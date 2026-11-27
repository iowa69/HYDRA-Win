"""Build HYDRA-Win's clinical Mash sketch, and measure how well it names species.

Kleborate's sketch, which upstream Hydra uses, covers the Enterobacterales. This
adds the other species in tools/clinical_species.tsv, so that species
identification never depends on the MLST scheme alone for them.

For every species:

1. NCBI Datasets lists RefSeq assemblies. Only those that pass NCBI's own ANI
   taxonomy check ("OK"), and CheckM >= 95% complete / <= 5% contaminated
   where NCBI reports CheckM, are used: a mislabelled genome in the sketch would
   name every genome near it wrongly.
2. Candidates are the reference genome plus a seeded random sample of complete
   genomes, topped up with draft assemblies for a species with too few finished
   ones. Each is sketched as ``mash sketch`` does (k=21, s=1000, the
   parameters of Kleborate's sketch) and the most diverse subset is kept,
   greedily: each next genome is the one furthest from those already chosen,
   until a species has --per-species genomes or the next one would add less
   than --min-gap.
3. Draft assemblies (contig or scaffold level) that were never candidates are
   held out and named with the finished sketch plus Kleborate's, through
   hydra_win.mashlite, the code the Windows build runs. That is the validation:
   genomes like the ones a user brings, which the sketch has never seen.

Writes the sketch, a provenance table (every genome, why it was used, its NCBI
checks) and a validation report. Needs ``mash`` (Linux or macOS) and the
network; it is run by a maintainer, not by the release workflow.

    python tools/build_species_sketch.py --mash $(which mash) \\
        --kleborate ~/.hydra/db/sketch/species/species_mash_sketches.msh \\
        --work /tmp/sketch-build
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hydra_amr.typing.species import (MASH_SPECIES_DISTANCE,  # noqa: E402
                                      MASH_STRONG_DISTANCE, _clean_sketch_name)
from hydra_win import mashlite  # noqa: E402

API = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/{taxon}/dataset_report"
FTP = "https://ftp.ncbi.nlm.nih.gov/genomes/all"
KMER, SIZE = 21, 1000
#: A species keeps at least this many genomes for its sketch before any are
#: held out for validation.
MIN_SKETCH = 3
USER_AGENT = "hydra-win-sketch-builder"


@dataclass
class Genome:
    species: str
    accession: str
    assembly_name: str
    level: str
    strain: str
    category: str
    ani_status: str
    ani: float | None
    completeness: float | None
    contamination: float | None
    length: int
    role: str = ""
    path: Path | None = None
    sketch: Path | None = None
    note: str = ""

    @property
    def folder(self) -> str:
        return self.species.replace(" ", "_")

    @property
    def url(self) -> str:
        acc = self.accession
        asm = re.sub(r"[^A-Za-z0-9._-]", "_", self.assembly_name)
        digits = acc.split("_")[1].split(".")[0]
        return (f"{FTP}/{acc[:3]}/{digits[0:3]}/{digits[3:6]}/{digits[6:9]}/"
                f"{acc}_{asm}/{acc}_{asm}_genomic.fna.gz")


@dataclass
class SpeciesPlan:
    species: str
    candidates: list[Genome] = field(default_factory=list)
    holdouts: list[Genome] = field(default_factory=list)
    chosen: list[Genome] = field(default_factory=list)


# ------------------------------------------------------------------ NCBI
def _get(url: str, attempts: int = 4) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def reports(species: str, level: str, limit: int) -> list[dict]:
    """Up to *limit* RefSeq assembly reports for one assembly level."""
    out: list[dict] = []
    token = ""
    while len(out) < limit:
        query = {"filters.assembly_source": "refseq", "filters.exclude_atypical": "true",
                 "filters.assembly_version": "current", "filters.assembly_level": level,
                 "page_size": str(min(1000, limit))}
        if token:
            query["page_token"] = token
        url = API.format(taxon=urllib.parse.quote(species)) + "?" + urllib.parse.urlencode(query)
        data = json.loads(_get(url))
        out += data.get("reports", [])
        token = data.get("next_page_token", "")
        time.sleep(0.35)  # NCBI asks for at most 3 requests a second without a key
        if not token:
            break
    return out[:limit]


def genome_from(report: dict, species: str) -> Genome | None:
    """A report -> Genome, or None if it fails any check."""
    name = report.get("organism", {}).get("organism_name", "")
    if name != species and not name.startswith(species + " "):
        return None
    ani = report.get("average_nucleotide_identity", {})
    if ani.get("taxonomy_check_status") != "OK":
        return None
    checkm = report.get("checkm_info", {})
    completeness = checkm.get("completeness")
    contamination = checkm.get("contamination")
    if completeness is not None and completeness < 95:
        return None
    if contamination is not None and contamination > 5:
        return None
    info = report.get("assembly_info", {})
    strain = (report.get("organism", {}).get("infraspecific_names", {}) or {}).get("strain", "")
    return Genome(species=species, accession=report["accession"],
                  assembly_name=info.get("assembly_name", ""),
                  level=info.get("assembly_level", ""), strain=strain,
                  category=info.get("refseq_category", ""),
                  ani_status=ani.get("taxonomy_check_status", ""),
                  ani=(ani.get("best_ani_match") or {}).get("ani"),
                  completeness=completeness, contamination=contamination,
                  length=int(report.get("assembly_stats", {}).get("total_sequence_length", 0)))


def plan_species(species: str, candidates: int, holdouts: int) -> SpeciesPlan:
    rng = random.Random(species)  # the same choice on every run
    plan = SpeciesPlan(species)
    complete = [g for g in (genome_from(r, species) for r in
                            reports(species, "complete_genome", 1000)) if g]
    if len(complete) < candidates:
        complete += [g for g in (genome_from(r, species) for r in
                                 reports(species, "chromosome", 300)) if g]
    reference = [g for g in complete if g.category == "reference genome"]
    others = [g for g in complete if g.category != "reference genome"]
    rng.shuffle(others)
    finished = reference + others
    seen = {g.accession for g in finished}
    drafts = [g for g in (genome_from(r, species) for r in
                          reports(species, "contig", 300) + reports(species, "scaffold", 300))
              if g and g.accession not in seen]
    rng.shuffle(drafts)
    # Held-out genomes are drafts first (what a user brings), but never at the
    # cost of the sketch: a species with few genomes keeps MIN_SKETCH for it.
    keep_out = min(holdouts, max(0, len(finished) + len(drafts) - MIN_SKETCH))
    held = drafts[:keep_out]
    if len(held) < keep_out:
        held += finished[candidates:][:keep_out - len(held)]
    held_ids = {g.accession for g in held}
    # Finished genomes first; drafts fill in where too few are finished.
    pool = [g for g in finished if g.accession not in held_ids] + \
        [g for g in drafts if g.accession not in held_ids]
    plan.candidates = pool[:candidates]
    plan.holdouts = held
    for g in plan.candidates:
        g.role = "candidate"
    for g in plan.holdouts:
        g.role = "validation"
    return plan


def download(genome: Genome, genomes_dir: Path) -> Genome:
    target = genomes_dir / genome.folder / f"{genome.accession}.fna.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size == 0:
        try:
            data = _get(genome.url)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            # The folder name is the assembly name with NCBI's own character
            # rules; when the guess is wrong, read the directory instead.
            parent = genome.url.rsplit("/", 2)[0] + "/"
            listing = _get(parent).decode("utf-8", "replace")
            match = re.search(rf'href="({re.escape(genome.accession)}_[^"/]+)/"', listing)
            if not match:
                raise
            folder = match.group(1)
            data = _get(f"{parent}{folder}/{folder}_genomic.fna.gz")
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
    genome.path = target
    return genome


def sketch(mash: str, genome: Genome, genomes_dir: Path, sketch_dir: Path) -> Genome:
    """One genome -> one .msh, named Genus_species/<accession>.fna.gz as Kleborate's are."""
    out = sketch_dir / genome.folder / genome.accession
    out.parent.mkdir(parents=True, exist_ok=True)
    msh = out.with_suffix(out.suffix + ".msh")
    if not msh.exists():
        relative = genome.path.relative_to(genomes_dir).as_posix()
        subprocess.run([mash, "sketch", "-k", str(KMER), "-s", str(SIZE), "-o", str(out),
                        relative], cwd=genomes_dir, check=True, capture_output=True)
    genome.sketch = msh
    return genome


