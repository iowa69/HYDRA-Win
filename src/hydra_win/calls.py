"""Confident calls: the fixed bar a resistance gene must clear to be counted.

Upstream reports every hit above its detection thresholds (80% identity over
60% of the reference for most nucleotide databases), which is what an expert
screening for novel or partial genes wants. A reader who is not an expert
reads the Summary's "AMR genes: blaTEM-1" as "this isolate carries TEM-1",
and a 72%-covered or 86%-identical hit does not say that.

So the Summary, the window and the cumulative workbook count and list only
confident calls, and name everything else under "to check" with the reason.
Nothing is hidden: every hit is still in its sheet, now with a Call column.

The bar is fixed, not a setting:

* >= 90% identity. AMRFinderPlus's own minimum for a BLAST-based hit where it
  has no curated cut-off, and upstream Hydra's protein and point-mutation
  thresholds.
* >= 90% coverage of the reference, and a complete gene. Below 90%
  AMRFinderPlus calls a hit PARTIAL, and so does upstream
  (``Thresholds.partial_coverage``).
* Not cut by a contig end and no internal stop codon: either way the gene's
  presence as a working gene is not established.

The bar applies to the locus: one database clearing it at that locus is
enough, because catalogues hold references of different lengths for the same
gene (NCBI's can include a signal peptide another catalogue lacks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from hydra_amr.config import Thresholds
from hydra_amr.records import Hit

#: The confident-call bar (percent). See the module docstring for where each
#: number comes from.
CONFIDENT_IDENTITY = 90.0
CONFIDENT_COVERAGE = Thresholds().partial_coverage

#: Resolutions that never make a confident gene call, and why, in words.
NOT_ESTABLISHED = {
    "CONTIG_END": "cut by a contig end: presence not established",
    "INTERNAL_STOP": "internal stop codon: may not be functional",
}

RULE_TEXT = (f"a gene counts as detected only if one database at its locus matches it at "
             f">= {CONFIDENT_IDENTITY:g}% identity over >= {CONFIDENT_COVERAGE:g}% of the "
             "reference gene, complete (not cut by a contig end, no internal stop codon). "
             "Every other hit is listed under 'to check' with the reason, and every hit "
             "stays on its sheet.")


@dataclass(frozen=True)
class Verdict:
    confident: bool
    #: Why not, in a few words ("" when confident).
    reason: str = ""
    #: Which call cleared the bar, when it is not the first one judged.
    evidence: str = ""


def _contig_end(hit: Hit) -> bool:
    detail = getattr(hit, "mutation", None)
    return hit.resolution == "CONTIG_END" or (detail is not None
                                              and detail.call_type == "contig_end")


def _clears(hit: Hit) -> bool:
    return (not _contig_end(hit) and hit.resolution not in NOT_ESTABLISHED
            and hit.resolution != "PARTIAL"
            and float(hit.identity_pct) >= CONFIDENT_IDENTITY
            and float(hit.coverage_pct) >= CONFIDENT_COVERAGE)


def _why_not(hit: Hit) -> str:
    if _contig_end(hit):
        return NOT_ESTABLISHED["CONTIG_END"]
    if hit.resolution in NOT_ESTABLISHED:
        return NOT_ESTABLISHED[hit.resolution]
    if hit.resolution == "PARTIAL" or float(hit.coverage_pct) < CONFIDENT_COVERAGE:
        return f"partial: {float(hit.coverage_pct):g}% of the reference gene"
    return (f"{float(hit.identity_pct):g}% identity: a related gene, not necessarily "
            "this one")


def judge(hits: Sequence[Hit]) -> Verdict:
    """Judge one locus from every call made on it; the first is the one shown."""
    if not hits:
        return Verdict(False, "no call")
    first = hits[0]
    if _clears(first):
        return Verdict(True)
    if _contig_end(first):
        # The gene runs off the contig; another catalogue's shorter reference
        # fitting inside what remains does not make the gene whole.
        return Verdict(False, _why_not(first))
    for other in hits[1:]:
        if _clears(other):
            return Verdict(True, evidence=(f"{other.database}: {float(other.identity_pct):g}% "
                                           f"identity, {float(other.coverage_pct):g}% coverage"))
    return Verdict(False, _why_not(first))
