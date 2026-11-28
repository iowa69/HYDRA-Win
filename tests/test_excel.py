"""Unit tests for the workbook builders, on synthetic results (no BLAST, no databases)."""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from hydra_amr.records import Hit, MlstCall, MutationDetail, SampleResult, SpeciesCall, TypingResult
from hydra_win import excel


def _hit(sample, db, gene, *, start, end, contig="contig_1", strand="+", identity=100.0,
         coverage=100.0, element_type="AMR", drug_class="BETA-LACTAM", primary=True,
         method="BLASTN", resolution="COMPLETE", note="", mutation=None):
    return Hit(sample=sample, database=db, gene=gene, element_type=element_type,
               drug_class=drug_class, sequence=contig, start=start, end=end, strand=strand,
               identity_pct=identity, coverage_pct=coverage, primary=primary, method=method,
               resolution=resolution, note=note, product=f"{gene} product", mutation=mutation)


def _result(name, kpc=True):
    hits = [
        _hit(name, "ncbi", "blaKPC-2", start=1000, end=1881, contig="plasmid_A"),
        _hit(name, "card", "KPC-2", start=1000, end=1881, contig="plasmid_A", identity=99.9,
             primary=False),
        _hit(name, "ncbi", "blaSHV-11", start=5000, end=5861, strand="-", identity=97.0),
        # The AMRFinderPlus protein search calls every gene NCBI's catalogue has, so
        # a real run always has it at these two loci (see hydra_win.calls).
        _hit(name, "protein", "blaKPC-2", start=1000, end=1881, contig="plasmid_A",
             method="EXACTX", primary=False),
        _hit(name, "protein", "blaSHV-11", start=5000, end=5861, strand="-", identity=97.0,
             method="BLASTX", primary=False),
        _hit(name, "protein", "gyrA", start=9000, end=11600, method="POINTX",
             resolution="POINT", drug_class="QUINOLONE", identity=99.8, note="gyrA_S83I (I)",
             mutation=MutationDetail(
                 symbol="gyrA_S83I", call_type="substitution",
                 type_label="Amino-acid substitution", protein_change="S83I",
                 protein_hgvs="p.Ser83Ile", nucleotide_change="c.248G>T (inferred)",
                 nucleotide_basis="inferred: no reference CDS", observed="ATC",
                 reference_inferred="AGC", base_change="G>T at codon position 2",
                 contig="contig_1", start=9248, end=9250, strand="+",
                 location="contig_1:9248-9250 (+)", gene_location="contig_1:9000-11600 (+)",
                 resistance="quinolone resistance", kleborate="GyrA:p.Ser83Ile",
                 description="gyrA codon 83 reads ATC (Ile)...")),
        _hit(name, "vfdb", "ybtS", start=20000, end=21300, element_type="VIRULENCE",
             drug_class="", identity=92.0),
        _hit(name, "plasmidfinder", "IncFIB(K)_1", start=10, end=570, contig="plasmid_A",
             element_type="PLASMID", drug_class=""),
        _hit(name, "ecoh", "wzx_O25", start=30000, end=31200, element_type="SEROTYPE",
             drug_class="", identity=88.0),
    ]
    if not kpc:
        hits = [h for h in hits if "KPC" not in h.gene]
    result = SampleResult(sample=name, inputs=[f"{name}.fasta"], hits=hits)
    result.species = SpeciesCall(name="Klebsiella pneumoniae", genus="Klebsiella",
                                 species="pneumoniae", confidence="strong",
                                 evidence="Mash", organism="Klebsiella_pneumoniae")
    result.mlst = MlstCall(scheme="klebsiella", sequence_type="11",
                           alleles={"gapA": "3", "infB": "3"}, loci_found=7, loci_total=7)
    result.typing = [TypingResult(scheme="klebsiella__ybst", call="15", lineage="ybt 9")]
    result.scores = {"resistance_score": 2 if kpc else 1, "has_carbapenemase": kpc}
    result.qc = {"contigs": 2, "total_length": 5_600_000, "n50": 5_300_000, "gc_percent": 57.1}
    return result


