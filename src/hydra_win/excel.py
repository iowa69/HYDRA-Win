"""Excel workbooks: one per genome, plus the optional cumulative workbook.

Both are built from upstream :class:`hydra_amr.records.SampleResult` objects
with openpyxl only. Colours are written as explicit cell fills rather than
conditional formatting, so they look the same in Excel, LibreOffice and any
viewer, and the tests can check them.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from hydra_amr.records import Hit, SampleResult, TypingResult
from hydra_amr.typing.organisms import registry as organisms

# ---------------------------------------------------------------- categories
AMR = "AMR"
STRESS = "Stress"
MUTATION = "Point mutation"
VIRULENCE = "Virulence"
PLASMID = "Plasmid"
TYPING = "Typing"
OTHER = "Other"
CATEGORY_ORDER = (AMR, STRESS, MUTATION, VIRULENCE, PLASMID, TYPING, OTHER)

#: Per-genome sheet names, in workbook order.
GENOME_SHEETS = ("Summary", "AMR_genes", "Point_mutations", "Virulence", "Plasmids",
                 "Typing", "All_hits", "Pivot")
#: Cumulative workbook sheet names, in workbook order.
CUMULATIVE_SHEETS = ("Summary", "AMR_matrix", "Mutations_matrix", "Virulence_matrix",
                     "Plasmids_matrix", "Typing_matrix", "All_hits")

MUTATION_METHODS = ("POINTX", "POINTN", "POINTP", "POINTR", "DISRUPTX", "SUSCEPTIBLEX")


def category(hit: Hit) -> str:
    """The workbook category a hit belongs to."""
    if hit.resolution == "POINT" or hit.method in MUTATION_METHODS:
        return MUTATION
    etype = (hit.element_type or "").upper()
    if etype == "AMR":
        return AMR
    if etype == "STRESS":
        return STRESS
    if etype == "VIRULENCE":
        return VIRULENCE
    if etype == "PLASMID":
        return PLASMID
    if etype in ("SEROTYPE", "TYPING"):
        return TYPING
    return OTHER


def label(hit: Hit) -> str:
    """Gene name, or the mutation itself (``gyrA_S83L``, ``ompK35_G134AfsTer11``)."""
    detail = getattr(hit, "mutation", None)
    if category(hit) == MUTATION and detail is not None and detail.symbol:
        return detail.symbol
    if category(hit) == MUTATION and hit.note:
        first = hit.note.split()[0].rstrip(";,")
        if first.startswith(hit.gene) and first != hit.gene:
            return first
    return hit.gene


#: Which categories each raw sheet holds.
SHEET_CATEGORIES = {
    "AMR_genes": (AMR, STRESS),
    "Point_mutations": (MUTATION,),
    "Virulence": (VIRULENCE,),
    "Plasmids": (PLASMID,),
}

# --------------------------------------------------------------------- style
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")
SECTION_FONT = Font(bold=True, color="1F4E78")
REDUNDANT_FONT = Font(color="808080")
PARTIAL_FONT = Font(italic=True)
THIN = Side(style="thin", color="BFBFBF")
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

#: (lower bound of %identity, fill colour, legend label), best first.
IDENTITY_BANDS = (
    (99.95, "63BE7B", "100%"),
    (98.0, "A9D18E", "98-99.9%"),
    (95.0, "FFEB84", "95-97.9%"),
    (90.0, "FFC266", "90-94.9%"),
    (0.0, "F8696B", "<90%"),
)
MUTATION_COLOUR = "8EA9DB"
CATEGORY_COLOURS = {
    AMR: "FCE4D6", STRESS: "FFF2CC", MUTATION: "DDEBF7", VIRULENCE: "E2EFDA",
    PLASMID: "EDE7F6", TYPING: "EDEDED", OTHER: "FFFFFF",
}


def identity_colour(identity: float | None) -> str | None:
    if identity is None:
        return None
    for floor, colour, _label in IDENTITY_BANDS:
        if identity >= floor:
            return colour
    return IDENTITY_BANDS[-1][1]


def _fill(colour: str | None) -> PatternFill | None:
    return PatternFill("solid", fgColor=colour) if colour else None


_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(value):
    """Excel refuses control characters; strip them from free text."""
    if isinstance(value, str):
        return _ILLEGAL.sub("", value)
    return value


# ---------------------------------------------------------------- hit tables
HIT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Contig", "sequence"),
    ("Start", "start"),
    ("End", "end"),
    ("Strand", "strand"),
    ("Gene", "gene"),
    ("Database", "database"),
    ("Identity (%)", "identity_pct"),
    ("Coverage (%)", "coverage_pct"),
    ("Drug class", "drug_class"),
    ("Subclass", "subclass"),
    ("Product", "product"),
    ("Accession", "accession"),
    ("Element type", "element_type"),
    ("Element subtype", "element_subtype"),
    ("Method", "method"),
    ("Resolution", "resolution"),
    ("Reference span", "coverage"),
    ("Gaps", "gaps"),
    ("Primary call", "primary"),
    ("Note", "note"),
)


def hit_values(hit: Hit) -> list:
    out = []
    for _title, attr in HIT_COLUMNS:
        value = getattr(hit, attr)
        if attr in ("identity_pct", "coverage_pct"):
            value = round(float(value), 2)
        elif attr == "primary":
            value = "yes" if value else "no (same locus as a better call)"
        out.append(_clean(value))
    return out


#: The leading columns of the Point_mutations sheet: what changed, where, and
#: what it means. The raw hit columns follow them.
MUTATION_COLUMNS: tuple[tuple[str, str, int], ...] = (   # title, MutationDetail field, width
    ("Mutation", "symbol", 24),
    ("Type of call", "type_label", 30),
    ("Gene", "gene", 9),
    ("Protein change", "protein_change", 15),
    ("Protein change (HGVS)", "protein_hgvs", 22),
    ("Nucleotide change", "nucleotide_change", 24),
    ("Isolate codon / base (read from the assembly)", "observed", 28),
    ("Reference codon / base (from a reference sequence)", "reference", 18),
    ("Reference codon (INFERRED by parsimony, no reference CDS)", "reference_inferred", 18),
    ("Base changed", "base_change", 24),
    ("Mutation position on contig", "location", 30),
    ("Gene position on contig", "gene_location", 30),
    ("Intact reference (disruptions)", "intact", 24),
    ("Resistance it is associated with", "resistance", 26),
    ("Kleborate-style call", "kleborate", 20),
    ("What it means", "description", 70),
    ("Basis of the base change", "nucleotide_basis", 50),
    ("Not resolved", "unresolved", 40),
)
#: Raw columns already shown among the leading ones.
_MUTATION_RAW_SKIP = ("gene",)
NO_REFERENCE_CDS = "n/a (no reference CDS)"

DISRUPTION_COLOUR = "F4B183"
CONTIG_END_COLOUR = "D9D9D9"
DIVERGENT_COLOUR = "C9B3E6"
INFERRED_FILL = "FFF2CC"


def mutation_detail(hit: Hit):
    return getattr(hit, "mutation", None)


def mutation_values(hit: Hit) -> list:
    """The leading Point_mutations values for one hit."""
    detail = mutation_detail(hit)
    out = []
    for _title, field_name, _width in MUTATION_COLUMNS:
        if field_name == "gene":
            out.append(hit.gene)
            continue
        if detail is None:
            out.append(label(hit) if field_name == "symbol" else
                       ("not described (no alignment detail)" if field_name == "unresolved"
                        else ""))
            continue
        value = getattr(detail, field_name, "")
        if field_name == "symbol":
            value = value or label(hit)
        if field_name == "reference" and not value and detail.call_type in (
                "substitution", "nonsense", "insertion", "deletion", "disruption_stop",
                "disruption_frameshift"):
            value = NO_REFERENCE_CDS
        out.append(_clean(value))
    return out


def type_colour(hit: Hit) -> str:
    detail = mutation_detail(hit)
    kind = detail.call_type if detail is not None else ""
    if kind == "contig_end":
        return CONTIG_END_COLOUR
    if kind == "divergent":
        return DIVERGENT_COLOUR
    if kind.startswith("disruption"):
        return DISRUPTION_COLOUR
    return MUTATION_COLOUR


def change_text(hit: Hit) -> str:
    """The change in a few characters, for matrix cells: S83I, G134AfsTer11, n.2059A>G."""
    detail = mutation_detail(hit)
    if detail is None:
        return label(hit)
    if detail.call_type == "contig_end":
        return "cut by contig end (not evidence)"
    if detail.call_type == "divergent":
        return f"divergent allele ({hit.identity_pct:.1f}% id)"
    if detail.protein_change:
        return detail.protein_change
    if detail.nucleotide_change:
        return detail.nucleotide_change
    return detail.symbol or label(hit)


def mutation_summary(hit: Hit) -> str:
    """One line: symbol, change, codon and place, resistance (All_hits, Summary sheets)."""
    detail = mutation_detail(hit)
    if detail is None:
        return label(hit) if category(hit) == MUTATION else ""
    parts = [detail.symbol or label(hit), detail.type_label]
    if detail.protein_hgvs:
        parts.append(detail.protein_hgvs)
    if detail.nucleotide_change:
        parts.append(detail.nucleotide_change)
    if detail.observed and detail.location:
        parts.append(f"{detail.observed} at {detail.location}")
    elif detail.location:
        parts.append(detail.location)
    if detail.resistance:
        parts.append(detail.resistance)
    return "; ".join(p for p in parts if p)


def mutation_lines(result: SampleResult) -> list[str]:
    """'gyrA_S83I (quinolone resistance)' for every primary mutation call, in order."""
    out = []
    for hit in sort_hits(h for h in result.hits if h.primary and category(h) == MUTATION):
        detail = mutation_detail(hit)
        what = detail.resistance if detail is not None else (hit.drug_class or "").lower()
        if detail is not None and detail.call_type == "contig_end":
            what = "gene cut by a contig end, not evidence of disruption"
        out.append(f"{label(hit)} ({what})" if what else label(hit))
    return out


def sort_hits(hits: Iterable[Hit]) -> list[Hit]:
    return sorted(hits, key=lambda h: (CATEGORY_ORDER.index(category(h)), h.sequence,
                                       min(h.start, h.end), h.gene, h.database))


def _write_header(ws: Worksheet, row: int, titles: Sequence[str], rotate: bool = False) -> None:
    for col, title in enumerate(titles, start=1):
        cell = ws.cell(row=row, column=col, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = CELL_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=not rotate,
                                   text_rotation=90 if rotate else 0)


def _autosize(ws: Worksheet, minimum: int = 6, maximum: int = 60,
              skip_rows: int = 0) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows(min_row=skip_rows + 1):
        for cell in row:
            if cell.value is None:
                continue
            text = str(cell.value)
            length = max((len(part) for part in text.split("\n")), default=0)
            widths[cell.column] = max(widths.get(cell.column, 0), length)
    for column, width in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = max(minimum, min(maximum, width + 2))


def write_hit_table(ws: Worksheet, hits: Sequence[Hit], *, leading: Sequence[tuple[str, object]] = (),
                    with_category: bool = False, mutations: bool = False,
                    with_mutation_summary: bool = False) -> int:
    """Write *hits* as a filterable table. Returns the number of data rows.

    ``mutations`` puts the Point_mutations columns (what changed, where, what it
    means) first; ``with_mutation_summary`` adds a one-line description of each
    mutation call after the category (All_hits).
    """
    raw = [(t, a) for t, a in HIT_COLUMNS if not (mutations and a in _MUTATION_RAW_SKIP)]
    lead_titles = [title for title, _ in leading]
    mutation_titles = [t for t, _f, _w in MUTATION_COLUMNS] if mutations else []
    titles = (lead_titles + (["Category"] if with_category else [])
              + (["Mutation: what changed"] if with_mutation_summary else [])
              + mutation_titles + [t for t, _ in raw])
    _write_header(ws, 1, titles)
    identity_col = titles.index("Identity (%)") + 1
    row = 1
    for item in hits:
        hit, lead_values = (item if isinstance(item, tuple) else (item, ()))
        row += 1
        values = (list(lead_values) + ([category(hit)] if with_category else [])
                  + ([_clean(mutation_summary(hit))] if with_mutation_summary else [])
                  + (mutation_values(hit) if mutations else [])
                  + [v for (t, a), v in zip(HIT_COLUMNS, hit_values(hit))
                     if not (mutations and a in _MUTATION_RAW_SKIP)])
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = CELL_BORDER
            if not hit.primary:
                cell.font = REDUNDANT_FONT
        if mutations:
            # Everything wraps and sits at the top: a row is as tall as its
            # longest explanation, and every cell starts on the same line.
            for col in range(1, len(values) + 1):
                ws.cell(row=row, column=col).alignment = Alignment(vertical="top")
            first = len(lead_titles) + (1 if with_category else 0) + 1
            for offset, (_title, field_name, _width) in enumerate(MUTATION_COLUMNS):
                cell = ws.cell(row=row, column=first + offset)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if field_name in ("symbol", "type_label"):
                    cell.fill = _fill(type_colour(hit))
                    cell.font = Font(bold=field_name == "symbol")
                elif field_name == "reference_inferred" and cell.value:
                    cell.fill = _fill(INFERRED_FILL)
        id_cell = ws.cell(row=row, column=identity_col)
        colour = MUTATION_COLOUR if category(hit) == MUTATION else identity_colour(hit.identity_pct)
        if colour:
            id_cell.fill = _fill(colour)
        if hit.resolution == "PARTIAL":
            ws.cell(row=row, column=identity_col + 1).font = PARTIAL_FONT
    ws.freeze_panes = "B2" if mutations else "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(titles))}{max(row, 1)}"
    _autosize(ws, maximum=50)
    if mutations:
        first = len(lead_titles) + (1 if with_category else 0) + 1
        for offset, (_title, _field, width) in enumerate(MUTATION_COLUMNS):
            ws.column_dimensions[get_column_letter(first + offset)].width = width
        for offset in range(len(MUTATION_COLUMNS)):
            ws.cell(row=1, column=first + offset).alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 64
        inferred = titles.index("Reference codon (INFERRED by parsimony, no reference CDS)") + 1
        ws.cell(row=1, column=inferred).comment = Comment(
            "AMRFinderPlus ships reference proteins, not coding sequences, for the "
            "point-mutation genes, so the reference codon cannot be read from a reference. "
            "This is the codon for the reference amino acid that differs least from the "
            "codon read in the isolate: an inference, not an observation.", "HYDRA-Win")
    if with_mutation_summary:
        col = titles.index("Mutation: what changed") + 1
        ws.column_dimensions[get_column_letter(col)].width = 60
    return row - 1


# ---------------------------------------------------------------- summaries
SCORE_LABELS = OrderedDict([
    ("resistance_score", "Resistance score (0-3)"),
    ("has_esbl", "ESBL"),
    ("has_carbapenemase", "Carbapenemase"),
    ("has_colistin_resistance", "Colistin resistance"),
    ("virulence_score", "Virulence score"),
    ("virulence_score_basis", "Virulence score basis"),
])

QC_LABELS = OrderedDict([
    ("contigs", "Contigs"), ("total_length", "Total length (bp)"), ("n50", "N50 (bp)"),
    ("n90", "N90 (bp)"), ("largest_contig", "Largest contig (bp)"),
    ("gc_percent", "GC (%)"), ("ambiguous_bases", "Ambiguous bases"),
])

COUNT_LABELS = OrderedDict([
    (AMR, "AMR genes"), (STRESS, "Stress genes (biocide/metal/heat)"),
    (MUTATION, "Point mutations / disruptions"), (VIRULENCE, "Virulence genes"),
    (PLASMID, "Plasmid replicons"), (TYPING, "Serotype loci"),
])


def _yes_no(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return value


def primary_genes(result: SampleResult, cat: str) -> list[str]:
    """Distinct gene names of the primary calls in one category, in order."""
    seen: "OrderedDict[str, None]" = OrderedDict()
    for hit in sort_hits(h for h in result.hits if h.primary and category(h) == cat):
        seen.setdefault(label(hit), None)
    return list(seen)


def category_counts(result: SampleResult) -> dict[str, int]:
    return {cat: len(primary_genes(result, cat)) for cat in COUNT_LABELS}


def amr_classes(result: SampleResult) -> list[str]:
    classes = sorted({h.drug_class for h in result.hits
                      if h.primary and category(h) == AMR and h.drug_class})
    return classes


def typing_label(scheme: str) -> str:
    return scheme.replace("__", " ").replace("_", " ")


def species_text(result: SampleResult) -> str:
    return result.species.name if result.species else "unknown"


def headline(result: SampleResult, missing: dict | None = None) -> dict:
    """The few numbers the window shows in a genome's row once it is done."""
    counts = category_counts(result)
    m = result.mlst
    st = m.sequence_type if m and m.sequence_type not in (None, "", "-") else "-"
    mlst = f"ST{st} ({m.scheme})" if st != "-" and m.scheme not in (None, "", "-") else (
        f"ST{st}" if st != "-" else "-")
    if st == "-" and missing and "pubmlst" in missing:
        mlst = "not typed (no PubMLST)"
    return {"species": species_text(result), "mlst": mlst,
            "typing": typing_headline(result) or organism_typing_absence(result),
            "amr": counts[AMR],
            "mutations": counts[MUTATION], "virulence": counts[VIRULENCE],
            "plasmids": counts[PLASMID]}


