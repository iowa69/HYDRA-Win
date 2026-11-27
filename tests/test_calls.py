"""Confident calls: what a beginner may read as "this resistance gene is there".

Every hit upstream reports stays in the workbook. What changes is what is
counted and listed on the Summary and in the window: only a gene seen at
>= 90% identity over >= 90% of the reference, complete, by at least one
database at that locus.
"""

from __future__ import annotations

from openpyxl import load_workbook

from hydra_amr.records import MutationDetail
from hydra_win import calls, excel
from test_excel import _hit, _result, _table


def test_a_complete_high_identity_gene_is_confident():
    verdict = calls.judge([_hit("g", "ncbi", "blaKPC-2", start=1, end=882)])
    assert verdict.confident and verdict.reason == ""


def test_a_partial_gene_is_not_confident():
    verdict = calls.judge([_hit("g", "ncbi", "blaTEM-1", start=1, end=620, coverage=72.4,
                                resolution="PARTIAL")])
    assert not verdict.confident
    assert verdict.reason == "partial: 72.4% of the reference gene"


def test_a_low_identity_gene_is_not_confident():
    verdict = calls.judge([_hit("g", "argannot", "aac(3)-IIa", start=1, end=861,
                                identity=86.4)])
    assert not verdict.confident
    assert verdict.reason == "86.4% identity: a related gene, not necessarily this one"


def test_another_database_at_the_same_locus_can_confirm_it():
    # NCBI's reference can be longer than the gene other catalogues hold; a
    # complete ResFinder match at the same locus is the evidence that counts.
    verdict = calls.judge([
        _hit("g", "ncbi", "blaCTX-M-15", start=1, end=876, coverage=85.0, resolution="PARTIAL"),
        _hit("g", "resfinder", "blaCTX-M-15_1", start=1, end=876, primary=False)])
    assert verdict.confident
    assert verdict.evidence == "resfinder: 100% identity, 100% coverage"


def test_a_gene_cut_by_a_contig_end_is_never_confident():
    verdict = calls.judge([_hit("g", "ncbi", "blaOXA-48", start=1, end=500,
                                resolution="CONTIG_END")])
    assert not verdict.confident
    assert verdict.reason == "cut by a contig end: presence not established"


def test_an_internal_stop_is_not_a_confident_gene():
    verdict = calls.judge([_hit("g", "ncbi", "blaSHV-1", start=1, end=861,
                                resolution="INTERNAL_STOP")])
    assert not verdict.confident
    assert verdict.reason == "internal stop codon: may not be functional"


def _with_partial_tem(name="g1"):
    result = _result(name)
    result.hits.append(_hit(name, "ncbi", "blaTEM-1", start=40000, end=40620, coverage=72.4,
                            resolution="PARTIAL"))
    return result


def test_the_summary_counts_only_confident_genes(tmp_path):
    path = excel.write_genome_workbook(_with_partial_tem(), tmp_path / "g1.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein", "card"))
    summary = {r[0]: r[1] for r in load_workbook(path)["Summary"].iter_rows(values_only=True)
               if r[0]}
    assert summary["AMR genes"] == 2                       # KPC and SHV, not TEM
    assert summary["AMR genes (names)"] == "blaSHV-11, blaKPC-2"   # contig order
    assert summary[excel.TO_CHECK_TITLE] == 1
    assert summary[f"{excel.TO_CHECK_TITLE} (names)"] == \
        "blaTEM-1 (partial: 72.4% of the reference gene)"
    assert "90% identity" in summary["Confident call"]


def test_drug_classes_include_established_mutations(tmp_path):
    # gyrA S83I is quinolone resistance whether or not a qnr gene is present.
    result = _result("g1")
    assert "QUINOLONE" in excel.amr_classes(result)
    contig_end = _result("g2")
    for hit in contig_end.hits:
        if hit.gene == "gyrA":
            hit.resolution = "CONTIG_END"
            hit.mutation = MutationDetail(symbol="gyrA", call_type="contig_end")
    assert "QUINOLONE" not in excel.amr_classes(contig_end)


def test_the_hit_tables_say_which_calls_are_confident(tmp_path):
    path = excel.write_genome_workbook(_with_partial_tem(), tmp_path / "g1.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein", "card"))
    rows = {r["Gene"]: r for r in _table(load_workbook(path)["AMR_genes"])}
    assert rows["blaKPC-2"]["Confident call"] == "confident"
    assert rows["blaTEM-1"]["Confident call"] == "check: partial: 72.4% of the reference gene"
    assert rows["KPC-2"]["Confident call"] == "-"                    # redundant: the KPC locus is judged once


def test_the_window_counts_only_confident_genes():
    assert excel.headline(_with_partial_tem())["amr"] == 2


def test_the_cumulative_summary_lists_what_to_check(tmp_path):
    path = excel.write_cumulative_workbook([_with_partial_tem("g1"), _result("g2", kpc=False)],
                                           tmp_path / "Cumulative_results.xlsx",
                                           excel.RunInfo(app_version="test"))
    rows = {r["Assembly"]: r for r in _table(load_workbook(path)["Summary"])}
    assert rows["g1"]["AMR genes (n)"] == 2
    assert rows["g1"][excel.TO_CHECK_TITLE] == "blaTEM-1 (partial: 72.4% of the reference gene)"
    assert rows["g2"][excel.TO_CHECK_TITLE] in ("", None)


def test_the_settings_dialog_says_the_bar_is_fixed():
    from hydra_win import core

    text = core.explain_automatic()
    assert "confident" in text and "90%" in text
    assert "not a setting" in text
