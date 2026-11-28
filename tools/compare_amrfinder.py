"""Compare HYDRA-Win's AMR calls with NCBI AMRFinderPlus on the same genomes and database.

HYDRA-Win does not run AMRFinderPlus: NCBI builds it for Linux and macOS only.
It searches AMRFinderPlus's database with its own BLAST code (upstream Hydra's
protein and mutation engines). This measures how closely the two agree, on the
same genomes, the same database release and the same organism.

1. ``--pick`` draws, for each species below, a seeded random sample of RefSeq
   assemblies that pass NCBI's ANI taxonomy check (one complete genome and two
   drafts, the kind a user brings) and writes tools/amrfinder_benchmark.tsv.
   The list is committed, so every run compares the same genomes.
2. The genomes are downloaded and analysed by HYDRA-Win exactly as the Windows
   app does it (``hydra_win.core.analyse``, offline, on ``--hydra-db``).
3. ``amrfinder -n --plus`` runs on the same FASTA, with ``-O`` set to the
   organism HYDRA-Win assigned, against ``--amrfinder-db``, which should be the
   release the HYDRA-Win database was built from.
4. Gene calls are paired by contig and position (at least half of the shorter
   one overlapping) and compared by name and method; point mutations are
   compared by AMRFinderPlus symbol. The report lists every difference.

Run by a maintainer on Linux, not by the release workflow:

    python tools/compare_amrfinder.py --pick            # only to redraw the genomes
    HYDRA_WIN_BLAST=$(dirname $(which blastx)) python tools/compare_amrfinder.py \\
        --amrfinder $(which amrfinder) --amrfinder-db ~/amrfinder-db/2026-10-29.1 \\
        --hydra-db ~/HYDRA-Win/db --work /tmp/afp-bench
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import pickle
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import build_species_sketch as ncbi  # noqa: E402  (NCBI Datasets queries and downloads)

GENOMES = ROOT / "tools" / "amrfinder_benchmark.tsv"
REPORT = ROOT / "docs" / "amrfinder_comparison.md"
GENOME_COLUMNS = ("species", "accession", "assembly_name", "level", "strain")

#: Species with an AMRFinderPlus organism (mutation catalogue), and the
#: Enterobacterales and non-fermenters that carry most acquired resistance.
SPECIES = (
    "Klebsiella pneumoniae", "Escherichia coli", "Salmonella enterica",
    "Enterobacter hormaechei", "Citrobacter freundii", "Serratia marcescens",
    "Acinetobacter baumannii", "Pseudomonas aeruginosa", "Staphylococcus aureus",
    "Enterococcus faecium", "Enterococcus faecalis", "Streptococcus pneumoniae",
    "Streptococcus agalactiae", "Neisseria gonorrhoeae", "Campylobacter jejuni",
    "Clostridioides difficile",
)

#: amrfinder Method -> the comparison's class of call.
def method_class(method: str) -> str:
    m = method.upper()
    if m.startswith(("EXACT", "ALLELE")):
        return "exact"
    if m.startswith("BLAST"):
        return "complete"
    if m.startswith("PARTIAL_CONTIG_END") or m == "CONTIG_END":
        return "contig end"
    if m.startswith("PARTIAL"):
        return "partial"
    if m.startswith("INTERNAL_STOP"):
        return "internal stop"
    if m == "HMM":
        return "HMM only"
    return m.lower()


@dataclass
class Call:
    """One gene call, from either tool, in the comparison's own terms."""

    contig: str
    start: int
    end: int
    symbol: str
    method: str
    kind: str          # method_class()
    element_type: str
    identity: float
    coverage: float
    reference: str = ""

    def overlap(self, other: Call) -> bool:
        if self.contig != other.contig:
            return False
        shared = min(self.end, other.end) - max(self.start, other.start) + 1
        return shared >= 0.5 * min(self.end - self.start + 1, other.end - other.start + 1)

    def text(self) -> str:
        return (f"{self.symbol} ({self.method}, {self.identity:.1f}% id, "
                f"{self.coverage:.1f}% cov)")