def organism_typing_absence(result: SampleResult) -> str:
    """Why there is no organism-specific call, in the width of a table cell.

    Three different things, and a reader must not have to guess which: no
    module covers this species, or one does and its data is not installed, or
    one ran and determined nothing.
    """
    chosen = organisms.select(result.species, result.mlst)
    if not chosen:
        return "no module for this species"
    for warning in result.warnings:
        if "typing skipped" in warning or "typing failed" in warning:
            return "data not installed"
    return "not determined"


@dataclass
class RunInfo:
    """Run-level facts stamped into every workbook."""

    app_version: str = ""
    upstream: str = ""
    date: str = ""
    databases: str = ""
    missing_databases: str = ""
    thresholds: str = ""
    notes: str = ""
    #: The user-adjustable settings actually used (label -> value), so every
    #: result can be traced to its thresholds.
    settings: dict = field(default_factory=dict)
    #: database -> what could not be done without it. Stated in every Summary
    #: sheet so a missing database is never read as a negative result.
    missing_analyses: dict = field(default_factory=dict)


NOT_TYPED = "not typed: PubMLST schemes not installed (not a negative result)"
MISSING_FILL = "F8CBAD"


def mlst_text(result: SampleResult, missing: dict | None = None) -> str:
    """The ST, or why there is none when PubMLST is not installed."""
    st = result.mlst.sequence_type
    if missing and "pubmlst" in missing and st in (None, "", "-"):
        return NOT_TYPED
    return st