# ------------------------------------------------------------- selection
def hashes(genome: Genome):
    return mashlite.read_sketch(genome.sketch).hashes[0]


def distance(a, b) -> float:
    return mashlite.mash_distance(a, b, KMER, SIZE)[0]


def choose(plan: SpeciesPlan, per_species: int, min_gap: float) -> None:
    """Greedy max-min diversity, starting from the reference genome."""
    pool = [g for g in plan.candidates if g.sketch is not None]
    if not pool:
        return
    sk = {g.accession: hashes(g) for g in pool}
    chosen = [pool[0]]
    rest = pool[1:]
    while rest and len(chosen) < per_species:
        gaps = [(min(distance(sk[g.accession], sk[c.accession]) for c in chosen), g) for g in rest]
        gap, best = max(gaps, key=lambda item: item[0])
        if gap < min_gap:
            break
        best.note = f"d={gap:.4f} from the nearest genome already chosen"
        chosen.append(best)
        rest.remove(best)
    chosen[0].note = chosen[0].note or ("reference genome" if chosen[0].category else
                                        "first candidate")
    for g in chosen:
        g.role = "sketch"
    for g in rest:
        g.role = "candidate (not needed: within the chosen genomes' diversity)"
    plan.chosen = chosen


# ------------------------------------------------------------ validation
def name_genome(path: Path, sketches: list[Path]) -> tuple[str, float, str, float]:
    """(best name, distance, best name of another species, its distance)."""
    by_name: dict[str, float] = {}
    for sketch_path in sketches:
        for reference, d, _shared, _denom in mashlite.dist(sketch_path, path):
            label = _clean_sketch_name(reference)
            if label and d < by_name.get(label, 9.0):
                by_name[label] = d
    ranked = sorted(by_name.items(), key=lambda item: item[1])
    best, best_d = ranked[0] if ranked else ("", 1.0)
    other = next(((n, d) for n, d in ranked if n.lower() != best.lower()), ("", 1.0))
    return best, best_d, other[0], other[1]


