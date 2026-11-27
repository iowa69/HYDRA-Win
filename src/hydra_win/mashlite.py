"""A pure-Python stand-in for ``mash dist`` against a Mash sketch file.

Upstream Hydra identifies species by running ``mash dist`` against every
sketch in its species folder: Kleborate's (the Enterobacterales) and, in
HYDRA-Win, the clinical sketch of 60 other species (hydra_win/data,
tools/build_species_sketch.py). Mash has no Windows build, and without it upstream
falls back to the MLST scheme, which misnames some genomes (several PubMLST
*E. coli* schemes type *Klebsiella* at full length). This module reproduces
what ``mash dist`` computes for an assembly query:

* reads the reference ``.msh`` file (an unpacked Cap'n Proto message, schema
  ``MinHash.capnp`` in the Mash sources) without a capnp library;
* sketches the query the way ``mash sketch`` does with the reference's
  parameters: upper-cased canonical k-mers, k-mers with non-ACGT characters
  skipped, MurmurHash3_x64_128 (first 64-bit word, the sketch's seed), bottom-s
  unique hashes over the whole file;
* computes the Mash distance ``-ln(2J / (1 + J)) / k`` from the bottom-s union
  exactly as ``CommandDistance::compareSketches`` does.

:func:`install` routes upstream's ``run(["mash", "dist", ...])`` here, so the
species logic itself (thresholds, conflict rules) stays upstream's.
"""

from __future__ import annotations

import math
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ------------------------------------------------------------ capnp reading
_MASK64 = (1 << 64) - 1


class _Message:
    """Minimal reader for an unpacked, possibly multi-segment, capnp message."""

    def __init__(self, data: bytes):
        self.data = memoryview(data)
        (count_minus_one,) = struct.unpack_from("<I", data, 0)
        count = count_minus_one + 1
        sizes = struct.unpack_from(f"<{count}I", data, 4)
        header_words = (4 + 4 * count + 7) // 8
        self.segments: list[int] = []  # byte offset of each segment
        offset = header_words * 8
        for size in sizes:
            self.segments.append(offset)
            offset += size * 8

    def word(self, segment: int, index: int) -> int:
        return struct.unpack_from("<Q", self.data, self.segments[segment] + index * 8)[0]

    def resolve(self, segment: int, index: int):
        """Follow far pointers. Returns (pointer word, segment, target word index)."""
        pointer = self.word(segment, index)
        kind = pointer & 3
        if kind == 2:  # far pointer
            double = (pointer >> 2) & 1
            pad_offset = (pointer >> 3) & ((1 << 29) - 1)
            pad_segment = pointer >> 32
            if not double:
                return self.resolve(pad_segment, pad_offset)
            far = self.word(pad_segment, pad_offset)
            tag = self.word(pad_segment, pad_offset + 1)
            target_offset = (far >> 3) & ((1 << 29) - 1)
            return tag, far >> 32, target_offset
        offset = (pointer >> 2) & ((1 << 30) - 1)
        if offset & (1 << 29):
            offset -= 1 << 30
        return pointer, segment, index + 1 + offset

    def struct_at(self, segment: int, index: int) -> "_Struct | None":
        pointer, seg, target = self.resolve(segment, index)
        if pointer == 0:
            return None
        if pointer & 3 != 0:
            raise ValueError("expected a struct pointer")
        data_words = (pointer >> 32) & 0xFFFF
        ptr_words = pointer >> 48
        return _Struct(self, seg, target, data_words, ptr_words)

    def list_at(self, segment: int, index: int):
        pointer, seg, target = self.resolve(segment, index)
        if pointer == 0:
            return None
        if pointer & 3 != 1:
            raise ValueError("expected a list pointer")
        element_size = (pointer >> 32) & 7
        count = pointer >> 35
        return element_size, count, seg, target