def _kv(ws: Worksheet, row: int, key: str, value, *, colour: str | None = None) -> int:
    key_cell = ws.cell(row=row, column=1, value=key)
    key_cell.font = Font(bold=True)
    key_cell.border = CELL_BORDER
    key_cell.alignment = Alignment(vertical="top")
    value_cell = ws.cell(row=row, column=2, value=_clean(_yes_no(value)))
    value_cell.border = CELL_BORDER
    value_cell.alignment = Alignment(wrap_text=True, vertical="top")
    if colour:
        value_cell.fill = _fill(colour)
    return row + 1


def _section(ws: Worksheet, row: int, title: str) -> int:
    for col in (1, 2):
        cell = ws.cell(row=row, column=col, value=title if col == 1 else None)
        cell.fill = SECTION_FILL
        cell.font = SECTION_FONT
    return row + 1


def write_genome_summary(ws: Worksheet, result: SampleResult, info: RunInfo) -> None:
    ws.cell(row=1, column=1, value=f"HYDRA-Win report: {result.sample}").font = TITLE_FONT
    row = 3
    if info.missing_analyses:
        row = _section(ws, row, "Analyses NOT performed (database not installed)")
        for name, impact in info.missing_analyses.items():
            row = _kv(ws, row, name, impact, colour=MISSING_FILL)
        row += 1
    row = _section(ws, row, "Identification")
    row = _kv(ws, row, "Assembly", result.sample)
    row = _kv(ws, row, "Input file", "; ".join(Path(p).name for p in result.inputs))
    sp = result.species
    row = _kv(ws, row, "Species", sp.name)
    row = _kv(ws, row, "Species confidence", sp.confidence)
    row = _kv(ws, row, "Species evidence", sp.evidence or "-")
    row = _kv(ws, row, "Mutation catalogue (AMRFinderPlus organism)", sp.organism or "-")
    m = result.mlst
    row = _kv(ws, row, "MLST scheme", m.scheme)
    st = mlst_text(result, info.missing_analyses)
    row = _kv(ws, row, "MLST ST", st, colour=MISSING_FILL if st == NOT_TYPED else None)
    row = _kv(ws, row, "MLST profile", m.profile)
    row = _kv(ws, row, "MLST loci found",
              f"{m.loci_found}/{m.loci_total}" if m.loci_total else "-")
    if m.note:
        row = _kv(ws, row, "MLST note", m.note)

    row += 1
    row = _section(ws, row, "Scores")
    for key, title in SCORE_LABELS.items():
        if key in result.scores:
            row = _kv(ws, row, title, result.scores[key])

    row += 1
    row = _section(ws, row, "Counts (distinct genes, primary calls)")
    counts = category_counts(result)
    for cat, title in COUNT_LABELS.items():
        row = _kv(ws, row, title, counts[cat], colour=CATEGORY_COLOURS[cat])
    row = _kv(ws, row, "AMR drug classes", len(amr_classes(result)))
    row = _kv(ws, row, "All hits (incl. redundant database calls)", len(result.hits))

    row += 1
    row = _section(ws, row, "Detected (primary calls)")
    for cat in (AMR, STRESS, MUTATION, VIRULENCE, PLASMID):
        genes = mutation_lines(result) if cat == MUTATION else primary_genes(result, cat)
        row = _kv(ws, row, f"{COUNT_LABELS[cat]} (names)",
                  ("; " if cat == MUTATION else ", ").join(genes) if genes else "none")
    row = _kv(ws, row, "AMR drug classes (names)", ", ".join(amr_classes(result)) or "none")

    row += 1
    row = _section(ws, row, "Point mutations and gene disruptions: what changed")
    calls = sort_hits(h for h in result.hits if h.primary and category(h) == MUTATION)
    if not calls:
        row = _kv(ws, row, "Point mutations / disruptions", "none detected")
    for hit in calls:
        detail = mutation_detail(hit)
        text = (detail.description or mutation_summary(hit)) if detail is not None \
            else mutation_summary(hit)
        row = _kv(ws, row, label(hit), text, colour=type_colour(hit))

    row += 1
    row = _section(ws, row, "Typing (the evidence for every call is on the Typing sheet)")
    row = _kv(ws, row, "Organism typing",
              typing_headline(result) or organism_typing_absence(result))
    for typing in sorted(result.typing,
                         key=lambda t: (t.organism == "", t.organism.lower())):
        call = typing.call
        if typing.lineage not in ("-", "", None):
            call = f"{call} (lineage {typing.lineage})"
        # The organism is not repeated on every row: the species is at the top
        # of this sheet, and the Typing sheet has a column for it.
        row = _kv(ws, row, typing.heading, call,
                  colour=MISSING_FILL if is_undetermined(typing.call) else None)
    if not result.typing:
        row = _kv(ws, row, "Lineage / serotype typing",
                  "no scheme applies to this species")

    row += 1
    row = _section(ws, row, "Assembly QC")
    for key, title in QC_LABELS.items():
        if key in result.qc:
            row = _kv(ws, row, title, result.qc[key])
    row = _kv(ws, row, "Warnings", "; ".join(result.warnings) or "none")

    row += 1
    row = _section(ws, row, "Settings used")
    if info.settings:
        for title, value in info.settings.items():
            row = _kv(ws, row, title, value)
    else:
        row = _kv(ws, row, "Settings", "not recorded")

    row += 1
    row = _section(ws, row, "Run")
    for title, value in (("HYDRA-Win version", info.app_version),
                         ("Upstream Hydra", info.upstream), ("Date", info.date),
                         ("Databases (version)", info.databases),
                         ("Databases not available", info.missing_databases or "none"),
                         ("Thresholds", info.thresholds), ("Notes", info.notes)):
        row = _kv(ws, row, title, value)
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 100
    ws.freeze_panes = "A3"