# --------------------------------------------------------------- genome list
def pick(out: Path) -> None:
    rows = []
    for species in SPECIES:
        rng = random.Random(f"{species}/amrfinder-benchmark")
        complete = [g for g in (ncbi.genome_from(r, species)
                                for r in ncbi.reports(species, "complete_genome", 300)) if g]
        drafts = [g for g in (ncbi.genome_from(r, species)
                              for r in ncbi.reports(species, "contig", 300)
                              + ncbi.reports(species, "scaffold", 300)) if g]
        rng.shuffle(complete)
        rng.shuffle(drafts)
        chosen = complete[:1] + drafts[:2]
        print(f"{species}: {len(complete)} complete, {len(drafts)} drafts -> "
              f"{', '.join(g.accession for g in chosen)}")
        rows += [{"species": species, "accession": g.accession,
                  "assembly_name": g.assembly_name, "level": g.level, "strain": g.strain}
                 for g in chosen]
    with open(out, "w", newline="") as handle:
        handle.write("# Genomes tools/compare_amrfinder.py compares HYDRA-Win and AMRFinderPlus on.\n"
                     "# Drawn by --pick: per species, one complete genome and two drafts, a seeded\n"
                     "# random sample of RefSeq assemblies that pass NCBI's ANI taxonomy check.\n")
        writer = csv.DictWriter(handle, GENOME_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_genomes(path: Path) -> list[dict]:
    with open(path) as handle:
        lines = [line for line in handle if not line.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def fetch(rows: list[dict], work: Path) -> dict[str, Path]:
    """accession -> plain FASTA, the same file both tools read."""
    fasta_dir = work / "fasta"
    fasta_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for row in rows:
        target = fasta_dir / f"{row['accession']}.fna"
        if not target.exists():
            genome = ncbi.Genome(species=row["species"], accession=row["accession"],
                                 assembly_name=row["assembly_name"], level=row["level"],
                                 strain=row["strain"], category="", ani_status="", ani=None,
                                 completeness=None, contamination=None, length=0)
            ncbi.download(genome, work / "download")
            with gzip.open(genome.path, "rb") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        out[row["accession"]] = target
    return out


# --------------------------------------------------------------- HYDRA-Win
def run_hydra(fastas: dict[str, Path], hydra_db: Path, work: Path, threads: int,
              tag: str) -> None:
    """Analyse *fastas* and keep each SampleResult under work/hydra-results."""
    os.environ["HYDRA_WIN_DB"] = str(hydra_db)
    os.environ["HYDRA_WIN_HOME"] = str(work / f"hydra-home-{tag}")
    from hydra_win import core  # noqa: PLC0415 - after the environment is set

    outdir = work / f"hydra-{tag}"
    if outdir.exists():
        shutil.rmtree(outdir)
    result = core.analyse(list(fastas.values()), outdir, offline=True, threads=threads)
    keep = work / "hydra-results"
    keep.mkdir(exist_ok=True)
    for sample in result.results:
        with open(keep / f"{sample.sample}.pickle", "wb") as handle:
            pickle.dump(sample, handle)


def load_hydra(work: Path, accessions) -> dict:
    out = {}
    for acc in accessions:
        path = work / "hydra-results" / f"{acc}.pickle"
        if path.exists():
            with open(path, "rb") as handle:
                out[acc] = pickle.load(handle)
    return out


def hydra_calls(result) -> tuple[list[Call], set[str]]:
    """The protein engine's gene calls, and every point-mutation symbol."""
    from hydra_win.excel import MUTATION_METHODS  # noqa: PLC0415

    genes, mutations = [], set()
    for hit in result.hits:
        if hit.mutation is not None and (hit.resolution == "POINT"
                                         or hit.method in MUTATION_METHODS):
            if hit.resolution != "CONTIG_END":
                mutations.add(hit.mutation.symbol)
            continue
        if hit.database != "protein" or hit.method not in ("EXACTX", "BLASTX", "PARTIALX",
                                                           "INTERNAL_STOP"):
            continue
        kind = method_class(hit.method)
        if hit.resolution == "CONTIG_END":
            kind = "contig end"
        genes.append(Call(hit.sequence, int(hit.start), int(hit.end), hit.gene, hit.method,
                          kind, hit.element_type, float(hit.identity_pct),
                          float(hit.coverage_pct), hit.accession))
    return genes, mutations


def summary_calls(result) -> list[Call]:
    """Every AMR locus the workbook judges: kind 'counted', 'check' or 'other'.

    'other' is a confident call only catalogues other than AMRFinderPlus make,
    which the Summary lists apart and does not count.
    """
    from hydra_win import calls, excel  # noqa: PLC0415

    out = []
    for locus, verdict in excel.amr_verdicts(result.hits):
        hit = locus.primary
        if not calls.reported_by_amrfinderplus(locus.calls):
            kind = "other" if verdict.confident else "other, weak"
        else:
            kind = "counted" if verdict.confident else "check"
        out.append(Call(hit.sequence, int(hit.start), int(hit.end), excel.named(hit),
                        hit.database, kind, "AMR", float(hit.identity_pct),
                        float(hit.coverage_pct), verdict.reason))
    return out


# --------------------------------------------------------------- AMRFinderPlus
def amrfinder_organisms(amrfinder: str, db: Path) -> set[str]:
    text = subprocess.run([amrfinder, "-l", "-d", str(db)], capture_output=True, text=True,
                          env=_tool_env(amrfinder), check=True).stdout
    listed = text.split(":", 1)[-1]
    return {name.strip() for name in listed.replace("\n", ",").split(",") if name.strip()}


def _tool_env(amrfinder: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path(amrfinder).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_amrfinder(amrfinder: str, db: Path, fasta: Path, organism: str | None, out: Path,
                  threads: int) -> Path:
    stamp = out.with_suffix(".organism")
    if out.exists() and stamp.exists() and stamp.read_text() == (organism or ""):
        return out
    cmd = [amrfinder, "-n", str(fasta), "--plus", "-d", str(db), "--threads", str(threads),
           "-o", str(out)]
    if organism:
        cmd += ["-O", organism]
    subprocess.run(cmd, check=True, capture_output=True, env=_tool_env(amrfinder))
    stamp.write_text(organism or "")
    return out


def susceptible_references(db: Path) -> set[str]:
    """Accessions of AMRFinderPlus's susceptible references (mosaic PBPs and the like)."""
    path = db / "AMRProt-susceptible.tsv"
    if not path.exists():
        return set()
    with open(path) as handle:
        rows = list(csv.DictReader((line.lstrip("#") for line in handle), delimiter="\t"))
    return {row.get("accession_version", "").strip() for row in rows}


def amrfinder_calls(path: Path, susceptible: set[str] = frozenset()) -> tuple[list[Call], set[str]]:
    genes, mutations = [], set()
    with open(path) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            subtype = row.get("Subtype") or row.get("Element subtype", "")
            symbol = row.get("Element symbol") or row.get("Gene symbol", "")
            method = row.get("Method", "")
            if subtype in ("POINT", "POINT_DISRUPT") or method.startswith("POINT"):
                mutations.add(symbol)
                continue
            def number(name):
                try:
                    return float(row.get(name) or 0)
                except ValueError:
                    return 0.0
            reference = row.get("Closest reference accession", "")
            kind = "susceptible" if reference in susceptible else method_class(method)
            genes.append(Call(row["Contig id"], int(row["Start"]), int(row["Stop"]), symbol,
                              method, kind,
                              row.get("Type") or row.get("Element type", ""),
                              number("% Identity to reference"), number("% Coverage of reference"),
                              row.get("Closest reference accession", "")))
    return genes, mutations


# --------------------------------------------------------------- comparison
@dataclass
class Pair:
    accession: str
    species: str
    afp: Call | None
    hydra: Call | None


def pair_calls(afp: list[Call], hydra: list[Call]) -> list[tuple[Call | None, Call | None]]:
    """One-to-one pairs of overlapping calls; unpaired calls on either side."""
    candidates = []
    for i, a in enumerate(afp):
        for j, h in enumerate(hydra):
            if a.overlap(h):
                shared = min(a.end, h.end) - max(a.start, h.start)
                candidates.append((-(a.symbol == h.symbol), -shared, i, j))
    used_a, used_h, pairs = set(), set(), []
    for _, _, i, j in sorted(candidates):
        if i in used_a or j in used_h:
            continue
        used_a.add(i)
        used_h.add(j)
        pairs.append((afp[i], hydra[j]))
    pairs += [(a, None) for i, a in enumerate(afp) if i not in used_a]
    pairs += [(None, h) for j, h in enumerate(hydra) if j not in used_h]
    return pairs


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def _summary_section(summary: list[Pair]) -> tuple[list[str], dict]:
    """AMRFinderPlus's complete calls against the genes HYDRA-Win's Summary counts."""
    def complete(call):
        return call is not None and call.kind in ("exact", "complete")

    def counted(call):
        return call is not None and call.kind == "counted"

    both = [p for p in summary if complete(p.afp) and counted(p.hydra)]
    afp_only = [p for p in summary if complete(p.afp) and not counted(p.hydra)]
    hydra_only = [p for p in summary if counted(p.hydra) and not complete(p.afp)]
    neither = [p for p in summary if p.afp and not complete(p.afp) and p.hydra
               and not counted(p.hydra)]
    other = [p for p in summary if p.hydra and p.hydra.kind == "other" and not p.afp]
    total = len(both) + len(afp_only)
    lines = ["## What the Summary counts", "",
             "The Summary counts an AMR gene only as a confident call (`hydra_win.calls`). "
             "Here every AMR locus HYDRA-Win judges is paired with AMRFinderPlus's call at the "
             "same place, whichever database HYDRA-Win's call came from. AMRFinderPlus "
             "*complete* means EXACT, ALLELE or BLAST; partial, contig-end and internal-stop "
             "calls are not complete.", ""]
    lines += _table(["", "loci"], [
        ["complete in AMRFinderPlus and counted by HYDRA-Win", len(both)],
        ["complete in AMRFinderPlus, not counted by HYDRA-Win", len(afp_only)],
        ["not complete in AMRFinderPlus, not counted by HYDRA-Win", len(neither)],
        ["counted by HYDRA-Win, not complete in AMRFinderPlus (or not called by it)",
         len(hydra_only)],
        ["listed apart as other catalogues only, not called by AMRFinderPlus", len(other)],
    ])
    lines += ["", f"{len(both)} of {total} complete AMRFinderPlus calls are counted "
              f"({100.0 * len(both) / total:.1f}%)." if total else "", ""]
    uncalled = [p for p in hydra_only if p.afp is None]
    listed = afp_only + [p for p in hydra_only if p.afp is not None]
    if other:
        by_db = Counter(p.hydra.method for p in other)
        names = Counter(p.hydra.symbol.split(" (closest")[0] for p in other)
        lines += [f"{len(other)} confident calls sit where AMRFinderPlus calls nothing. Only "
                  "other catalogues make them, so the Summary lists them under 'other "
                  "catalogues only' and does not count them. By database: "
                  + ", ".join(f"{db} {n}" for db, n in by_db.most_common()) + ". Most are "
                  "chromosomal efflux pumps, their regulators and other housekeeping genes "
                  "NCBI leaves out of AMRFinderPlus. The most frequent:", ""]
        lines += _table(["gene (database name)", "genomes"],
                        [[name, n] for name, n in names.most_common(15)])
        lines.append("")
    rows = [[p.accession, p.species, p.afp.text() if p.afp else "-",
             (f"{p.hydra.symbol} ({p.hydra.method}, {p.hydra.identity:.1f}% id, "
              f"{p.hydra.coverage:.1f}% cov): {p.hydra.kind}"
              + (f" - {p.hydra.reference}" if p.hydra.reference else "")) if p.hydra else "-"]
            for p in listed]
    if rows:
        lines += ["Every locus where AMRFinderPlus makes a call and the two disagree:", ""]
        lines += _table(["genome", "species", "AMRFinderPlus", "HYDRA-Win Summary"], rows)
        lines.append("")
    if uncalled:
        lines += ["Counted by HYDRA-Win where AMRFinderPlus calls nothing:", ""]
        lines += _table(["genome", "species", "HYDRA-Win Summary"],
                        [[p.accession, p.species,
                          f"{p.hydra.symbol} ({p.hydra.method}, {p.hydra.identity:.1f}% id, "
                          f"{p.hydra.coverage:.1f}% cov)"] for p in uncalled])
        lines.append("")
    return lines, {"summary_both": len(both), "summary_afp_only": len(afp_only),
                   "summary_hydra_only": len(hydra_only), "summary_other": len(other)}


def write_report(path: Path, genomes: list[dict], pairs: list[Pair],
                 mutation_rows: list[tuple], versions: dict, organisms: dict,
                 summary: list[Pair] = ()) -> dict:
    amr = [p for p in pairs if (p.afp or p.hydra).element_type == "AMR"]
    afp_calls = [p for p in amr if p.afp]
    hmm_only = [p for p in afp_calls if p.afp.kind == "HMM only"]
    susceptible = [p for p in afp_calls if p.afp.kind == "susceptible"]
    comparable = [p for p in afp_calls if p.afp.kind not in ("HMM only", "susceptible")]
    found = [p for p in comparable if p.hydra]
    same = [p for p in found if p.hydra.symbol == p.afp.symbol]
    renamed = [p for p in found if p.hydra.symbol != p.afp.symbol]
    missed = [p for p in comparable if not p.hydra]
    extra = [p for p in amr if p.hydra and not p.afp]
    hmm_found = [p for p in hmm_only if p.hydra]
    kind_differs = [p for p in found if p.afp.kind != p.hydra.kind]
    other = [p for p in pairs if (p.afp or p.hydra).element_type != "AMR"]
    other_agree = sum(1 for p in other if p.afp and p.hydra and p.afp.symbol == p.hydra.symbol)
    mut_afp = sum(len(a) for _, _, a, _ in mutation_rows)
    mut_both = sum(len(a & h) for _, _, a, h in mutation_rows)
    mut_afp_only = [(acc, s) for acc, _, a, h in mutation_rows for s in sorted(a - h)]
    mut_hydra_only = [(acc, s) for acc, _, a, h in mutation_rows for s in sorted(h - a)]

    def pct(n, d):
        return f"{100.0 * n / d:.1f}%" if d else "-"

    lines = [
        "# HYDRA-Win and AMRFinderPlus: the same genomes, the same database",
        "",
        "Generated by `tools/compare_amrfinder.py`. HYDRA-Win does not run AMRFinderPlus "
        "(NCBI builds it for Linux and macOS only); it searches AMRFinderPlus's database with "
        "upstream Hydra's own BLAST code. This compares the two on the same FASTA files, the "
        "same database release and the same organism (`-O` is the organism HYDRA-Win "
        "assigned).",
        "",
        f"* AMRFinderPlus {versions['amrfinder']}, database {versions['amrfinder_db']}, run "
        "with `-n --plus`.",
        f"* HYDRA-Win {versions['hydra_win']} (upstream Hydra {versions['upstream']}), "
        f"database {versions['hydra_db']}, run offline through `hydra_win.core.analyse`.",
        f"* {len(genomes)} genomes of {len({g['species'] for g in genomes})} species "
        f"(`tools/amrfinder_benchmark.tsv`), run on {versions['date']}.",
        "",
        "## AMR genes",
        "",
        "Gene calls of type AMR from HYDRA-Win's AMRFinderPlus protein search, paired with "
        "AMRFinderPlus's by contig and position.",
        "",
    ]
    lines += _table(["", "calls", "share"], [
        ["AMRFinderPlus calls (BLAST-based)", len(comparable), ""],
        ["found by HYDRA-Win at the same place", len(found), pct(len(found), len(comparable))],
        ["... under the same name", len(same), pct(len(same), len(comparable))],
        ["... under another name", len(renamed), pct(len(renamed), len(comparable))],
        ["missed by HYDRA-Win", len(missed), pct(len(missed), len(comparable))],
        ["found only by HYDRA-Win", len(extra), ""],
        ["AMRFinderPlus HMM-only calls (HYDRA-Win has no HMM search)", len(hmm_only),
         f"{len(hmm_found)} found by HYDRA-Win anyway"],
        ["AMRFinderPlus susceptible-reference calls (see below)", len(susceptible), ""],
        ["paired calls whose class differs (complete / partial / exact)", len(kind_differs), ""],
    ])
    lines += ["", f"STRESS and VIRULENCE elements (`--plus`): {len(other)} calls in all, "
              f"{other_agree} found by both under the same name.", ""]
    if susceptible:
        lines += ["## Susceptible-reference calls", "",
                  "AMRFinderPlus also reports a protein whose divergence from a *susceptible* "
                  "reference is itself the resistance (the mosaic PBPs of *S. pneumoniae* and "
                  "*N. gonorrhoeae*). Since its 4.x databases these references are in "
                  "`AMRProt-susceptible.fa`, which upstream Hydra does not import, so HYDRA-Win "
                  "does not make these calls; the catalogued point mutations in the same genes "
                  "are compared under Point mutations.", ""]
        lines += _table(["genome", "species", "AMRFinderPlus"],
                        [[p.accession, p.species, p.afp.text()] for p in susceptible])
        lines.append("")
    summary_lines, summary_counts = _summary_section(list(summary))
    lines += summary_lines
    lines += ["## Point mutations", "",
              f"AMRFinderPlus reports {mut_afp} point mutations and disruptions; HYDRA-Win "
              f"reports {mut_both} of them under the same symbol, misses "
              f"{len(mut_afp_only)} and reports {len(mut_hydra_only)} that AMRFinderPlus "
              "does not.", ""]
    if mut_afp_only or mut_hydra_only:
        lines += _table(["genome", "AMRFinderPlus only", "HYDRA-Win only"], [
            [acc, ", ".join(s for a, s in mut_afp_only if a == acc) or "-",
             ", ".join(s for a, s in mut_hydra_only if a == acc) or "-"]
            for acc in sorted({a for a, _ in mut_afp_only + mut_hydra_only})])
        lines.append("")
    lines += ["## Every AMR gene difference", ""]
    diff_rows = [[p.accession, p.species, p.afp.text() if p.afp else "-",
                  p.hydra.text() if p.hydra else "-"]
                 for p in renamed + missed + extra + kind_differs]
    seen = set()
    unique_rows = []
    for row in diff_rows:
        if tuple(row) not in seen:
            seen.add(tuple(row))
            unique_rows.append(row)
    lines += _table(["genome", "species", "AMRFinderPlus", "HYDRA-Win"], unique_rows) \
        if unique_rows else ["None."]
    lines += ["", "## Genomes", ""]
    lines += _table(["species", "accession", "level", "organism (-O)", "AMR genes (AMRFinderPlus)"],
                    [[g["species"], g["accession"], g["level"], organisms.get(g["accession"]) or "-",
                      sum(1 for p in amr if p.accession == g["accession"] and p.afp)]
                     for g in genomes])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"comparable": len(comparable), "susceptible": len(susceptible),
            "found": len(found), "same": len(same),
            "renamed": len(renamed), "missed": len(missed), "extra": len(extra),
            "hmm_only": len(hmm_only), "kind_differs": len(kind_differs),
            "mut_afp": mut_afp, "mut_both": mut_both, "mut_afp_only": len(mut_afp_only),
            "mut_hydra_only": len(mut_hydra_only), **summary_counts}


# --------------------------------------------------------------- main
def _version(cmd: list[str], env=None) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env).stdout.strip() \
            .splitlines()[-1]
    except (OSError, IndexError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pick", action="store_true", help="redraw the genome list and exit")
    parser.add_argument("--genomes", type=Path, default=GENOMES)
    parser.add_argument("--amrfinder")
    parser.add_argument("--amrfinder-db", type=Path)
    parser.add_argument("--hydra-db", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--only", nargs="*", help="accessions to run (default: all)")
    parser.add_argument("--shard", help="I/N: run HYDRA-Win on every Nth genome from the Ith "
                        "and stop; a later --reuse-hydra run compares them all")
    parser.add_argument("--reuse-hydra", action="store_true",
                        help="compare the HYDRA-Win results already in --work")
    args = parser.parse_args(argv)
    if args.pick:
        pick(args.genomes)
        return 0
    for name in ("amrfinder", "amrfinder_db", "hydra_db", "work"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required")
    genomes = read_genomes(args.genomes)
    if args.only:
        genomes = [g for g in genomes if g["accession"] in args.only]
    work = args.work
    work.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if args.shard:
        index, count = (int(x) for x in args.shard.split("/"))
        genomes = genomes[index - 1::count]
    fastas = fetch(genomes, work)
    print(f"{len(fastas)} genomes ready ({time.time() - started:.0f} s)", flush=True)
    if not args.reuse_hydra:
        run_hydra(fastas, args.hydra_db, work, args.threads,
                  tag=args.shard.replace("/", "of") if args.shard else "all")
        print(f"HYDRA-Win done ({time.time() - started:.0f} s)", flush=True)
    if args.shard:
        return 0
    results = load_hydra(work, fastas)
    known = amrfinder_organisms(args.amrfinder, args.amrfinder_db)
    susceptible = susceptible_references(args.amrfinder_db)
    afp_dir = work / "amrfinder"
    afp_dir.mkdir(exist_ok=True)
    pairs, mutation_rows, organisms, summary = [], [], {}, []
    for g in genomes:
        acc = g["accession"]
        result = results.get(acc)
        if result is None:
            print(f"{acc}: HYDRA-Win produced no result", file=sys.stderr)
            continue
        organism = result.species.organism if result.species.organism in known else None
        organisms[acc] = organism
        table = run_amrfinder(args.amrfinder, args.amrfinder_db, fastas[acc], organism,
                              afp_dir / f"{acc}.tsv", args.threads)
        afp_genes, afp_mut = amrfinder_calls(table, susceptible)
        hy_genes, hy_mut = hydra_calls(result)
        pairs += [Pair(acc, g["species"], a, h) for a, h in pair_calls(afp_genes, hy_genes)]
        afp_amr = [c for c in afp_genes if c.element_type == "AMR" and c.kind != "susceptible"]
        summary += [Pair(acc, g["species"], a, h)
                    for a, h in pair_calls(afp_amr, summary_calls(result))]
        mutation_rows.append((acc, g["species"], afp_mut, hy_mut))
    from hydra_win import UPSTREAM_COMMIT, __version__  # noqa: PLC0415

    env = _tool_env(args.amrfinder)
    db_version = (args.amrfinder_db / "version.txt").read_text().strip() \
        if (args.amrfinder_db / "version.txt").exists() else args.amrfinder_db.name
    import json  # noqa: PLC0415

    manifest = json.loads((args.hydra_db / "manifest.json").read_text())
    entry = manifest.get("protein") or manifest.get("databases", {}).get("protein", {})
    versions = {"amrfinder": _version([args.amrfinder, "--version"], env),
                "amrfinder_db": db_version, "hydra_win": __version__,
                "upstream": UPSTREAM_COMMIT[:7], "hydra_db": entry.get("version", "unknown"),
                "date": time.strftime("%Y-%m-%d")}
    counts = write_report(args.report, genomes, pairs, mutation_rows, versions, organisms,
                          summary)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"report: {args.report} ({time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
