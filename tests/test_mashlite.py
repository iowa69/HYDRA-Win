"""The clinical sketch as shipped, and how mashlite reads it next to Kleborate's."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from hydra_amr.typing.species import _clean_sketch_name
from hydra_win import databases, mashlite

ROOT = Path(__file__).resolve().parent.parent
SPECIES_LIST = ROOT / "tools" / "clinical_species.tsv"


def listed_species() -> list[str]:
    out = []
    for line in SPECIES_LIST.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith(("#", "species\t")):
            out.append(line.split("\t")[0])
    return out


@pytest.fixture(scope="module")
def clinical():
    return mashlite.read_sketch(databases.CLINICAL_SKETCH)


def test_the_clinical_sketch_has_kleborates_parameters(clinical):
    # One query sketch serves both files only because the parameters match.
    assert (clinical.kmer_size, clinical.sketch_size, clinical.seed) == (21, 1000, 42)
    assert not clinical.noncanonical


def test_every_listed_species_is_in_the_sketch_and_nothing_else(clinical):
    named = {_clean_sketch_name(name) for name in clinical.names}
    assert "" not in named          # every reference carries its taxon, as Kleborate's do
    assert named == set(listed_species())


def test_the_sources_table_lists_exactly_the_genomes_in_the_sketch(clinical):
    rows = [line.split("\t") for line in
            databases.CLINICAL_SOURCES.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith(("#", "species\t"))]
    in_sketch = {f"{r[0].replace(' ', '_')}/{r[2]}.fna.gz" for r in rows if r[1] == "sketch"}
    assert in_sketch == set(clinical.names)
    held_out = {r[2] for r in rows if r[1] == "validation"}
    assert held_out and not held_out & {r[2] for r in rows if r[1] == "sketch"}


def _fasta(path: Path, length: int = 30_000) -> Path:
    rng = random.Random(1)
    path.write_text(">c1\n" + "".join(rng.choice("ACGT") for _ in range(length)) + "\n")
    return path


def test_a_genome_is_sketched_once_for_every_sketch_file(tmp_path, monkeypatch):
    first = shutil.copy(databases.CLINICAL_SKETCH, tmp_path / "a.msh")
    second = shutil.copy(databases.CLINICAL_SKETCH, tmp_path / "b.msh")
    query = _fasta(tmp_path / "q.fasta")
    calls = []
    real = mashlite.sketch_fasta

    def counting(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(mashlite, "sketch_fasta", counting)
    one = mashlite.dist(first, query)
    two = mashlite.dist(second, query)
    assert [d for _n, d, _s, _t in one] == [d for _n, d, _s, _t in two]
    assert len(calls) == 1

    # A changed file is a different genome.
    _fasta(query, length=40_000)
    mashlite.dist(first, query)
    assert len(calls) == 2