TYPING_COLUMNS = ("Type", "Organism", "Scheme / database", "Call", "Lineage / detail",
                  "Loci found", "Evidence: what the call rests on",
                  "Caveats, limits and what could not be determined",
                  "Contig", "Start", "End", "Strand", "Identity (%)", "Coverage (%)")

#: Where the Typing sheet's header row sits. The two rows above it are the
#: title and the sentence explaining the evidence and caveats columns.
TYPING_HEADER_ROW = 4

#: A call that says the typing could not be made. Coloured, because a reader
#: skimming the sheet has to see the difference between "absent" and "not
#: looked for" without reading every caveat.
UNDETERMINED = ("not determined", "not typed", "not applicable", "-", "", None)

#: The organism heading used for the schemes that are not organism-specific:
#: Kleborate's lineage loci, the SCCmec cassette, the capsule loci.
ANY_ORGANISM = "any species (lineage and element schemes)"


def is_undetermined(call) -> bool:
    text = str(call or "").strip().lower()
    return text in UNDETERMINED or text.startswith("not determined")


def evidence_text(typing: TypingResult) -> str:
    """The ``alleles`` mapping, one ``key = value`` per line.

    One line per item rather than one run-on string: this is the part a
    microbiologist checks, and it holds residue lists, contig coordinates,
    identities and the database version. Excel wraps it, so it stays readable
    in a single cell.
    """
    return "\n".join(f"{key} = {value}" for key, value in typing.alleles.items())


def typing_headline(result: SampleResult) -> str:
    """One line naming what the organism-specific typing concluded."""
    return organisms.headline(result.typing)