class _Struct:
    def __init__(self, message: _Message, segment: int, index: int, data_words: int,
                 ptr_words: int):
        self.m = message
        self.segment = segment
        self.index = index
        self.data_words = data_words
        self.ptr_words = ptr_words

    def uint32(self, slot: int, default: int = 0) -> int:
        if slot // 2 >= self.data_words:
            return default
        word = self.m.word(self.segment, self.index + slot // 2)
        return ((word >> (32 * (slot % 2))) & 0xFFFFFFFF) ^ default

    def bit(self, bit: int) -> bool:
        if bit // 64 >= self.data_words:
            return False
        return bool((self.m.word(self.segment, self.index + bit // 64) >> (bit % 64)) & 1)

    def _pointer_index(self, slot: int) -> int | None:
        if slot >= self.ptr_words:
            return None
        return self.index + self.data_words + slot

    def struct(self, slot: int) -> "_Struct | None":
        where = self._pointer_index(slot)
        return None if where is None else self.m.struct_at(self.segment, where)

    def text(self, slot: int) -> str:
        where = self._pointer_index(slot)
        if where is None:
            return ""
        found = self.m.list_at(self.segment, where)
        if found is None:
            return ""
        _size, count, seg, target = found
        start = self.m.segments[seg] + target * 8
        raw = bytes(self.m.data[start:start + count])
        return raw.rstrip(b"\x00").decode("utf-8", "replace")

    def uint64_list(self, slot: int) -> np.ndarray:
        where = self._pointer_index(slot)
        found = None if where is None else self.m.list_at(self.segment, where)
        if found is None:
            return np.zeros(0, dtype=np.uint64)
        size, count, seg, target = found
        if size != 5:
            raise ValueError("expected a List(UInt64)")
        start = self.m.segments[seg] + target * 8
        return np.frombuffer(self.m.data, dtype="<u8", count=count, offset=start).astype(np.uint64)

    def struct_list(self, slot: int) -> list["_Struct"]:
        where = self._pointer_index(slot)
        found = None if where is None else self.m.list_at(self.segment, where)
        if found is None:
            return []
        size, _words, seg, target = found
        if size != 7:
            raise ValueError("expected a composite list")
        tag = self.m.word(seg, target)
        count = (tag >> 2) & ((1 << 30) - 1)
        data_words = (tag >> 32) & 0xFFFF
        ptr_words = tag >> 48
        step = data_words + ptr_words
        return [_Struct(self.m, seg, target + 1 + i * step, data_words, ptr_words)
                for i in range(count)]


@dataclass
class Sketch:
    kmer_size: int
    sketch_size: int
    seed: int
    noncanonical: bool
    preserve_case: bool
    names: list[str]
    hashes: list[np.ndarray]  # sorted uint64 per reference


_SKETCH_CACHE: dict[str, Sketch] = {}


def read_sketch(path: Path | str) -> Sketch:
    """Parse a Mash ``.msh`` file (64-bit hashes only, which is what k > 16 uses)."""
    key = str(Path(path).resolve())
    if key in _SKETCH_CACHE:
        return _SKETCH_CACHE[key]
    message = _Message(Path(path).read_bytes())
    root = message.struct_at(0, 0)
    if root is None:
        raise ValueError(f"{path} is not a Mash sketch")
    # MinHash data section: kmerSize @0 -> u32 slot 0, minHashesPerWindow @2 ->
    # slot 2, concatenated @3 -> bit 96, error @6 -> slot 4, noncanonical @7 ->
    # bit 97, preserveCase @9 -> bit 98, hashSeed @10 -> slot 5 (default 42).
    # Pointers: referenceListOld @4 -> 0, locusList @5 -> 1, alphabet @8 -> 2,
    # referenceList @11 -> 3.
    kmer = root.uint32(0)
    size = root.uint32(2)
    seed = root.uint32(5, default=42)
    noncanonical = root.bit(97)
    preserve_case = root.bit(98)
    references = []
    for slot in (3, 0):  # Mash reads referenceList when it is non-empty
        ref_list = root.struct(slot)
        if ref_list is not None:
            references = ref_list.struct_list(0)
            if references:
                break
    names: list[str] = []
    hashes: list[np.ndarray] = []
    for ref in references:
        # Reference pointers: sequence @0, quality @1, name @3 -> 2, comment @4 -> 3,
        # hashes32 @5 -> 4, hashes64 @6 -> 5, counts32 @8 -> 6.
        names.append(ref.text(2))
        hashes.append(np.sort(ref.uint64_list(5)))
    if kmer <= 16:
        raise ValueError("32-bit (k <= 16) Mash sketches are not supported")
    sketch = Sketch(kmer, size, seed, noncanonical, preserve_case, names, hashes)
    _SKETCH_CACHE[key] = sketch
    return sketch


# --------------------------------------------------------------- hashing
_C1 = np.uint64(0x87C37B91114253D5)
_C2 = np.uint64(0x4CF5AD432745937F)


def _rotl(x: np.ndarray, r: int) -> np.ndarray:
    return (x << np.uint64(r)) | (x >> np.uint64(64 - r))


def _fmix(k: np.ndarray) -> np.ndarray:
    k = k ^ (k >> np.uint64(33))
    k = k * np.uint64(0xFF51AFD7ED558CCD)
    k = k ^ (k >> np.uint64(33))
    k = k * np.uint64(0xC4CEB9FE1A85EC53)
    return k ^ (k >> np.uint64(33))


def murmur3_x64_128_h1(keys: np.ndarray, seed: int) -> np.ndarray:
    """First 64-bit word of MurmurHash3_x64_128 for each row of a (n, length) uint8 array."""
    n, length = keys.shape
    h1 = np.full(n, seed, dtype=np.uint64)
    h2 = np.full(n, seed, dtype=np.uint64)
    with np.errstate(over="ignore"):
        nblocks = length // 16
        for b in range(nblocks):
            block = np.ascontiguousarray(keys[:, b * 16:(b + 1) * 16])
            words = block.view("<u8").reshape(n, 2).astype(np.uint64)
            k1 = words[:, 0] * _C1
            k1 = _rotl(k1, 31) * _C2
            h1 ^= k1
            h1 = _rotl(h1, 27) + h2
            h1 = h1 * np.uint64(5) + np.uint64(0x52DCE729)
            k2 = words[:, 1] * _C2
            k2 = _rotl(k2, 33) * _C1
            h2 ^= k2
            h2 = _rotl(h2, 31) + h1
            h2 = h2 * np.uint64(5) + np.uint64(0x38495AB5)
        tail = keys[:, nblocks * 16:].astype(np.uint64)
        rest = length & 15
        if rest > 8:
            k2 = np.zeros(n, dtype=np.uint64)
            for i in range(rest - 1, 7, -1):
                k2 ^= tail[:, i] << np.uint64(8 * (i - 8))
            k2 = k2 * _C2
            k2 = _rotl(k2, 33) * _C1
            h2 ^= k2
        if rest > 0:
            k1 = np.zeros(n, dtype=np.uint64)
            for i in range(min(rest, 8) - 1, -1, -1):
                k1 ^= tail[:, i] << np.uint64(8 * i)
            k1 = k1 * _C1
            k1 = _rotl(k1, 31) * _C2
            h1 ^= k1
        h1 ^= np.uint64(length)
        h2 ^= np.uint64(length)
        h1 = h1 + h2
        h2 = h2 + h1
        h1 = _fmix(h1)
        h2 = _fmix(h2)
        h1 = h1 + h2
    return h1


_COMPLEMENT = np.zeros(256, dtype=np.uint8)
for _a, _b in zip(b"ACGT", b"TGCA"):
    _COMPLEMENT[_a] = _b
_VALID = np.zeros(256, dtype=bool)
_VALID[list(b"ACGT")] = True


def _sequence_hashes(seq: bytes, k: int, seed: int, canonical: bool,
                     chunk: int = 1 << 19) -> np.ndarray:
    arr = np.frombuffer(seq, dtype=np.uint8)
    n = arr.size - k + 1
    if n <= 0:
        return np.zeros(0, dtype=np.uint64)
    invalid = np.concatenate(([0], np.cumsum(~_VALID[arr], dtype=np.int64)))
    ok = (invalid[k:] - invalid[:-k]) == 0
    forward = np.lib.stride_tricks.sliding_window_view(arr, k)
    if canonical:
        rc = _COMPLEMENT[arr][::-1].copy()
        reverse = np.lib.stride_tricks.sliding_window_view(rc, k)[::-1]
    out = []
    for start in range(0, n, chunk):
        stop = min(n, start + chunk)
        keep = ok[start:stop]
        if not keep.any():
            continue
        fw = forward[start:stop][keep]
        if canonical:
            rv = reverse[start:stop][keep]
            differ = fw != rv
            first = differ.argmax(axis=1)
            rows = np.arange(fw.shape[0])
            use_rc = differ[rows, first] & (rv[rows, first] < fw[rows, first])
            kmers = np.where(use_rc[:, None], rv, fw)
        else:
            kmers = fw
        out.append(murmur3_x64_128_h1(np.ascontiguousarray(kmers), seed))
    if not out:
        return np.zeros(0, dtype=np.uint64)
    return np.concatenate(out)


def sketch_fasta(path: Path | str, k: int, size: int, seed: int = 42,
                 canonical: bool = True, preserve_case: bool = False) -> np.ndarray:
    """Bottom-*size* unique hashes of every k-mer in a FASTA file (sorted)."""
    from hydra_amr.seqio import read_fasta  # noqa: PLC0415

    best = np.zeros(0, dtype=np.uint64)
    for _header, seq in read_fasta(path):
        text = seq if preserve_case else seq.upper()
        hashes = _sequence_hashes(text.encode("ascii", "replace"), k, seed, canonical)
        if hashes.size == 0:
            continue
        merged = np.unique(np.concatenate((best, hashes)))
        best = merged[:size]
    return best


def mash_distance(ref: np.ndarray, query: np.ndarray, k: int, size: int) -> tuple[float, int, int]:
    """(distance, shared, denominator) as ``mash dist`` reports them.

    ``CommandDistance::compareSketches`` walks both sorted lists until it has
    seen *size* distinct hashes or one list runs out, then tops the denominator
    up from the other list. That is the first ``min(size, |union|)`` elements of
    the sorted union, with the shared count taken over those elements only.
    """
    union = np.union1d(ref, query)[:size]
    denom = int(union.size)
    if denom == 0:
        return 1.0, 0, 0
    common = int(np.count_nonzero(np.isin(union, ref, assume_unique=True)
                                  & np.isin(union, query, assume_unique=True)))
    jaccard = common / denom
    if common == denom:
        distance = 0.0
    elif common == 0:
        distance = 1.0
    else:
        distance = -math.log(2 * jaccard / (1.0 + jaccard)) / k
    return distance, common, denom


#: Query sketches by (file, its size and mtime, sketch parameters). Kleborate's
#: sketch and the clinical one share their parameters, and upstream asks for
#: a genome's species before MLST and again after it, so without this every
#: genome would be hashed up to four times.
_QUERY_CACHE: dict[tuple, np.ndarray] = {}


def _query_hashes(query: Path | str, sketch: Sketch) -> np.ndarray:
    path = Path(query).resolve()
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, sketch.kmer_size, sketch.sketch_size,
           sketch.seed, sketch.noncanonical, sketch.preserve_case)
    if key not in _QUERY_CACHE:
        if len(_QUERY_CACHE) > 64:
            _QUERY_CACHE.clear()
        _QUERY_CACHE[key] = sketch_fasta(query, sketch.kmer_size, sketch.sketch_size,
                                         sketch.seed, canonical=not sketch.noncanonical,
                                         preserve_case=sketch.preserve_case)
    return _QUERY_CACHE[key]


def dist(sketch_path: Path | str, query: Path | str) -> list[tuple[str, float, int, int]]:
    """``mash dist SKETCH QUERY`` -> [(reference, distance, shared, denom)]."""
    sketch = read_sketch(sketch_path)
    query_hashes = _query_hashes(query, sketch)
    out = []
    for name, hashes in zip(sketch.names, sketch.hashes):
        distance, common, denom = mash_distance(hashes, query_hashes, sketch.kmer_size,
                                                sketch.sketch_size)
        out.append((name, distance, common, denom))
    return out


# ------------------------------------------------------------ integration
def _fake_mash(cmd: list[str]) -> subprocess.CompletedProcess:
    """Answer a ``mash dist [-p N] SKETCH QUERY`` command line in-process."""
    args = [a for a in cmd[2:]]
    positional = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in ("-p", "-m", "-k", "-s"):
            skip = True
            continue
        if token.startswith("-"):
            if token == "-r":
                return subprocess.CompletedProcess(cmd, 1, "", "reads input not supported")
            continue
        positional.append(token)
    if len(positional) != 2:
        return subprocess.CompletedProcess(cmd, 1, "", "expected SKETCH QUERY")
    sketch, query = positional
    lines = [f"{name}\t{query}\t{distance:g}\t0\t{common}/{denom}"
             for name, distance, common, denom in dist(sketch, query)]
    return subprocess.CompletedProcess(cmd, 0, "\n".join(lines) + "\n", "")


def install() -> None:
    """Make upstream's species identifier call this module instead of ``mash``."""
    from hydra_amr.typing import species  # noqa: PLC0415

    if getattr(species, "_hydra_win_mashlite", False):
        return
    # Used even where a real Mash exists, so every platform runs the same code.
    original_run = species.run
    original_have = species.have

    def have(tool: str) -> bool:
        return True if tool == "mash" else original_have(tool)

    def run(cmd, *args, **kwargs):
        if cmd and str(cmd[0]) == "mash" and len(cmd) > 1 and str(cmd[1]) == "dist":
            return _fake_mash([str(c) for c in cmd])
        return original_run(cmd, *args, **kwargs)

    species.have = have
    species.run = run
    species._hydra_win_mashlite = True