def _table(ws, header_row=1):
    rows = list(ws.iter_rows(min_row=header_row, values_only=True))
    header = rows[0]
    out = []
    for r in rows[1:]:
        if all(v is None for v in r):
            break  # the table ends at the first blank row
        out.append(dict(zip(header, r)))
    return out


def test_category_assignment():
    result = _result("g1")
    cats = {h.gene: excel.category(h) for h in result.hits}
    assert cats["blaKPC-2"] == excel.AMR
    assert cats["gyrA"] == excel.MUTATION
    assert cats["ybtS"] == excel.VIRULENCE
    assert cats["IncFIB(K)_1"] == excel.PLASMID
    assert cats["wzx_O25"] == excel.TYPING
    assert excel.label(next(h for h in result.hits if h.gene == "gyrA")) == "gyrA_S83I"


def test_genome_workbook(tmp_path):
    path = excel.write_genome_workbook(_result("g1"), tmp_path / "g1" / "g1.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein", "card"))
    wb = load_workbook(path)
    assert wb.sheetnames == list(excel.GENOME_SHEETS)

    amr = _table(wb["AMR_genes"])
    assert {r["Gene"] for r in amr} == {"blaKPC-2", "KPC-2", "blaSHV-11"}
    kpc = next(r for r in amr if r["Gene"] == "blaKPC-2")
    assert (kpc["Contig"], kpc["Start"], kpc["End"], kpc["Strand"]) == ("plasmid_A", 1000, 1881, "+")
    assert kpc["Database"] == "ncbi" and kpc["Identity (%)"] == 100.0
    assert kpc["Drug class"] == "BETA-LACTAM"
    shv = next(r for r in amr if r["Gene"] == "blaSHV-11")
    assert shv["Strand"] == "-"
    assert wb["AMR_genes"].freeze_panes == "A2"
    assert wb["AMR_genes"].auto_filter.ref.startswith("A1:")

    # identity shading on the raw sheet
    ws = wb["AMR_genes"]
    header = [c.value for c in ws[1]]
    col = header.index("Identity (%)") + 1
    colours = {ws.cell(row=r, column=header.index("Gene") + 1).value:
               ws.cell(row=r, column=col).fill.fgColor.rgb for r in range(2, ws.max_row + 1)}
    assert colours["blaKPC-2"].endswith(excel.IDENTITY_BANDS[0][1])
    assert colours["blaSHV-11"].endswith("FFEB84")  # 95-97.9%

    mutations = _table(wb["Point_mutations"])
    assert [r["Mutation"] for r in mutations] == ["gyrA_S83I"]
    m = mutations[0]
    header = [c.value for c in wb["Point_mutations"][1]]
    # What changed comes first, the raw hit columns after it.
    assert header[:4] == ["Mutation", "Type of call", "Gene", "Protein change"]
    assert header.index("Contig") > header.index("Not resolved")
    assert m["Protein change (HGVS)"] == "p.Ser83Ile"
    assert m["Isolate codon / base (read from the assembly)"] == "ATC"
    assert m["Reference codon (INFERRED by parsimony, no reference CDS)"] == "AGC"
    assert m["Reference codon / base (from a reference sequence)"] == excel.NO_REFERENCE_CDS
    assert m["Mutation position on contig"] == "contig_1:9248-9250 (+)"
    assert m["Resistance it is associated with"] == "quinolone resistance"
    assert m["Start"] == 9000                                  # the raw gene hit is kept
    all_rows = _table(wb["All_hits"])
    gyr = next(r for r in all_rows if r["Gene"] == "gyrA")
    assert "p.Ser83Ile" in gyr["Mutation: what changed"]
    assert "ATC at contig_1:9248-9250 (+)" in gyr["Mutation: what changed"]
    assert [r["Gene"] for r in _table(wb["Virulence"])] == ["ybtS"]
    assert [r["Gene"] for r in _table(wb["Plasmids"])] == ["IncFIB(K)_1"]

    typing = _table(wb["Typing"], header_row=excel.TYPING_HEADER_ROW)
    kinds = {r["Type"] for r in typing}
    assert {"Species", "MLST", "Lineage / element typing", "Serotype locus"} <= kinds
    assert next(r for r in typing if r["Type"] == "MLST")["Call"] == "11"
    ybst = next(r for r in typing if r["Scheme / database"] == "klebsiella ybst")
    assert ybst["Call"] == "15"
    assert ybst["Lineage / detail"] == "ybt 9"
    assert ybst["Organism"] == excel.ANY_ORGANISM

    all_hits = _table(wb["All_hits"])
    assert len(all_hits) == 9
    assert all(r["Contig"] and r["Start"] and r["End"] and r["Strand"] for r in all_hits)

    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Species"] == "Klebsiella pneumoniae"
    assert summary["MLST ST"] == "11"
    assert summary["Carbapenemase"] == "yes"
    assert summary["AMR genes"] == 2  # KPC and SHV; the CARD KPC call is redundant
    assert summary["Point mutations / disruptions"] == 1
    assert summary["Point mutations / disruptions (names)"] == "gyrA_S83I (quinolone resistance)"
    assert summary["gyrA_S83I"].startswith("gyrA codon 83 reads ATC")

    # Pivot: one row per locus, the redundant CARD call shown in its own column
    pivot = _table(wb["Pivot"], header_row=5)
    kpc_row = next(r for r in pivot if r["Gene"] == "blaKPC-2")
    assert kpc_row["ncbi"] == 100.0 and kpc_row["card"] == 99.9
    assert kpc_row["Databases"] == 3                    # ncbi, card and the protein search
    assert not any(r["Gene"] == "KPC-2" for r in pivot)
    gyr_row = next(r for r in pivot if r["Gene"] == "gyrA_S83I")
    assert gyr_row["protein"] == "S83I"                       # the change, not an identity
    assert gyr_row["Location"].startswith("contig_1:9248-9250 (+)")
    assert wb["Pivot"].freeze_panes == "D6"