def typing_rows(result: SampleResult) -> list[list]:
    rows: list[list] = []
    sp = result.species
    rows.append(["Species", "-", "Mash sketches / MLST scheme map", sp.name,
                 sp.confidence, "", sp.evidence or "no evidence recorded", "",
                 "", None, None, "", None, None])
    m = result.mlst
    rows.append(["MLST", "-", m.scheme, m.sequence_type,
                 m.source if m.scheme != "-" else "-",
                 f"{m.loci_found}/{m.loci_total}" if m.loci_total else "-",
                 f"profile = {m.profile}", m.note, "", None, None, "",
                 round(m.similarity, 2) if m.similarity else None, None])
    # Grouped by organism module, and inside a group kept in the order the
    # module reported them: that order is the module author's, and it reads
    # from the identifying call down to the accessory content.
    organism_first = sorted(result.typing,
                            key=lambda t: (t.organism == "", t.organism.lower()))
    for typing in organism_first:
        kind = "Organism typing" if typing.organism else "Lineage / element typing"
        rows.append([kind, typing.organism or ANY_ORGANISM, typing.heading, typing.call,
                     typing.lineage, typing.loci, evidence_text(typing), typing.note,
                     "", None, None, "", None, None])
    for hit in sort_hits(h for h in result.hits if category(h) == TYPING):
        rows.append(["Serotype locus", "-", hit.database, hit.gene, hit.product, "",
                     "", hit.note, hit.sequence, hit.start, hit.end, hit.strand,
                     round(hit.identity_pct, 2), round(hit.coverage_pct, 2)])
    return rows


def write_typing(ws: Worksheet, result: SampleResult) -> int:
    """The Typing sheet: every call, its evidence, and its caveats.

    One row per call. The evidence column is the module's own record of what it
    read the call from; the caveats column is what is provisional, what
    disagreed and what could not be determined. Both are shipped in full: a
    call a clinical microbiologist cannot check is a call they cannot use.
    """
    headline = typing_headline(result)
    ws.cell(row=1, column=1,
            value=f"Typing: {result.sample}"
                  f"{' - ' + headline if headline else ''}").font = TITLE_FONT
    ws.cell(row=2, column=1, value=(
        "One row per call. 'Evidence' is what the call was read from - alleles, "
        "residues, identity and coverage, contig coordinates, database version. "
        "'Caveats' is what is provisional, what disagreed, and what could not be "
        "determined. 'Not determined' is never a negative result: the caveat says "
        "why.")).alignment = Alignment(wrap_text=False, vertical="top")
    header_row = TYPING_HEADER_ROW
    _write_header(ws, header_row, TYPING_COLUMNS)
    rows = typing_rows(result)
    for r, values in enumerate(rows, start=header_row + 1):
        undetermined = is_undetermined(values[3])
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=_clean(value))
            cell.border = CELL_BORDER
            if c in (7, 8):
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            if undetermined and c == 4:
                cell.fill = _fill(MISSING_FILL)
    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = (f"A{header_row}:{get_column_letter(len(TYPING_COLUMNS))}"
                          f"{header_row + len(rows)}")
    _autosize(ws, maximum=60, skip_rows=header_row - 1)
    ws.column_dimensions["G"].width = 60
    ws.column_dimensions["H"].width = 70
    return len(rows)


# --------------------------------------------------------------------- pivot
@dataclass
class Locus:
    """One genomic locus and every database call made on it."""

    primary: Hit
    calls: list[Hit]

    @property
    def category(self) -> str:
        return category(self.primary)


def _overlap(a: Hit, b: Hit) -> bool:
    lo_a, hi_a = sorted((a.start, a.end))
    lo_b, hi_b = sorted((b.start, b.end))
    shared = min(hi_a, hi_b) - max(lo_a, lo_b) + 1
    return shared >= 0.6 * min(hi_a - lo_a + 1, hi_b - lo_b + 1)


def group_loci(hits: Sequence[Hit]) -> list[Locus]:
    """Attach each redundant call to the primary call on the same locus.

    Mirrors upstream's own rule (same contig and element type, >= 60% overlap),
    which is how it chose one primary call per locus in the first place.
    """
    loci = [Locus(primary=h, calls=[h]) for h in hits if h.primary]
    for hit in hits:
        if hit.primary:
            continue
        home = next((locus for locus in loci
                     if locus.category != MUTATION
                     and locus.primary.sequence == hit.sequence
                     and locus.primary.element_type == hit.element_type
                     and _overlap(locus.primary, hit)), None)
        if home is None:
            loci.append(Locus(primary=hit, calls=[hit]))
        else:
            home.calls.append(hit)
    loci.sort(key=lambda lc: (CATEGORY_ORDER.index(lc.category),
                              (lc.primary.drug_class or "~").upper(), lc.primary.gene.upper()))
    return loci


def _database_columns(hits: Sequence[Hit], preferred: Sequence[str]) -> list[str]:
    present = []
    for name in list(preferred) + sorted({h.database for h in hits}):
        if name not in present and any(h.database == name for h in hits):
            present.append(name)
    return present