def binomial(name: str) -> str:
    return " ".join(name.split()[:2]).lower()


def validate(plans: list[SpeciesPlan], sketches: list[Path]) -> list[dict]:
    rows = []
    jobs = [(plan.species, g) for plan in plans for g in plan.holdouts if g.path]
    with concurrent.futures.ProcessPoolExecutor() as pool:
        futures = {pool.submit(name_genome, g.path, sketches): (species, g)
                   for species, g in jobs}
        for future in concurrent.futures.as_completed(futures):
            species, g = futures[future]
            best, d, other, other_d = future.result()
            if d >= MASH_SPECIES_DISTANCE:
                outcome = "not named (falls back to MLST)"
            elif binomial(best) == binomial(species):
                outcome = "correct, strong" if d < MASH_STRONG_DISTANCE else "correct, good"
            else:
                outcome = "WRONG"
            rows.append({"species": species, "accession": g.accession, "level": g.level,
                         "named": best if d < MASH_SPECIES_DISTANCE else "", "distance": d,
                         "next_species": other, "next_distance": other_d,
                         "outcome": outcome})
    return sorted(rows, key=lambda r: (r["species"], r["accession"]))


def confusable(plans: list[SpeciesPlan]) -> list[tuple[str, str, float]]:
    """Pairs of species whose sketch genomes come within the species distance."""
    sk = {p.species: [hashes(g) for g in p.chosen] for p in plans if p.chosen}
    names = sorted(sk)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            nearest = min(distance(x, y) for x in sk[a] for y in sk[b])
            if nearest < 2 * MASH_SPECIES_DISTANCE:
                out.append((a, b, nearest))
    return sorted(out, key=lambda item: item[2])


def mash_agreement(mash: str, final: Path, genomes: list[Genome]) -> tuple[int, int]:
    """How many (reference, query) distances mashlite and real Mash agree on exactly."""
    agree = total = 0
    for g in genomes:
        proc = subprocess.run([mash, "dist", str(final), str(g.path)], check=True,
                              capture_output=True, text=True)
        real = {line.split("\t")[0]: float(line.split("\t")[2])
                for line in proc.stdout.splitlines() if line}
        for reference, d, _s, _n in mashlite.dist(final, g.path):
            total += 1
            agree += abs(real[reference] - float(f"{d:g}")) < 1e-9
    return agree, total