def test_cumulative_workbook(tmp_path):
    results = [_result("g1"), _result("g2", kpc=False)]
    path = excel.write_cumulative_workbook(results, tmp_path / "Cumulative_results.xlsx",
                                           excel.RunInfo(app_version="test"))
    wb = load_workbook(path)
    assert wb.sheetnames == list(excel.CUMULATIVE_SHEETS)

    summary = _table(wb["Summary"])
    assert [r["Assembly"] for r in summary] == ["g1", "g2"]
    assert list(wb["Summary"][1])[0].value == "Assembly"

    matrix = _table(wb["AMR_matrix"], header_row=2)
    by_name = {r["Assembly"]: r for r in matrix}
    assert by_name["g1"]["blaKPC-2"] == 100.0
    assert by_name["g2"]["blaKPC-2"] is None
    assert by_name["g1"]["Genes (n)"] == 2 and by_name["g2"]["Genes (n)"] == 1
    assert "KPC-2" not in by_name["g1"]  # redundant calls stay out of matrices
    ws = wb["AMR_matrix"]
    header = [c.value for c in ws[2]]
    kpc_cell = ws.cell(row=3, column=header.index("blaKPC-2") + 1)
    assert kpc_cell.fill.fgColor.rgb.endswith(excel.IDENTITY_BANDS[0][1])
    assert ws.cell(row=1, column=header.index("blaKPC-2") + 1).value == "BETA-LACTAM"

    mutations = _table(wb["Mutations_matrix"], header_row=3)
    assert all(r["gyrA"] == "S83I" for r in mutations)        # the change, not 99.8
    assert wb["Mutations_matrix"].cell(row=2, column=5).value == "quinolone resistance"
    assert summary[0]["Point mutations / disruptions"] == "gyrA_S83I (quinolone resistance)"
    assert _table(wb["Virulence_matrix"], header_row=2)[0]["ybtS"] == 92.0
    assert _table(wb["Plasmids_matrix"], header_row=2)[1]["IncFIB(K)_1"] == 100.0

    long = _table(wb["All_hits"])
    assert len(long) == 15
    assert list(long[0])[0] == "Assembly"
    assert {r["Assembly"] for r in long} == {"g1", "g2"}