def write_pivot(ws: Worksheet, result: SampleResult, databases: Sequence[str]) -> int:
    hits = [h for h in result.hits if category(h) != TYPING]
    loci = group_loci(hits)
    db_columns = _database_columns(hits, databases)

    ws.cell(row=1, column=1, value=f"{result.sample}: every locus x every database").font = TITLE_FONT
    m = result.mlst
    st = f"{m.scheme} ST{m.sequence_type}" if m.scheme != "-" else "no MLST call"
    scores = result.scores
    ws.cell(row=2, column=1, value=(
        f"Species: {result.species.name}   |   MLST: {st}   |   "
        f"Resistance score: {scores.get('resistance_score', '-')}   |   "
        f"Virulence score: {scores.get('virulence_score', '-')}"))
    legend_row = 3
    ws.cell(row=legend_row, column=1, value="Cell = % identity of that database's call at the "
                                            "locus (for a mutation: the change itself). "
                                            "Legend:").font = Font(italic=True)
    col = 4
    for _floor, colour, band in IDENTITY_BANDS:
        cell = ws.cell(row=legend_row, column=col, value=band)
        cell.fill = _fill(colour)
        cell.alignment = Alignment(horizontal="center")
        col += 1
    cell = ws.cell(row=legend_row, column=col, value="mutation")
    cell.fill = _fill(MUTATION_COLOUR)
    ws.cell(row=legend_row, column=col + 1, value="italic = partial coverage").font = PARTIAL_FONT

    header_row = 5
    titles = (["Category", "Drug class", "Gene"] + db_columns +
              ["Best identity (%)", "Coverage (%)", "Databases", "Location"])
    _write_header(ws, header_row, titles)
    for c in range(4, 4 + len(db_columns)):
        ws.cell(row=header_row, column=c).alignment = Alignment(
            horizontal="center", vertical="bottom", text_rotation=90)
    ws.row_dimensions[header_row].height = 80

    row = header_row
    for locus in loci:
        row += 1
        p = locus.primary
        cat = locus.category
        cat_fill = _fill(CATEGORY_COLOURS[cat])
        for c, value in enumerate((cat, p.drug_class or "-", label(p)), start=1):
            cell = ws.cell(row=row, column=c, value=_clean(value))
            cell.fill = cat_fill
            cell.border = CELL_BORDER
        best_by_db: dict[str, Hit] = {}
        for call in locus.calls:
            current = best_by_db.get(call.database)
            if current is None or call.identity_pct > current.identity_pct:
                best_by_db[call.database] = call
        for offset, name in enumerate(db_columns):
            cell = ws.cell(row=row, column=4 + offset)
            cell.border = CELL_BORDER
            call = best_by_db.get(name)
            if call is None:
                continue
            if cat == MUTATION:
                # A mutation row states the change, not the gene's identity.
                cell.value = _clean(change_text(call))
                cell.alignment = Alignment(horizontal="center", shrink_to_fit=True)
                cell.fill = _fill(type_colour(call))
                cell.comment = Comment(_clean(mutation_summary(call)), "HYDRA-Win")
            else:
                cell.value = round(call.identity_pct, 1)
                cell.number_format = "0.0"
                cell.alignment = Alignment(horizontal="center")
                cell.fill = _fill(identity_colour(call.identity_pct))
            if call.resolution == "PARTIAL":
                cell.font = PARTIAL_FONT
            if cat != MUTATION and call.gene != p.gene:
                cell.comment = Comment(f"{name}: {call.gene}", "HYDRA-Win")
        tail_col = 4 + len(db_columns)
        best = max(locus.calls, key=lambda h: h.identity_pct)
        strand = p.strand or "+"
        where = f"{p.sequence}:{min(p.start, p.end)}-{max(p.start, p.end)} ({strand})"
        detail = mutation_detail(p) if cat == MUTATION else None
        if detail is not None and detail.location:
            where = f"{detail.location}; gene {where}"
        values = (round(best.identity_pct, 2), round(p.coverage_pct, 2), len(best_by_db), where)
        for offset, value in enumerate(values):
            cell = ws.cell(row=row, column=tail_col + offset, value=_clean(value))
            cell.border = CELL_BORDER
        best_cell = ws.cell(row=row, column=tail_col)
        best_cell.fill = _fill(MUTATION_COLOUR if cat == MUTATION
                               else identity_colour(best.identity_pct))

    ws.freeze_panes = ws.cell(row=header_row + 1, column=4)
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(titles))}{max(row, header_row)}"
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 26
    for c in range(4, 4 + len(db_columns)):
        ws.column_dimensions[get_column_letter(c)].width = 7
    tail_col = 4 + len(db_columns)
    for offset, width in enumerate((10, 10, 10, 40)):
        ws.column_dimensions[get_column_letter(tail_col + offset)].width = width
    return len(loci)


# ------------------------------------------------------------ per-genome book
def write_genome_workbook(result: SampleResult, path: Path, info: RunInfo | None = None,
                          databases: Sequence[str] = ()) -> Path:
    info = info or RunInfo()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    write_genome_summary(ws, result, info)
    ordered = sort_hits(result.hits)
    for sheet, cats in SHEET_CATEGORIES.items():
        chosen = [h for h in ordered if category(h) in cats]
        if sheet == "Point_mutations":
            write_hit_table(wb.create_sheet(sheet), chosen, mutations=True)
        else:
            write_hit_table(wb.create_sheet(sheet), chosen, with_category=(sheet == "AMR_genes"))
    write_typing(wb.create_sheet("Typing"), result)
    write_hit_table(wb.create_sheet("All_hits"), ordered, with_category=True,
                    with_mutation_summary=True)
    write_pivot(wb.create_sheet("Pivot"), result, databases)
    wb.save(path)
    return path


# ------------------------------------------------------------ cumulative book
MATRICES = (
    ("AMR_matrix", (AMR, STRESS)),
    ("Mutations_matrix", (MUTATION,)),
    ("Virulence_matrix", (VIRULENCE,)),
    ("Plasmids_matrix", (PLASMID,)),
)


def cumulative_summary_rows(results: Sequence[SampleResult],
                            missing: dict | None = None) -> tuple[list[str], list[list]]:
    typing_schemes: list[str] = []
    for result in results:
        for typing in result.typing:
            if typing.scheme not in typing_schemes:
                typing_schemes.append(typing.scheme)
    titles = (["Assembly", "Species", "Species confidence", "MLST scheme", "ST",
               "MLST profile", "Organism typing (headline)"]
              + [_scheme_column(results, s) for s in typing_schemes]
              + list(SCORE_LABELS.values())
              + [COUNT_LABELS[c] + " (n)" for c in COUNT_LABELS] + ["AMR drug classes (n)"]
              + ["AMR genes", "Point mutations / disruptions", "Virulence genes",
                 "Plasmid replicons", "Contigs", "Total length (bp)", "N50 (bp)", "GC (%)",
                 "Warnings"])
    rows = []
    for result in results:
        typing = {t.scheme: t for t in result.typing}
        counts = category_counts(result)
        row = [result.sample, result.species.name, result.species.confidence,
               result.mlst.scheme, mlst_text(result, missing), result.mlst.profile,
               typing_headline(result) or "no organism module applies"]
        for scheme in typing_schemes:
            t = typing.get(scheme)
            row.append("" if t is None else (
                t.call if t.lineage in ("-", "", None) else f"{t.call} ({t.lineage})"))
        row += [_yes_no(result.scores.get(key, "")) for key in SCORE_LABELS]
        row += [counts[c] for c in COUNT_LABELS] + [len(amr_classes(result))]
        row += [", ".join(primary_genes(result, AMR) + primary_genes(result, STRESS)),
                "; ".join(mutation_lines(result)),
                ", ".join(primary_genes(result, VIRULENCE)),
                ", ".join(primary_genes(result, PLASMID))]
        row += [result.qc.get("contigs"), result.qc.get("total_length"), result.qc.get("n50"),
                result.qc.get("gc_percent"), "; ".join(result.warnings)]
        rows.append([_clean(v) for v in row])
    return titles, rows


