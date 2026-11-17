#!/usr/bin/env python3
"""Check every reported mutation against the assembly itself, independently of HYDRA-Win.

    verify_mutations.py WORKBOOK.xlsx ASSEMBLY.fasta[.gz]

For each row of the Point_mutations sheet this re-reads the genome FASTA with
its own minimal parser and genetic code (nothing from hydra_amr or hydra_win):

* protein substitutions and stops: the codon at the reported contig coordinates
  and strand must be the reported isolate codon and encode the reported
  alternate residue; the reported (inferred) reference codon must encode the
  reported reference residue and differ from the isolate codon exactly as the
  reported base change and c. position say;
* nucleotide (rRNA / promoter) changes: the base at the reported position must
  be the reported alternate base, and the reference base the reported one;
* frameshifts: the codon where the reported new frame stops must be a stop.

Exits non-zero on any disagreement, or when a genome has no substitution to check.
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

BASES = "TCAG"
AMINO = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODE = {a + b + c: AMINO[16 * i + 4 * j + k]
        for i, a in enumerate(BASES) for j, b in enumerate(BASES) for k, c in enumerate(BASES)}
COMPLEMENT = str.maketrans("ACGTN", "TGCAN")
LOCATION = re.compile(r"^(?P<contig>\S+?):(?P<lo>\d+)(?:-(?P<hi>\d+))? \((?P<strand>[+-])\)")
PROTEIN = re.compile(r"^(?P<ref>[A-Z])(?P<pos>\d+)(?P<alt>[A-Z]|Ter)$")
CDS = re.compile(r"^c\.(?P<pos>\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])")
NUC = re.compile(r"^[cn]\.(?P<pos>-?\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])")
STOP_AT = re.compile(r"stops at (?P<codon>[ACGT]{3}) \((?P<contig>\S+?):(?P<lo>\d+)-(?P<hi>\d+)\)")


def revcomp(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


def read_fasta(path: Path) -> dict[str, str]:
    opener = gzip.open if path.name.endswith(".gz") else open
    out: dict[str, list[str]] = {}
    name = None
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(">"):
                name = line[1:].split()[0]
                out[name] = []
            elif name is not None:
                out[name].append(line.upper())
    return {k: "".join(v) for k, v in out.items()}


def rows(workbook: Path) -> list[dict]:
    from openpyxl import load_workbook  # noqa: PLC0415

    values = list(load_workbook(workbook, read_only=True)["Point_mutations"].iter_rows(
        values_only=True))
    header = values[0]
    return [dict(zip(header, r)) for r in values[1:] if any(v is not None for v in r)]


def bases_at(genome: dict[str, str], contig: str, lo: int, hi: int, strand: str) -> str:
    seq = genome[contig][lo - 1:hi]
    return revcomp(seq) if strand == "-" else seq


def verify(workbook: Path, fasta: Path) -> tuple[int, list[str]]:
    genome = read_fasta(fasta)
    problems: list[str] = []
    checked = 0
    substitutions = 0
    for row in rows(workbook):
        name = row.get("Mutation")
        kind = row.get("Type of call") or ""
        where = LOCATION.match(row.get("Mutation position on contig") or "")
        observed = row.get("Isolate codon / base (read from the assembly)") or ""
        if kind in ("Amino-acid substitution", "Nonsense (premature stop codon)",
                    "Gene disruption: premature stop codon"):
            change = PROTEIN.match(row.get("Protein change") or "")
            if not (where and change):
                problems.append(f"{name}: no codon location or protein change to check "
                                f"({row.get('Not resolved')})")
                continue
            lo, hi = int(where["lo"]), int(where["hi"] or where["lo"])
            if hi - lo != 2 or where["contig"] not in genome:
                problems.append(f"{name}: location {where.group(0)} is not one codon of the genome")
                continue
            codon = bases_at(genome, where["contig"], lo, hi, where["strand"])
            alt = "*" if change["alt"] == "Ter" else change["alt"]
            if codon != observed:
                problems.append(f"{name}: FASTA has {codon} at {where.group(0)}, sheet says {observed}")
            if CODE.get(codon) != alt:
                problems.append(f"{name}: {codon} encodes {CODE.get(codon)}, not {alt}")
            reference = row.get("Reference codon (INFERRED by parsimony, no reference CDS)") or \
                row.get("Reference codon / base (from a reference sequence)") or ""
            if len(reference) == 3:
                if CODE.get(reference) != change["ref"]:
                    problems.append(f"{name}: reference codon {reference} encodes "
                                    f"{CODE.get(reference)}, not {change['ref']}")
                cds = CDS.match(row.get("Nucleotide change") or "")
                diffs = [i for i in range(3) if reference[i] != codon[i]]
                if not cds:
                    problems.append(f"{name}: no single-base c. change for {reference}>{codon}")
                else:
                    pos = int(cds["pos"])
                    i = (pos - 1) % 3
                    if (pos - 1) // 3 + 1 != int(change["pos"]):
                        problems.append(f"{name}: c.{pos} is not in codon {change['pos']}")
                    if diffs != [i] or reference[i] != cds["ref"] or codon[i] != cds["alt"]:
                        problems.append(f"{name}: {reference}->{codon} does not differ as "
                                        f"{cds.group(0)} says")
            substitutions += kind == "Amino-acid substitution"
            checked += 1
        elif kind in ("rRNA base change", "Promoter / upstream base change", "Nucleotide change"):
            change = NUC.match(row.get("Nucleotide change") or "")
            if not (where and change):
                problems.append(f"{name}: no base location or nucleotide change to check")
                continue
            base = bases_at(genome, where["contig"], int(where["lo"]), int(where["lo"]),
                            where["strand"])
            if base != observed or base != change["alt"]:
                problems.append(f"{name}: FASTA has {base} at {where.group(0)}; sheet says "
                                f"{observed}, change {change.group(0)}")
            if (row.get("Reference codon / base (from a reference sequence)") or "") != change["ref"]:
                problems.append(f"{name}: reference base does not match {change.group(0)}")
            checked += 1
        elif kind.startswith("Gene disruption: frameshift"):
            stop = STOP_AT.search(observed)
            if not (stop and where):
                problems.append(f"{name}: no stop codon location to check")
                continue
            codon = bases_at(genome, stop["contig"], int(stop["lo"]), int(stop["hi"]),
                             where["strand"])
            if codon != stop["codon"] or CODE.get(codon) != "*":
                problems.append(f"{name}: FASTA has {codon} where the new frame is said to stop")
            checked += 1
    if not substitutions:
        problems.append(f"{workbook.name}: no protein substitution was checked")
    return checked, problems


def main(argv: list[str]) -> int:
    checked, problems = verify(Path(argv[1]), Path(argv[2]))
    for problem in problems:
        print("PROBLEM:", problem)
    print(f"{Path(argv[1]).name}: {checked} mutation rows checked against "
          f"{Path(argv[2]).name}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
