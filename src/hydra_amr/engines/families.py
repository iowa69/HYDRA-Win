"""AMRFinderPlus's curated BLAST rules and gene-family names.

HYDRA-WIN PATCH 5 (see VENDORED.txt).

AMRFinderPlus does not hold every reference protein to one identity. Its family
table (``fam.tsv``) gives hundreds of gene families a curated cut-off: 98% for
the aac(3) and dfrA families, whose members differ by a few residues, 85% for
cfr, 84% for lsa(A). This module applies them the way AMRFinderPlus does
(``amr_report.cpp``, ``BlastAlignment::finish`` and ``good``):

* A hit starts at the family of its closest reference. It is checked against
  that family's rule -- the complete rule when it covers >= 90% of the
  reference, otherwise the partial rule, at >= 50% coverage -- and, failing
  it, against the parent family's, up the hierarchy. The first family whose
  rule it passes is the one it is reported as. A hit that passes none is not
  reported.
* A family with no curated rule (0.00 in the table) needs 90% identity.
* An identity set by the user replaces every curated one, as ``amrfinder -i``
  does.

Naming follows ``getGeneSymbol``: a hit identical to an allele over its whole
length keeps the allele's name (blaKPC-2); any other hit gets the symbol of
the family it was assigned to (blaKPC), because one residue can make another
allele with another phenotype. A hit assigned to a family NCBI marks
non-reportable (Salmonella's chromosomal aac(6')-Iy, for one) is not reported,
unless the reference itself is reportable and matched exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: AMRFinderPlus's defaults: ident_min_def, complete_coverage_min_def and
#: --coverage_min, as percentages.
DEFAULT_IDENTITY = 90.0
COMPLETE_COVERAGE = 90.0
PARTIAL_COVERAGE = 50.0
#: amr_report.cpp's frac_delta (1e-5 of a fraction), as a percentage.
_DELTA = 1e-3


@dataclass(frozen=True)
class Family:
    node: str
    parent: str
    symbol: str
    name: str
    #: Curated identities in percent; 0 means none, so the default applies.
    complete_identity: float
    partial_identity: float
    reportable: int


@dataclass(frozen=True)
class Assignment:
    """Which family a hit belongs to, and what it is called."""

    #: Node id of the family whose rule the hit passed ("" outside the hierarchy).
    family: str
    symbol: str
    #: The family's name, for a hit not named by its allele; None keeps the
    #: reference's own product name.
    name: str | None
    #: An exact match to an allele, so it keeps the allele's name.
    allele: bool
    partial: bool
    #: The identity the passing rule required, in percent.
    required_identity: float
    reportable: bool
    #: The family the hit started from, when it fell back to a parent: its
    #: symbol and the identity it required.
    start: str = ""
    start_required: float = 0.0

    def explain(self, closest: str) -> str:
        """Why the hit carries this name, for its note."""
        parts = []
        if self.start:
            parts.append(f"below the {self.start_required:g}% identity NCBI requires for "
                         f"{self.start}, so named by its parent family {self.symbol}")
        if closest:
            parts.append(f"named by its gene family because AMRFinderPlus names an allele only "
                         f"on an exact match; closest reference {closest}")
        return "; ".join(parts)


def _number(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


class FamilyRules:
    def __init__(self, families: dict[str, Family], identity: float | None = None,
                 partial_coverage: float = PARTIAL_COVERAGE,
                 complete_coverage: float = COMPLETE_COVERAGE):
        self.families = families
        #: Set when the user chose an identity, which replaces every curated one.
        self.identity = identity
        self.partial_coverage = partial_coverage
        self.complete_coverage = complete_coverage

    @classmethod
    def load(cls, prot_dir: Path, identity: float | None = None,
             partial_coverage: float = PARTIAL_COVERAGE,
             complete_coverage: float = COMPLETE_COVERAGE) -> FamilyRules | None:
        """Read ``fam.tsv``; None when the protein reference has none."""
        path = Path(prot_dir) / "fam.tsv"
        if not path.exists():
            return None
        families: dict[str, Family] = {}
        with open(path, encoding="utf-8") as handle:
            header = handle.readline().lstrip("#").rstrip("\n").split("\t")
            idx = {name: i for i, name in enumerate(header)}
            for line in handle:
                if not line.strip():
                    continue
                row = line.rstrip("\n").split("\t")
                row += [""] * (len(header) - len(row))

                def get(name: str) -> str:
                    return row[idx[name]].strip() if name in idx else ""

                symbol = get("gene_symbol")
                families[get("node_id")] = Family(
                    node=get("node_id"), parent=get("parent_node_id"),
                    symbol="" if symbol == "-" else symbol, name=get("family_name"),
                    complete_identity=_number(get("blastrule_complete_ident")),
                    partial_identity=_number(get("blastrule_partial_ident")),
                    reportable=int(_number(get("reportable"))))
        return cls(families, identity=identity, partial_coverage=partial_coverage,
                   complete_coverage=complete_coverage)

    def assign_fusion(self, parts: list[tuple[str, str, int]], identity: float, coverage: float,
                      *, exact: bool) -> Assignment | None:
        """A fusion protein, named by every part as AMRFinderPlus does it.

        *parts* are (gene, fam_id, reportable) in part order. Each part is
        assigned on its own (fusion2geneSymbols); the call is reportable when
        any part is, and holds the strictest identity any part required.
        """
        assigned = [self.assign(gene, fam_id, identity, coverage, exact=exact,
                                reference_reportable=reportable)
                    for gene, fam_id, reportable in parts]
        if not assigned or any(a is None for a in assigned):
            return None
        return Assignment(family=assigned[0].family,
                          symbol="/".join(a.symbol for a in assigned), name=None,
                          allele=all(a.allele for a in assigned), partial=assigned[0].partial,
                          required_identity=max(a.required_identity for a in assigned),
                          reportable=any(a.reportable for a in assigned))

    def _required(self, family: Family | None, partial: bool) -> float:
        if self.identity is not None:
            return self.identity
        if family is None:
            return DEFAULT_IDENTITY
        curated = family.partial_identity if partial else family.complete_identity
        return curated or DEFAULT_IDENTITY

    def assign(self, gene: str, fam_id: str, identity: float, coverage: float, *,
               exact: bool, reference_reportable: int = 2) -> Assignment | None:
        """The family a hit to reference (*gene*, *fam_id*) is reported as, or None."""
        partial = coverage < self.complete_coverage - _DELTA
        min_coverage = self.partial_coverage if partial else self.complete_coverage
        if coverage < min_coverage - _DELTA:
            return None
        allele = exact and gene != fam_id
        start = self.families.get(gene) or self.families.get(fam_id)
        if start is None:
            required = self._required(None, partial)
            if identity < required - _DELTA:
                return None
            return Assignment("", gene, None, allele, partial, required, True)
        family: Family | None = start
        seen: set[str] = set()
        while family is not None and family.node not in seen:
            seen.add(family.node)
            required = self._required(family, partial)
            if identity >= required - _DELTA:
                break
            family = self.families.get(family.parent)
        else:
            return None
        if family is None:
            return None
        reportable = family.reportable >= 1 or (allele and reference_reportable >= 2)
        symbol = gene if allele else (family.symbol or gene)
        fell_back = family is not start
        return Assignment(family=family.node, symbol=symbol,
                          name=None if allele else (family.name or None), allele=allele,
                          partial=partial, required_identity=required, reportable=reportable,
                          start=(start.symbol or start.node) if fell_back else "",
                          start_required=self._required(start, partial) if fell_back else 0.0)
