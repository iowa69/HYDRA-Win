#!/usr/bin/env python3
"""Check Hydra-win workbooks against upstream Hydra's JSON for the same genomes.

    compare_upstream.py HYDRA_JSON HYDRA_WIN_OUTDIR

HYDRA_JSON is ``hydra.json`` from ``hydra run --format json`` (same databases,
``--preset deep``). Exits non-zero on any difference: missing sheets, hits
without coordinates, or a call set that differs from upstream's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

GENOME_SHEETS = ("Summary", "AMR_genes", "Point_mutations", "Virulence", "Plasmids",
                 "Typing", "All_hits", "Pivot")
CUMULATIVE_SHEETS = ("Summary", "AMR_matrix", "Mutations_matrix", "Virulence_matrix",
                     "Plasmids_matrix", "All_hits")


def rows(ws, header_row=1):
    values = list(ws.iter_rows(min_row=header_row, values_only=True))
    header = list(values[0])
    return [dict(zip(header, row)) for row in values[1:] if any(v is not None for v in row)]


def key(sample, db, gene, contig, start, end, strand, identity):
    return (sample, db, gene, contig, int(start), int(end), strand, round(float(identity), 1))


def main(argv):
    upstream = json.loads(Path(argv[1]).read_text())
    outdir = Path(argv[2])
    problems = []
    for sample in upstream["samples"]:
        name = sample["sample"]
        book = outdir / name / f"{name}.xlsx"
        wb = load_workbook(book)
        missing = [s for s in GENOME_SHEETS if s not in wb.sheetnames]
        if missing:
            problems.append(f"{name}: missing sheets {missing}")
        hits = rows(wb["All_hits"])
        bad = [h for h in hits if not h["Contig"] or not h["Start"] or not h["End"]
               or h["Strand"] not in ("+", "-")]
        if bad:
            problems.append(f"{name}: {len(bad)} hits without contig/start/end/strand")
        mine = {key(name, h["Database"], h["Gene"], h["Contig"], h["Start"], h["End"],
                    h["Strand"], h["Identity (%)"]) for h in hits}
        theirs = {key(name, h["database"], h["gene"], h["sequence"], h["start"], h["end"],
                      h["strand"], h["identity_pct"]) for h in sample["hits"]}
        if mine != theirs:
            problems.append(f"{name}: {len(theirs - mine)} upstream hits missing, "
                            f"{len(mine - theirs)} extra; e.g. "
                            f"{sorted(theirs - mine)[:3]} / {sorted(mine - theirs)[:3]}")
        summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
        checks = {
            "Species": sample["species"]["name"],
            "MLST scheme": sample["mlst"]["scheme"],
            "MLST ST": sample["mlst"]["sequence_type"],
            "Resistance score (0-3)": sample["scores"].get("resistance_score"),
        }
        for label, expected in checks.items():
            if str(summary.get(label)) != str(expected):
                problems.append(f"{name}: {label} {summary.get(label)!r} != upstream {expected!r}")
        typing = {r["Scheme / database"]: r["Call"] for r in rows(wb["Typing"])}
        for t in sample["typing"]:
            label = t["scheme"].replace("__", " ").replace("_", " ")
            if str(typing.get(label)) != str(t["call"]):
                problems.append(f"{name}: typing {label} {typing.get(label)!r} != {t['call']!r}")
        point = rows(wb["Point_mutations"])
        print(f"{name}: {len(hits)} hits ({len(theirs)} upstream), species "
              f"{summary.get('Species')}, {summary.get('MLST scheme')} ST{summary.get('MLST ST')}, "
              f"{len(point)} point-mutation rows, {len(sample['typing'])} typing calls")
    cumulative = outdir / "Cumulative_results.xlsx"
    if cumulative.exists():
        wb = load_workbook(cumulative)
        missing = [s for s in CUMULATIVE_SHEETS if s not in wb.sheetnames]
        if missing:
            problems.append(f"cumulative: missing sheets {missing}")
        n = len(rows(wb["All_hits"]))
        expected = sum(len(s["hits"]) for s in upstream["samples"])
        if n != expected:
            problems.append(f"cumulative All_hits has {n} rows, upstream {expected}")
        print(f"cumulative: {n} hits in All_hits")
    for problem in problems:
        print("PROBLEM:", problem)
    print("MATCH" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