def _scheme_column(results: Sequence[SampleResult], scheme: str) -> str:
    """A column title for one scheme, naming the organism when there is one.

    ``cps`` means a group B streptococcal serotype in one module and a
    meningococcal serogroup in another, and a batch may hold both, so the
    organism has to be part of the column title or the two merge.
    """
    for result in results:
        for typing in result.typing:
            if typing.scheme == scheme:
                if typing.organism:
                    return f"{typing.organism}: {typing.heading}"
                return typing.heading
    return typing_label(scheme)


def typing_matrix_data(results: Sequence[SampleResult]):
    """(columns, cells): columns are (organism, scheme); cells[sample][scheme]."""
    cells: dict[str, dict[str, TypingResult]] = {}
    columns: "OrderedDict[str, str]" = OrderedDict()
    for result in results:
        per = cells.setdefault(result.sample, {})
        for typing in result.typing:
            per[typing.scheme] = typing
            columns.setdefault(typing.scheme, typing.organism or ANY_ORGANISM)
    ordered = sorted(columns.items(),
                     key=lambda kv: (kv[1] == ANY_ORGANISM, kv[1].lower(), kv[0].lower()))
    return ordered, cells


def write_typing_matrix(ws: Worksheet, results: Sequence[SampleResult]) -> int:
    """Assemblies x typing schemes, the call in each cell.

    The one view that answers "is this an outbreak": twenty genomes beside each
    other, every scheme in a column, so a shared serotype, emm type or clonal
    complex is visible down the column. A call that could not be made is
    coloured rather than left blank, because a blank reads as a negative.
    """
    columns, cells = typing_matrix_data(results)
    lead = ["Assembly", "Species", "ST", "Organism typing (headline)"]
    first = len(lead) + 1
    for c, title in enumerate(lead, start=1):
        ws.cell(row=1, column=c,
                value="Typing matrix" if c == 1 else None).font = Font(bold=True)
        ws.cell(row=2, column=c, value=title)
    for index, (scheme, organism) in enumerate(columns):
        cell = ws.cell(row=1, column=first + index, value=organism)
        cell.alignment = Alignment(text_rotation=90, horizontal="center",
                                   vertical="bottom")
        cell.font = Font(bold=True, color="1F4E78")
        cell.fill = SECTION_FILL
    _write_header(ws, 2, lead + [_scheme_title(results, scheme)
                                 for scheme, _organism in columns])
    for index in range(len(columns)):
        ws.cell(row=2, column=first + index).alignment = Alignment(
            text_rotation=90, horizontal="center", vertical="bottom")
    ws.row_dimensions[1].height = 150
    ws.row_dimensions[2].height = 180
    row = 2
    for result in sorted(results, key=lambda r: r.sample):
        row += 1
        ws.cell(row=row, column=1, value=result.sample).border = CELL_BORDER
        ws.cell(row=row, column=2, value=result.species.name).border = CELL_BORDER
        ws.cell(row=row, column=3, value=result.mlst.sequence_type).border = CELL_BORDER
        ws.cell(row=row, column=4,
                value=typing_headline(result) or "-").border = CELL_BORDER
        for index, (scheme, _organism) in enumerate(columns):
            typing = cells.get(result.sample, {}).get(scheme)
            cell = ws.cell(row=row, column=first + index,
                           value="" if typing is None else _clean(typing.call))
            cell.border = CELL_BORDER
            if typing is None:
                continue
            if is_undetermined(typing.call):
                cell.fill = _fill(MISSING_FILL)
            if typing.note:
                cell.comment = Comment(typing.note[:2000], "HYDRA-Win")
    if not columns:
        ws.cell(row=4, column=1,
                value="No typing scheme applied to any assembly in this run.")
    ws.freeze_panes = ws.cell(row=3, column=first)
    _autosize(ws, maximum=28, skip_rows=2)
    for index in range(len(columns)):
        ws.column_dimensions[get_column_letter(first + index)].width = 22
    ws.column_dimensions["D"].width = 34
    return max(0, row - 2)


def _scheme_title(results: Sequence[SampleResult], scheme: str) -> str:
    for result in results:
        for typing in result.typing:
            if typing.scheme == scheme:
                return typing.heading
    return typing_label(scheme)


def matrix_data(results: Sequence[SampleResult], cats: Sequence[str]):
    """(columns, cells): columns are (drug class, gene); cells[sample][gene] = best hit."""
    cells: dict[str, dict[str, Hit]] = {}
    classes: dict[str, str] = {}
    for result in results:
        per = cells.setdefault(result.sample, {})
        for hit in result.hits:
            if not hit.primary or category(hit) not in cats:
                continue
            name = label(hit)
            classes.setdefault(name, hit.drug_class or "")
            if not classes[name] and hit.drug_class:
                classes[name] = hit.drug_class
            current = per.get(name)
            if current is None or hit.identity_pct > current.identity_pct:
                per[name] = hit
    columns = sorted(classes.items(), key=lambda kv: ((kv[1] or "~").upper(), kv[0].upper()))
    return [(cls, gene) for gene, cls in columns], cells


def write_matrix(ws: Worksheet, results: Sequence[SampleResult], cats: Sequence[str],
                 title: str) -> int:
    columns, cells = matrix_data(results, cats)
    lead = ["Assembly", "Species", "ST", "Genes (n)"]
    first = len(lead) + 1
    # Row 1: drug class above each gene; row 2: the header proper.
    for c, label in enumerate(lead, start=1):
        ws.cell(row=1, column=c, value=title if c == 1 else None).font = Font(bold=True)
    for offset, (cls, _gene) in enumerate(columns):
        cell = ws.cell(row=1, column=first + offset, value=cls or "-")
        cell.alignment = Alignment(text_rotation=90, horizontal="center", vertical="bottom")
        cell.font = Font(bold=True, color="1F4E78")
        cell.fill = SECTION_FILL
    _write_header(ws, 2, lead + [gene for _cls, gene in columns])
    for offset in range(len(columns)):
        ws.cell(row=2, column=first + offset).alignment = Alignment(
            text_rotation=90, horizontal="center", vertical="bottom")
    ws.row_dimensions[1].height = 110
    ws.row_dimensions[2].height = 110
    mutation = MUTATION in cats
    for r, result in enumerate(results, start=3):
        per = cells.get(result.sample, {})
        lead_values = [result.sample, result.species.name, result.mlst.sequence_type, len(per)]
        for c, value in enumerate(lead_values, start=1):
            cell = ws.cell(row=r, column=c, value=_clean(value))
            cell.border = CELL_BORDER
        for offset, (_cls, gene) in enumerate(columns):
            cell = ws.cell(row=r, column=first + offset)
            cell.border = CELL_BORDER
            hit = per.get(gene)
            if hit is None:
                continue
            cell.value = round(hit.identity_pct, 1)
            cell.number_format = "0.0"
            cell.alignment = Alignment(horizontal="center")
            cell.fill = _fill(MUTATION_COLOUR if mutation else identity_colour(hit.identity_pct))
            if hit.resolution == "PARTIAL":
                cell.font = PARTIAL_FONT
    last_col = max(len(lead), len(lead) + len(columns))
    last_row = 2 + len(results)
    ws.freeze_panes = ws.cell(row=3, column=first)
    ws.auto_filter.ref = f"A2:{get_column_letter(last_col)}{last_row}"
    ws.column_dimensions["A"].width = max(12, min(50, max((len(r.sample) for r in results),
                                                          default=10) + 2))
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 9
    for offset in range(len(columns)):
        ws.column_dimensions[get_column_letter(first + offset)].width = 5.5
    if not columns:
        ws.cell(row=3 + len(results), column=1,
                value="No calls in this category for any assembly.").font = Font(italic=True)
    return len(columns)


