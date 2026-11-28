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

* For a call from the AMRFinderPlus protein search, the identity NCBI curates
  for that gene family (98% for the aac(3) and dfrA families, 85% for cfr),
  and 90% where it curates none: the rule AMRFinderPlus itself applies, read
  from the bundled family table (see hydra_amr.engines.families). For every
  other database, >= 90% identity, AMRFinderPlus's default.
* >= 90% coverage of the reference, and a complete gene. Below 90%
  AMRFinderPlus calls a hit PARTIAL, and so does upstream
  (``Thresholds.partial_coverage``).
* Not cut by a contig end, no internal stop codon, and not split by inserted
  sequence (a match spanning more than 60 bp beyond the reference it covers):
  in each case the gene's presence as a working gene is not established.

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

#: Where HYDRA-Win's AMRFinderPlus protein search files its gene calls, and the
#: methods of a gene call (point mutations and disruptions are not genes).
AMRFINDERPLUS = "protein"
GENE_METHODS = ("EXACTX", "BLASTX", "PARTIALX", "INTERNAL_STOP")
#: What the gene sheets say of a locus only other catalogues call.
NOT_COUNTED = "not counted: AMRFinderPlus does not report this gene"


def reported_by_amrfinderplus(hits: Sequence[Hit]) -> bool:
    """Whether the AMRFinderPlus protein search makes a gene call among *hits* (one locus).

    MEGARes and ARG-ANNOT also hold the chromosomal efflux pumps, regulators and
    housekeeping genes NCBI deliberately leaves out of AMRFinderPlus (acrA,
    cpxAR, mexQ...), and some sequences no other catalogue recognises. Counting
    them gave a typical E. coli 54-60 "AMR genes" where AMRFinderPlus finds
    3-10 (docs/amrfinder_comparison.md). So a gene is counted only where the
    protein search, which applies AMRFinderPlus's own rules, calls it too.
    """
    return any(h.database == AMRFINDERPLUS and h.method in GENE_METHODS for h in hits)


RULE_TEXT = (f"a gene counts as detected only if one database at its locus matches it at "
             f">= {CONFIDENT_IDENTITY:g}% identity over >= {CONFIDENT_COVERAGE:g}% of the "
             "reference gene, complete (not cut by a contig end, no internal stop codon, not "
             "split by inserted sequence). In "
             "the AMRFinderPlus protein search the identity is instead the curated cut-off "
             "NCBI sets for that gene family, where it sets one (98% for the aac(3) and dfrA "
             "families, 85% for cfr), as AMRFinderPlus itself applies it. A gene is counted "
             "only where the AMRFinderPlus protein search calls it too: a confident call "
             "that only other catalogues make (mostly chromosomal efflux pumps and "
             "regulators NCBI leaves out of AMRFinderPlus) is listed under 'other "
             "catalogues only', not counted. Every other hit is listed under 'to check' "
             "with the reason, and every hit stays on its sheet.")


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


#: A match spanning more of the contig than the reference it covers, by more
#: than this many bases, joins the pieces of a gene split by other sequence:
#: an insertion sequence or transposon, or an assembly gap. AMRFinderPlus
#: reports only the larger piece, as partial. A few bases of indel are not that.
INSERTION_MIN = 60


def inserted_bases(hit: Hit) -> int:
    """Bases of other sequence inside the match; 0 for an uninterrupted gene."""
    spans, _, _ = (getattr(hit, "coverage", "") or "").partition("/")
    covered = 0
    for part in spans.split(","):
        lo, _, hi = part.partition("-")
        try:
            covered += int(hi) - int(lo) + 1
        except ValueError:
            return 0
    if covered <= 0:
        return 0
    # Protein references are measured in residues, the contig in bases.
    per_unit = 3 if hit.database == "protein" else 1
    excess = (int(hit.end) - int(hit.start) + 1) - per_unit * covered
    return excess if excess > INSERTION_MIN else 0


def required_identity(hit: Hit) -> float:
    """The identity this hit must reach: its family's curated cut-off, else 90%."""
    curated = getattr(hit, "rule_identity", None)
    return float(curated) if curated is not None else CONFIDENT_IDENTITY


def _clears(hit: Hit) -> bool:
    return (not _contig_end(hit) and hit.resolution not in NOT_ESTABLISHED
            and hit.resolution != "PARTIAL" and not inserted_bases(hit)
            and float(hit.identity_pct) >= required_identity(hit)
            and float(hit.coverage_pct) >= CONFIDENT_COVERAGE)


def _why_not(hit: Hit) -> str:
    if _contig_end(hit):
        return NOT_ESTABLISHED["CONTIG_END"]
    if hit.resolution in NOT_ESTABLISHED:
        return NOT_ESTABLISHED[hit.resolution]
    if inserted_bases(hit):
        return (f"interrupted: the match is split by {inserted_bases(hit)} bp of other "
                "sequence (an insertion), so the gene may not be functional")
    if hit.resolution == "PARTIAL" or float(hit.coverage_pct) < CONFIDENT_COVERAGE:
        return f"partial: {float(hit.coverage_pct):g}% of the reference gene"
    if getattr(hit, "rule_identity", None) is not None:
        return (f"{float(hit.identity_pct):g}% identity, below the "
                f"{required_identity(hit):g}% NCBI requires for this gene family: a related "
                "gene, not necessarily this one")
    return (f"{float(hit.identity_pct):g}% identity: a related gene, not necessarily "
            "this one")


def judge(hits: Sequence[Hit]) -> Verdict:
    """Judge one locus from every call made on it; the first is the one shown."""
    if not hits:
        return Verdict(False, "no call")
    first = hits[0]
    if _clears(first):
        return Verdict(True)
    if _contig_end(first) or inserted_bases(first) or first.resolution == "INTERNAL_STOP":
        # The gene runs off the contig, or is split by other sequence; another
        # catalogue's shorter reference fitting inside one piece does not make
        # the gene whole. Nor can a nucleotide match see a premature stop codon
        # the protein search found: one nonsense mutation still reads 99.7%.
        return Verdict(False, _why_not(first))
    for other in hits[1:]:
        if _clears(other):
            return Verdict(True, evidence=(f"{other.database}: {float(other.identity_pct):g}% "
                                           f"identity, {float(other.coverage_pct):g}% coverage"))
    return Verdict(False, _why_not(first))
