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
    result.hits.append(_hit(name, "protein", "blaTEM-1", start=40000, end=40620, coverage=72.0,
                            resolution="PARTIAL", method="PARTIALX", primary=False))
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
    rows = {(r["Gene"], r["Database"]): r for r in _table(load_workbook(path)["AMR_genes"])}
    assert rows["blaKPC-2", "ncbi"]["Confident call"] == "confident"
    assert rows["blaTEM-1", "ncbi"]["Confident call"] == \
        "check: partial: 72.4% of the reference gene"
    assert rows["KPC-2", "card"]["Confident call"] == "-"                    # redundant: the KPC locus is judged once


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


# ---- AMRFinderPlus's curated cut-offs (HYDRA-WIN PATCH 5) ----------------------
def _protein(gene, identity, rule_identity, closest=""):
    hit = _hit("g", "protein", gene, start=1, end=1050, identity=identity, method="BLASTX")
    hit.rule_identity, hit.closest = rule_identity, closest
    return hit


def test_an_amrfinderplus_hit_is_held_to_its_familys_curated_cutoff():
    # NCBI curates cfr at 85%: an 87% cfr is a cfr, and AMRFinderPlus reports it.
    assert calls.judge([_protein("cfr", 87.0, 85.0)]).confident


def test_an_amrfinderplus_hit_below_its_familys_cutoff_is_not_confident():
    # Only reachable when someone overrides the protein identity upstream.
    verdict = calls.judge([_protein("aac(3)-IIa", 95.0, 98.0)])
    assert not verdict.confident
    assert verdict.reason == ("95% identity, below the 98% NCBI requires for this gene "
                              "family: a related gene, not necessarily this one")


def test_other_databases_keep_the_fixed_90_percent_bar():
    assert not calls.judge([_hit("g", "resfinder", "cfr_1", start=1, end=1050,
                                 identity=87.0)]).confident


def test_the_rule_text_names_the_curated_cutoffs():
    assert "curated" in calls.RULE_TEXT and "90%" in calls.RULE_TEXT


def test_the_gene_sheet_shows_the_closest_allele_of_a_family_call(tmp_path):
    result = _result("g1")
    result.hits.append(_protein("blaCTX-M", 99.7, 90.0, closest="blaCTX-M-15"))
    path = excel.write_genome_workbook(result, tmp_path / "g1.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein"))
    rows = {r["Gene"]: r for r in _table(load_workbook(path)["AMR_genes"])}
    assert rows["blaCTX-M"]["Closest allele (when named by family)"] == "blaCTX-M-15"
    assert rows["blaKPC-2"]["Closest allele (when named by family)"] in ("", None)


def test_the_settings_dialog_says_the_protein_search_uses_curated_cutoffs():
    from hydra_win import core

    text = core.explain_automatic()
    assert "curated cut-off" in text
    assert "(90% / 90%)" not in text


def test_the_run_info_says_the_protein_search_uses_curated_cutoffs(tmp_path):
    from hydra_amr.config import Config
    from hydra_amr.db.manager import DatabaseStore
    from hydra_win import core

    store = DatabaseStore(tmp_path / "db")
    info = core._run_info(store, [], [], Config(db_dir=store.root), core.Settings())
    assert "protein: NCBI's curated identity cut-off for each gene family" in info.thresholds


def test_the_summary_names_a_family_call_with_its_closest_allele(tmp_path):
    result = _result("g1")
    result.hits.append(_protein("blaCTX-M", 99.7, 90.0, closest="blaCTX-M-15"))
    path = excel.write_genome_workbook(result, tmp_path / "g1.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein"))
    summary = {r[0]: r[1] for r in load_workbook(path)["Summary"].iter_rows(values_only=True)
               if r[0]}
    assert "blaCTX-M (closest blaCTX-M-15)" in summary["AMR genes (names)"]
    # One matrix column per family, whatever allele each genome is closest to.
    columns, _ = excel.matrix_data([result], (excel.AMR,))
    assert ("BETA-LACTAM", "blaCTX-M") in columns


# ---- genes split by inserted sequence ---------------------------------------
def test_a_gene_split_by_an_insertion_is_not_confident():
    # Both pieces of a blaZ interrupted by ~5.5 kb, joined into one "complete"
    # match: AMRFinderPlus reports only the larger piece, as a partial.
    hit = _hit("g", "ncbi", "blaZ", start=7691, end=14102, coverage=100.0)
    hit.coverage = "1-399,400-846/846"
    verdict = calls.judge([hit])
    assert not verdict.confident
    assert verdict.reason == ("interrupted: the match is split by 5566 bp of other sequence "
                              "(an insertion), so the gene may not be functional")


def test_a_protein_match_is_measured_in_codons():
    hit = _protein("blaZ", 100.0, 90.0)
    hit.start, hit.end, hit.coverage = 7691, 14102, "1-133,134-282/282"
    assert calls.judge([hit]).reason.startswith("interrupted: the match is split by 5566 bp")


def test_a_few_bases_of_indel_do_not_interrupt_a_gene():
    hit = _hit("g", "ncbi", "blaKPC-2", start=1000, end=1890)     # 882 bp gene + 9 bp
    hit.coverage = "1-882/882"
    assert calls.judge([hit]).confident