def test_a_contig_end_row_cannot_be_read_as_a_confirmed_loss_of_function(tmp_path):
    """The owner's decision: disclose it in the row, do not suppress the call.

    The row has to carry three things wherever the reader meets it - that the
    gene runs off the end of the contig, that this is not evidence of
    disruption, and that loss of function could not be assessed - and a single
    matrix or pivot cell is one of the places a reader meets it.
    """
    from hydra_amr.records import CONTIG_END_RESOLUTION, CONTIG_END_SUBTYPE

    detail = MutationDetail(
        symbol="mgrB (contig end)", call_type="contig_end",
        type_label=("Gene cut by a contig end: NOT evidence of disruption, "
                    "loss of function not assessed"),
        location="contig_7:1 (contig start)", gene_location="contig_7:1-140 (-)",
        intact="20 of 47 residues on this contig (43%)",
        resistance=("loss of function not established: the gene is cut by a contig "
                    "end, so the colistin resistance a confirmed loss of function "
                    "would mean cannot be reported"),
        description="The mgrB reading frame runs off the start of contig contig_7 ...",
        unresolved="gene cut by a contig end; the rest of the gene is not in this contig")
    at_edge = _hit("S1", "protein", "mgrB", start=1, end=140, contig="contig_7",
                   strand="-", drug_class="COLISTIN", method="DISRUPTX",
                   resolution=CONTIG_END_RESOLUTION, mutation=detail,
                   note=("mgrB runs off the end of contig contig_7, so the gene is cut by "
                         "the assembly: this is NOT evidence of disruption and loss of "
                         "function could not be assessed."))
    at_edge.element_subtype = CONTIG_END_SUBTYPE

    assert excel.is_contig_end(at_edge) is True
    assert excel.weak_font(at_edge) is excel.NOT_CONFIRMED_FONT
    # Struck through and greyed, so a single cell cannot be mistaken for a call.
    assert excel.NOT_CONFIRMED_FONT.strike is True
    assert excel.NOT_CONFIRMED_FONT.italic is True
    # A matrix cell says it in words as well, because colour is not evidence.
    text = excel.change_text(at_edge)
    assert "contig end" in text and "not assessed" in text
    assert excel.type_colour(at_edge) == excel.CONTIG_END_COLOUR

    # An ordinary partial hit is still only italic: the two must not look alike.
    partial = _hit("S1", "ncbi", "blaSHV-11", start=1, end=400, resolution="PARTIAL")
    assert excel.is_contig_end(partial) is False
    assert excel.weak_font(partial) is excel.PARTIAL_FONT
    assert excel.PARTIAL_FONT.strike in (None, False)

    # And it reaches the workbook, in columns no view drops.
    result = _result("S1")
    result.hits.append(at_edge)
    excel.write_genome_workbook(result, tmp_path / "S1.xlsx")
    wb = load_workbook(tmp_path / "S1.xlsx")
    rows = list(wb["All_hits"].iter_rows(values_only=True))
    header = list(rows[0])
    row = next(r for r in rows[1:]
               if r[header.index("Gene")] == "mgrB"
               and r[header.index("Database")] == "protein")
    assert row[header.index("Element subtype")] == CONTIG_END_SUBTYPE
    assert row[header.index("Resolution")] == CONTIG_END_RESOLUTION
    note = str(row[header.index("Note")])
    assert "NOT evidence of disruption" in note
    assert "loss of function could not be assessed" in note
    # The "what changed" column leads with it too, so the first cell a reader
    # reads already says the gene was cut rather than disrupted.
    changed = str(row[header.index("Mutation: what changed")])
    assert changed.startswith("mgrB (contig end)")
    assert "loss of function not assessed" in changed


@pytest.mark.parametrize("value,expected", [(100.0, "63BE7B"), (98.5, "A9D18E"),
                                            (96.0, "FFEB84"), (91.0, "FFC266"),
                                            (80.0, "F8696B")])
def test_identity_bands(value, expected):
    assert excel.identity_colour(value) == expected


def test_empty_result(tmp_path):
    result = SampleResult(sample="empty", inputs=["empty.fasta"])
    result.warnings.append("not analysed: empty file")
    wb = load_workbook(excel.write_genome_workbook(result, tmp_path / "e.xlsx"))
    assert wb.sheetnames == list(excel.GENOME_SHEETS)
    assert wb["All_hits"].max_row == 1