def mutation_matrix_data(results: Sequence[SampleResult]):
    """(columns, cells): one column per gene; cells[sample][gene] = that gene's calls."""
    cells: dict[str, dict[str, list[Hit]]] = {}
    classes: dict[str, str] = {}
    for result in results:
        per = cells.setdefault(result.sample, {})
        for hit in sort_hits(result.hits):
            if not hit.primary or category(hit) != MUTATION:
                continue
            gene = hit.gene
            detail = mutation_detail(hit)
            resistance = (detail.resistance if detail is not None and detail.resistance
                          else (hit.drug_class or "").lower())
            classes.setdefault(gene, resistance)
            per.setdefault(gene, []).append(hit)
    columns = sorted(classes.items(), key=lambda kv: ((kv[1] or "~").upper(), kv[0].upper()))
    return [(resistance, gene) for gene, resistance in columns], cells


def _residue_number(hit: Hit) -> int:
    """The position a change sits at, so one gene's changes read in order (S83L; D87N)."""
    match = re.search(r"-?\d+", change_text(hit))
    return int(match.group(0)) if match else 0


def write_mutation_matrix(ws: Worksheet, results: Sequence[SampleResult], title: str) -> int:
    """Assemblies x genes; each cell states the change(s) the assembly carries."""
    columns, cells = mutation_matrix_data(results)
    lead = ["Assembly", "Species", "ST", "Mutations (n)"]
    first = len(lead) + 1
    ws.cell(row=1, column=1, value=title).font = Font(bold=True)
    ws.cell(row=2, column=1, value="Above each gene: the resistance its calls are associated "
                                   "with. Cell: the change the assembly carries (empty = none "
                                   "detected). Blue: substitution, rRNA or promoter change; "
                                   "orange: gene disruption; grey: gene cut by a contig end (not "
                                   "evidence).").font = Font(italic=True, size=9)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)
    ws.cell(row=2, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    for offset, (resistance, _gene) in enumerate(columns):
        cell = ws.cell(row=2, column=first + offset, value=resistance or "-")
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="bottom")
        cell.font = Font(bold=True, color="1F4E78")
        cell.fill = SECTION_FILL
    _write_header(ws, 3, lead + [gene for _r, gene in columns])
    ws.row_dimensions[2].height = 60
    for r, result in enumerate(results, start=4):
        per = cells.get(result.sample, {})
        n = sum(len(v) for v in per.values())
        for c, value in enumerate([result.sample, result.species.name, result.mlst.sequence_type,
                                   n], start=1):
            cell = ws.cell(row=r, column=c, value=_clean(value))
            cell.border = CELL_BORDER
        for offset, (_r, gene) in enumerate(columns):
            cell = ws.cell(row=r, column=first + offset)
            cell.border = CELL_BORDER
            hits = per.get(gene)
            if not hits:
                continue
            hits = sorted(hits, key=_residue_number)
            cell.value = _clean("; ".join(change_text(h) for h in hits))
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            colours = {type_colour(h) for h in hits}
            cell.fill = _fill(DISRUPTION_COLOUR if DISRUPTION_COLOUR in colours
                              else next(iter(colours)))
            if all(type_colour(h) == CONTIG_END_COLOUR for h in hits):
                cell.font = Font(italic=True, color="595959")
            cell.comment = Comment(_clean("\n".join(mutation_summary(h) for h in hits)),
                                   "HYDRA-Win")
    last_col = max(len(lead), len(lead) + len(columns))
    ws.freeze_panes = ws.cell(row=4, column=first)
    ws.auto_filter.ref = f"A3:{get_column_letter(last_col)}{3 + len(results)}"
    ws.column_dimensions["A"].width = max(12, min(50, max((len(r.sample) for r in results),
                                                          default=10) + 2))
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 11
    for offset in range(len(columns)):
        ws.column_dimensions[get_column_letter(first + offset)].width = 17
    if not columns:
        ws.cell(row=4 + len(results), column=1,
                value="No point mutations or disruptions in any assembly.").font = Font(italic=True)
    return len(columns)


def write_cumulative_workbook(results: Sequence[SampleResult], path: Path,
                              info: RunInfo | None = None) -> Path:
    info = info or RunInfo()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    titles, rows = cumulative_summary_rows(results, info.missing_analyses)
    _write_header(ws, 1, titles)
    for r, values in enumerate(rows, start=2):
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = CELL_BORDER
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(titles))}{len(rows) + 1}"
    _autosize(ws, maximum=60)
    note_row = len(rows) + 3
    run_rows = [(f"NOT PERFORMED ({name} not installed)", impact)
                for name, impact in info.missing_analyses.items()]
    run_rows += [("HYDRA-Win", info.app_version), ("Upstream Hydra", info.upstream),
                 ("Date", info.date), ("Databases", info.databases)]
    run_rows += list(info.settings.items())
    run_rows += [("Thresholds", info.thresholds), ("Notes", info.notes)]
    for label, value in run_rows:
        ws.cell(row=note_row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=note_row, column=2, value=_clean(value))
        note_row += 1

    for sheet, cats in MATRICES:
        if MUTATION in cats:
            write_mutation_matrix(wb.create_sheet(sheet), results, sheet.replace("_", " "))
        else:
            write_matrix(wb.create_sheet(sheet), results, cats, sheet.replace("_", " "))

    write_typing_matrix(wb.create_sheet("Typing_matrix"), results)

    long_rows = []
    for result in results:
        for hit in sort_hits(result.hits):
            long_rows.append((hit, (result.sample,)))
    write_hit_table(wb.create_sheet("All_hits"), long_rows,
                    leading=(("Assembly", None),), with_category=True,
                    with_mutation_summary=True)
    wb.save(path)
    return path