# ---------------------------------------------------------------- output
SOURCE_COLUMNS = ("species", "role", "accession", "strain", "assembly_level",
                  "refseq_category", "ani_taxonomy_check", "best_ani", "checkm_completeness",
                  "checkm_contamination", "length_bp", "note", "url")


def write_sources(path: Path, plans: list[SpeciesPlan], retrieved: str) -> None:
    lines = [f"# Genomes behind clinical_species.msh, from NCBI RefSeq, retrieved {retrieved}.",
             "# role 'sketch': in the sketch. role 'validation': held out to measure it.",
             "\t".join(SOURCE_COLUMNS)]
    for plan in plans:
        for g in plan.chosen + plan.holdouts:
            lines.append("\t".join(str(v if v is not None else "") for v in (
                g.species, g.role, g.accession, g.strain, g.level, g.category, g.ani_status,
                g.ani, g.completeness, g.contamination, g.length, g.note, g.url)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(path: Path, plans, rows, pairs, agreement, retrieved, kleborate,
                 min_gap: float, candidates: int) -> None:
    def count(outcome_prefix):
        return sum(1 for r in rows if r["outcome"].startswith(outcome_prefix))

    n = len(rows)
    lines = [
        "# Clinical species sketch: how well it names species",
        "",
        f"Built {retrieved} by `tools/build_species_sketch.py` from NCBI RefSeq. "
        f"{sum(len(p.chosen) for p in plans)} genomes of {sum(1 for p in plans if p.chosen)} "
        f"species are in the sketch (k={KMER}, s={SIZE}, the parameters of Kleborate's).",
        "",
        "**Validation set:** draft assemblies (contig or scaffold level) that passed NCBI's "
        "ANI taxonomy check and were never sketch candidates. Each was named with this sketch "
        f"plus Kleborate's (`{kleborate.name}`), through `hydra_win.mashlite`, the code the "
        "Windows build runs, with upstream Hydra's thresholds: a name needs a Mash distance "
        f"below {MASH_SPECIES_DISTANCE}, and is strong below {MASH_STRONG_DISTANCE}.",
        "",
        "| Outcome | Genomes | Share |",
        "|---|---|---|",
    ]
    for label in ("correct, strong", "correct, good", "not named", "WRONG"):
        k = count(label)
        lines.append(f"| {label} | {k} | {100 * k / n:.1f}% |" if n else f"| {label} | 0 | - |")
    lines += ["", f"mashlite and real Mash gave identical distances for {agreement[0]} of "
                  f"{agreement[1]} reference/query pairs checked.", ""]
    thin = [p for p in plans if len(p.chosen) < MIN_SKETCH]
    # Identical at this sketch's resolution: the same isolate assembled twice,
    # or a species so clonal that unrelated isolates are this close.
    same = [r for r in rows if r["distance"] < 0.0001]
    if thin or same:
        lines += ["## Limits of this validation", ""]
    for p in thin:
        usable = sum(1 for g in p.candidates if g.sketch is not None)
        if usable < candidates:
            why = (f"NCBI holds only {usable} genome(s) of it that pass its ANI taxonomy check, "
                   "so a genome of this species far from those falls back to MLST")
        else:
            why = (f"all {usable} candidates were within {min_gap} of the "
                   f"{'genome' if len(p.chosen) == 1 else 'genomes'} chosen")
        lines.append(f"* **{p.species}**: {len(p.chosen)} sketch genome(s); {why}.")
    if same:
        others = [r for r in rows if r["distance"] >= 0.0001]
        right = sum(1 for r in others if r["outcome"].startswith("correct"))
        lines.append(
            f"* {len(same)} validation genomes are within d < 0.0001 of a sketch genome, "
            "identical at this sketch's resolution (the same isolate assembled twice, or a "
            "clonal species): they show that the sketch reads such genomes, not how far its "
            f"coverage reaches. Without them, {right} of {len(others)} were named correctly "
            f"and {sum(1 for r in others if r['outcome'] == 'WRONG')} wrongly. They are: "
            + ", ".join(f"{r['species']} {r['accession']}" for r in same) + ".")
    if thin or same:
        lines.append("")
    if pairs:
        lines += ["## Species whose sketch genomes are close",
                  "",
                  "The smallest distance between any two sketch genomes of the two species. "
                  f"Below {MASH_SPECIES_DISTANCE} a genome of one could be named as the other.",
                  "", "| Species | Species | Nearest distance |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {d:.4f} |" for a, b, d in pairs]
        lines.append("")
    lines += ["## Every validation genome", "",
              "| Species | Accession | Level | Named | Distance | Next species | Its distance "
              "| Outcome |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['species']} | {r['accession']} | {r['level']} | {r['named'] or '-'} "
                     f"| {r['distance']:.4f} | {r['next_species'] or '-'} "
                     f"| {r['next_distance']:.4f} | {r['outcome']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_species(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("species\t"):
            continue
        out.append(line.split("\t")[0].strip())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mash", required=True)
    parser.add_argument("--kleborate", type=Path, required=True,
                        help="Kleborate's species_mash_sketches.msh, for validation")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--species", type=Path, default=ROOT / "tools" / "clinical_species.tsv")
    parser.add_argument("--out", type=Path, default=ROOT / "src" / "hydra_win" / "data")
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs" / "species_sketch_validation.md")
    parser.add_argument("--candidates", type=int, default=16)
    parser.add_argument("--per-species", type=int, default=10)
    parser.add_argument("--min-gap", type=float, default=0.005)
    parser.add_argument("--holdouts", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)

    retrieved = time.strftime("%Y-%m-%d")
    genomes_dir = args.work / "genomes"
    sketch_dir = args.work / "sketches"
    species = read_species(args.species)
    plans_file = args.work / "plans.json"
    args.work.mkdir(parents=True, exist_ok=True)

    plans: list[SpeciesPlan] = []
    for name in species:
        plan = plan_species(name, args.candidates, args.holdouts)
        print(f"{name}: {len(plan.candidates)} candidates, {len(plan.holdouts)} held out",
              flush=True)
        plans.append(plan)
    plans_file.write_text(json.dumps({p.species: [g.accession for g in p.candidates + p.holdouts]
                                      for p in plans}, indent=1))

    everything = [g for p in plans for g in p.candidates + p.holdouts]
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures = {pool.submit(download, g, genomes_dir): g for g in everything}
        for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            g = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - one genome must not stop the build
                failed.append(f"{g.accession} ({g.species}): {exc}")
                g.path = None
            if done % 50 == 0:
                print(f"downloaded {done}/{len(everything)}", flush=True)
    for line in failed:
        print("download failed:", line, flush=True)

    for plan in plans:
        for g in plan.candidates:
            if g.path:
                sketch(args.mash, g, genomes_dir, sketch_dir)
        choose(plan, args.per_species, args.min_gap)
        print(f"{plan.species}: {len(plan.chosen)} genomes in the sketch", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    final_base = args.out / "clinical_species"
    final = final_base.with_suffix(".msh")
    final.unlink(missing_ok=True)
    chosen = [g.sketch for p in plans for g in p.chosen]
    subprocess.run([args.mash, "paste", str(final_base)] + [str(s) for s in chosen], check=True,
                   capture_output=True)
    mashlite._SKETCH_CACHE.clear()
    write_sources(args.out / "clinical_species_sources.tsv", plans, retrieved)

    rows = validate(plans, [args.kleborate, final])
    pairs = confusable(plans)
    sample = [g for p in plans for g in p.holdouts[:1] if g.path][:20]
    agreement = mash_agreement(args.mash, final, sample)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.report, plans, rows, pairs, agreement, retrieved, args.kleborate,
                 args.min_gap, args.candidates)
    wrong = [r for r in rows if r["outcome"] == "WRONG"]
    print(f"sketch: {final} ({final.stat().st_size // 1024} KB, {len(chosen)} genomes)")
    print(f"validation: {len(rows)} genomes, {len(wrong)} named wrongly; report {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