def test_another_database_cannot_confirm_a_gene_with_an_internal_stop():
    # A nucleotide match cannot see the stop: one nonsense mutation still reads
    # 99.7% identical, and AMRFinderPlus reports the blaTEM as INTERNAL_STOP.
    stopped = _protein("blaTEM", 99.3, 90.0, closest="blaTEM-1")
    stopped.method = stopped.resolution = "INTERNAL_STOP"
    verdict = calls.judge([stopped, _hit("g", "ncbi", "blaTEM-1", start=1, end=1050,
                                         identity=99.7, primary=False)])
    assert not verdict.confident
    assert verdict.reason == "internal stop codon: may not be functional"


# ---- counted only where AMRFinderPlus reports the gene ----------------------
# MEGARes and ARG-ANNOT also hold the chromosomal efflux pumps, regulators and
# housekeeping genes NCBI leaves out of AMRFinderPlus: 523 of them across 48
# benchmark genomes (docs/amrfinder_comparison.md), 54-60 "AMR genes" for an
# E. coli where AMRFinderPlus finds 3-10.
def _with_megares_only(name="g1", **kw):
    result = _result(name)
    result.hits.append(_hit(name, "megares", "ACRA", start=60000, end=61194, identity=99.7,
                            drug_class="EFFLUX", **kw))
    return result


def _summary(tmp_path, result):
    path = excel.write_genome_workbook(result, tmp_path / f"{result.sample}.xlsx",
                                       excel.RunInfo(app_version="test"),
                                       databases=("ncbi", "protein", "megares"))
    return path, {r[0]: r[1] for r in load_workbook(path)["Summary"].iter_rows(values_only=True)
                  if r[0]}


def test_a_gene_only_another_catalogue_reports_is_not_counted(tmp_path):
    _, summary = _summary(tmp_path, _with_megares_only())
    assert summary["AMR genes"] == 2
    assert "ACRA" not in summary["AMR genes (names)"]
    assert summary[excel.OTHER_TITLE] == 1
    assert summary[f"{excel.OTHER_TITLE} (names)"] == "ACRA (megares)"


def test_drug_classes_follow_only_the_counted_genes():
    assert "EFFLUX" not in excel.amr_classes(_with_megares_only())


def test_the_gene_sheet_says_why_a_gene_is_not_counted(tmp_path):
    path, _ = _summary(tmp_path, _with_megares_only())
    rows = {(r["Gene"], r["Database"]): r for r in _table(load_workbook(path)["AMR_genes"])}
    assert rows["ACRA", "megares"]["Confident call"] == \
        "not counted: AMRFinderPlus does not report this gene"


def test_a_weak_hit_only_another_catalogue_has_is_not_listed_to_check(tmp_path):
    _, summary = _summary(tmp_path, _with_megares_only(coverage=70.0, resolution="PARTIAL"))
    assert "ACRA" not in summary[f"{excel.TO_CHECK_TITLE} (names)"]
    assert summary[excel.OTHER_TITLE] == 0


def test_the_window_counts_only_what_amrfinderplus_reports():
    assert excel.headline(_with_megares_only())["amr"] == 2


def test_the_cumulative_summary_lists_other_catalogues_only(tmp_path):
    path = excel.write_cumulative_workbook([_with_megares_only("g1"), _result("g2")],
                                           tmp_path / "Cumulative_results.xlsx",
                                           excel.RunInfo(app_version="test"))
    rows = {r["Assembly"]: r for r in _table(load_workbook(path)["Summary"])}
    assert rows["g1"]["AMR genes (n)"] == 2
    assert rows["g1"][excel.OTHER_TITLE] == "ACRA (megares)"
    assert rows["g2"][excel.OTHER_TITLE] in ("", None)


def test_the_rule_text_says_only_amrfinderplus_genes_are_counted():
    assert "AMRFinderPlus protein search" in calls.RULE_TEXT
    assert "other catalogues only" in calls.RULE_TEXT


def test_the_settings_dialog_says_other_catalogues_alone_are_not_counted():
    from hydra_win import core

    assert "only other catalogues" in core.explain_automatic()


# ---- easy to read -------------------------------------------------------------
def test_the_verdict_sits_next_to_the_gene_name(tmp_path):
    path, _ = _summary(tmp_path, _with_megares_only())
    header = [c.value for c in load_workbook(path)["AMR_genes"][1]]
    assert header[header.index("Gene") + 1] == "Confident call"


def test_a_sheet_without_amr_hits_has_no_verdict_column(tmp_path):
    path, _ = _summary(tmp_path, _with_megares_only())
    for sheet in ("Virulence", "Plasmids", "Point_mutations"):
        header = [c.value for c in load_workbook(path)[sheet][1]]
        assert "Confident call" not in header, sheet


def test_a_reason_rounds_its_percentage():
    verdict = calls.judge([_hit("g", "ncbi", "sul1", start=1, end=530, coverage=63.7681,
                                resolution="PARTIAL")])
    assert verdict.reason == "partial: 63.8% of the reference gene"
