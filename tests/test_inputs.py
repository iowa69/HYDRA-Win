"""Inputs, genome naming, settings and per-genome runs: the logic behind the window and --cli."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from hydra_amr.config import Thresholds
from hydra_amr.utils import HydraError
from hydra_win import cli, core, excel
from test_excel import _result


def touch(path: Path, text: str = ">c\nACGT\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------------------ naming
def test_duplicate_names_are_made_unique_and_marked(tmp_path):
    files = [touch(tmp_path / "a" / "EC958.fasta"), touch(tmp_path / "b" / "EC958.fna.gz"),
             touch(tmp_path / "c" / "ec958.fa"), touch(tmp_path / "d" / "Other.fas")]
    plan = core.plan_genomes(files)
    # Case-insensitive, because Windows folders are.
    assert [g.name for g in plan] == ["EC958", "EC958_2", "ec958_3", "Other"]
    assert [g.renamed for g in plan] == [False, True, True, False]
    assert plan[1].base == "EC958" and plan[1].path == files[1]
    assert list(core.name_genomes(files)) == ["EC958", "EC958_2", "ec958_3", "Other"]


def test_a_suffixed_name_is_never_reused(tmp_path):
    names = [g.name for g in core.plan_genomes(
        [tmp_path / "x.fasta", tmp_path / "x_2.fasta", tmp_path / "y" / "x.fasta"])]
    assert names == ["x", "x_2", "x_3"]


def test_names_of_the_run_files_stay_free(tmp_path):
    names = [g.name for g in core.plan_genomes(
        [tmp_path / "Cumulative_results.xlsx.fasta", tmp_path / "hydra-win.log.fa"])]
    assert names == ["Cumulative_results.xlsx_2", "hydra-win.log_2"]


# -------------------------------------------------------------------- FASTQ
def test_reads_are_rejected_with_one_counted_message(tmp_path):
    run = tmp_path / "run1"
    for name in ("s1_R1.fastq.gz", "s1_R2.fastq.gz", "s2_R1.fq", "s2_R2.fq.bz2"):
        touch(run / name, "@r\nACGT\n+\nIIII\n")
    touch(run / "s1.fasta")
    touch(run / "notes.txt")  # other files inside a folder are ignored quietly
    lone = touch(tmp_path / "single.FASTQ", "@r\nACGT\n+\nIIII\n")
    other = touch(tmp_path / "report.xlsx")
    intake = core.scan_inputs([run, lone, other, tmp_path / "missing.fasta"])
    assert [p.name for p in intake.assemblies] == ["s1.fasta"]
    assert len(intake.fastq) == 5
    assert [p.name for p in intake.other] == ["report.xlsx"]
    assert len(intake.missing) == 1
    message = intake.rejection_message()
    assert message.startswith("5 FASTQ read files were not added.")
    assert "assembled genomes (FASTA) only" in message
    assert "1 other file was not added" in message
    assert "1 path could not be found" in message


def test_one_fastq_file(tmp_path):
    intake = core.scan_inputs([touch(tmp_path / "a.fq.gz", "@r\nA\n+\nI\n")])
    assert not intake.assemblies
    assert intake.rejection_message().startswith("1 FASTQ read file was not added.")
    assert core.scan_inputs([touch(tmp_path / "g.fna")]).rejection_message() == ""


def test_headless_inputs_log_a_folder_of_reads_once(tmp_path):
    for i in range(30):
        touch(tmp_path / f"r{i}_R1.fastq.gz", "@r\nA\n+\nI\n")
    touch(tmp_path / "g.fasta")
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    log = logging.getLogger("hydra")
    log.addHandler(handler)
    try:
        found = core.expand_inputs([tmp_path])
    finally:
        log.removeHandler(handler)
    assert [p.name for p in found] == ["g.fasta"]
    fastq = [r.getMessage() for r in records if "FASTQ" in r.getMessage()]
    assert len(fastq) == 1 and "30 FASTQ" in fastq[0]


# ----------------------------------------------------------------- settings
@pytest.mark.parametrize("text, expected", [
    ("", None), ("Automatic", None), ("auto", None), (None, None), ("90", 90.0),
    ("92,5", 92.5), (" 85 % ", 85.0), ("0", 0.0), ("100", 100.0), (75, 75.0)])
def test_parse_percent(text, expected):
    assert core.parse_percent(text, "Minimum identity") == expected


@pytest.mark.parametrize("text", ["101", "-1", "abc", "nan", "9O", "1e3"])
def test_parse_percent_rejects(text):
    with pytest.raises(core.SettingsError, match="Minimum identity"):
        core.parse_percent(text, "Minimum identity")


@pytest.mark.parametrize("text, expected", [("", None), ("Automatic", None), ("4", 4)])
def test_parse_threads(text, expected):
    assert core.parse_threads(text) == expected


@pytest.mark.parametrize("text", ["0", "-2", "1.5", "lots", "100000"])
def test_parse_threads_rejects(text):
    with pytest.raises(core.SettingsError, match="Threads"):
        core.parse_threads(text)


def test_automatic_leaves_upstream_thresholds_alone():
    t = core.Settings().thresholds()
    assert not t.explicit
    assert vars(t) == vars(Thresholds())
    assert core.Settings().automatic


def test_values_are_set_like_upstream_flags():
    t = core.Settings(min_identity=90, min_coverage=50).thresholds()
    assert t.was_set("min_identity") and t.was_set("min_coverage")
    assert (t.min_identity, t.min_coverage) == (90, 50)
    assert (t.protein_min_identity, t.protein_min_coverage) == (90, 90)  # untouched
    only = core.Settings(min_coverage=70).thresholds()
    assert not only.was_set("min_identity") and only.was_set("min_coverage")


def test_settings_equal_upstream_cli_thresholds(tmp_path):
    """The same Thresholds upstream's own `hydra run --min-identity/--min-coverage` builds."""
    pytest.importorskip("pandas")  # upstream's CLI module imports its report writers
    from hydra_amr import cli as upstream

    for flags, settings in (([], core.Settings()),
                            (["--min-identity", "90"], core.Settings(min_identity=90)),
                            (["--min-identity", "75", "--min-coverage", "40"],
                             core.Settings(min_identity=75, min_coverage=40))):
        args = upstream.build_parser().parse_args(["run", "-a", "x.fasta", *flags])
        theirs = upstream._build_config(args, tmp_path).thresholds
        assert vars(theirs) == vars(settings.thresholds()), flags


def test_automatic_is_explained_in_upstream_terms():
    assert core.automatic_text("identity") == "80% (PlasmidFinder 95%, EcOH 90%)"
    assert core.automatic_text("coverage") == "60% (EcOH 80%)"
    text = core.explain_automatic()
    assert "80% identity over 60%" in text and "PlasmidFinder 95% identity" in text
    assert "EcOH 90% identity and 80% coverage" in text and "--min-identity" in text


def test_settings_describe_what_was_used():
    auto = core.Settings().describe()
    assert auto["Minimum identity (%)"] == "Automatic: 80% (PlasmidFinder 95%, EcOH 90%)"
    assert auto["Minimum coverage (%)"] == "Automatic: 60% (EcOH 80%)"
    assert auto["Threads"].endswith("(Automatic: all CPU cores)")
    assert auto["Equivalent upstream flags"] == "none (upstream defaults)"
    custom = core.Settings(min_identity=92.5, threads=4).describe()
    assert custom["Minimum identity (%)"].startswith("92.5% (set by user")
    assert custom["Minimum coverage (%)"].startswith("Automatic: 60%")
    assert custom["Threads"] == "4 (set by user)"
    assert custom["Equivalent upstream flags"] == "--min-identity 92.5"


def test_cli_exposes_the_settings():
    parser = cli.build_parser()
    args = parser.parse_args(["--cli", "g.fasta", "--out", "o", "--min-identity", "90",
                              "--min-coverage", "auto", "--threads", "2"])
    assert (args.min_identity, args.min_coverage, args.threads) == (90.0, None, 2)
    args = parser.parse_args(["--cli", "g.fasta", "--out", "o"])
    assert (args.min_identity, args.min_coverage, args.threads) == (None, None, None)
    for bad in (["--min-identity", "120"], ["--min-coverage", "x"], ["--threads", "0"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["--cli", "g.fasta", *bad])


def test_settings_are_written_into_both_workbooks(tmp_path):
    settings = core.Settings(min_identity=90, threads=3)
    info = excel.RunInfo(app_version="t", thresholds="x", settings=settings.describe())
    one, two = _result("A"), _result("B", kpc=False)
    book = excel.write_genome_workbook(one, tmp_path / "A.xlsx", info)
    ws = load_workbook(book)["Summary"]
    assert ws["A1"].value == "HYDRA-Win report: A"
    summary = {r[0]: r[1] for r in ws.iter_rows(values_only=True) if r[0]}
    assert summary["Minimum identity (%)"].startswith("90% (set by user")
    assert summary["Minimum coverage (%)"] == "Automatic: 60% (EcOH 80%)"
    assert summary["Threads"] == "3 (set by user)"
    assert summary["Equivalent upstream flags"] == "--min-identity 90"
    assert summary["HYDRA-Win version"] == "t"
    cumulative = excel.write_cumulative_workbook([one, two], tmp_path / "C.xlsx", info)
    notes = {r[0]: r[1] for r in load_workbook(cumulative)["Summary"].iter_rows(values_only=True)
             if r[0]}
    assert notes["HYDRA-Win"] == "t"
    assert notes["Minimum identity (%)"].startswith("90% (set by user")
    assert notes["Threads"] == "3 (set by user)"
    assert notes["Thresholds"] == "x"


def test_headline_for_the_table():
    head = excel.headline(_result("A"))
    assert head["species"] == "Klebsiella pneumoniae"
    assert head["mlst"] == "ST11 (klebsiella)"
    assert (head["amr"], head["mutations"], head["plasmids"]) == (2, 1, 1)


# ----------------------------------------------------- per-genome analysis
class _FakeStore:
    def __init__(self, root):
        self.root = root

    def is_installed(self, name):
        return True

    def installed(self):
        return {}


class _FakePipeline:
    runs: list = []

    def __init__(self, config, store, options):
        self.config = config

    def run(self, assemblies, readsets, workdir):
        assert len(assemblies) == 1 and not readsets
        (name, path), = assemblies.items()
        _FakePipeline.runs.append((name, self.config.thresholds.min_identity,
                                   self.config.threads))
        if "bad" in name:
            raise HydraError("cannot read this assembly")
        return [_result(name)]


def test_one_failed_genome_does_not_stop_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(core.runtime, "prepare", lambda: SimpleNamespace(
        db_root=tmp_path / "db", work_root=tmp_path / "work"))
    monkeypatch.setattr(core.mashlite, "install", lambda: None)
    monkeypatch.setattr(core, "ensure_databases", lambda **_: {})
    monkeypatch.setattr(core, "DatabaseStore", _FakeStore)
    monkeypatch.setattr(core.databases, "require_core", lambda store: None)
    monkeypatch.setattr(core, "Pipeline", _FakePipeline)
    _FakePipeline.runs = []
    files = [touch(tmp_path / "in" / "S1.fasta"), touch(tmp_path / "in" / "bad.fasta"),
             touch(tmp_path / "other" / "S1.fna"), touch(tmp_path / "in" / "reads.fastq")]
    events = []
    result = core.analyse(files, tmp_path / "out", cumulative=True,
                          settings=core.Settings(min_identity=88, threads=2),
                          on_genome=lambda e: events.append((e.genome.name, e.status)))
    assert [r[0] for r in _FakePipeline.runs] == ["S1", "bad", "S1_2"]
    assert {r[1:] for r in _FakePipeline.runs} == {(88, 2)}
    assert [e for e in events if e[1] != "running"] == [
        ("S1", "done"), ("bad", "failed"), ("S1_2", "done")]
    assert events[0] == ("S1", "running")
    assert result.failed == {"bad": "cannot read this assembly"}
    assert sorted(result.workbooks) == ["S1", "S1_2"]
    for name in ("S1", "S1_2"):
        assert (tmp_path / "out" / name / f"{name}.xlsx").exists()
    assert result.cumulative == tmp_path / "out" / "Cumulative_results.xlsx"
    notes = {r[0]: r[1] for r in load_workbook(result.cumulative)["Summary"].iter_rows(
        values_only=True) if r[0]}
    assert notes["Minimum identity (%)"].startswith("88% (set by user")
    assert not (tmp_path / "out" / "reads").exists()


def test_invalid_settings_stop_before_any_work(tmp_path):
    with pytest.raises(core.SettingsError):
        core.analyse([tmp_path / "x.fasta"], tmp_path / "out",
                     settings=core.Settings(min_identity=150))


# ------------------------------------------------- databases of v0.1.0 reused
def test_databases_from_an_earlier_home_are_reused(tmp_path):
    from hydra_amr.db.manager import DatabaseStore

    from hydra_win import databases

    old = DatabaseStore(tmp_path / "LocalAppData" / "Hydra-win" / "db")
    touch(old.root / "nucl" / "card" / "card.fasta")
    old.record("card", path="nucl/card", kind="nucl", version="4.0.1")
    touch(old.root / "mlst" / "schemes.tsv", "scheme\n")
    old.record("pubmlst", path="mlst", kind="mlst")
    new = DatabaseStore(tmp_path / "HYDRA-Win" / "db")
    new.record("ncbi", path="nucl/ncbi", kind="nucl")
    touch(new.root / "nucl" / "ncbi" / "ncbi.fasta")
    reused = databases.adopt(new, ["card", "pubmlst", "vfdb"],
                             [tmp_path / "nowhere", old.root, new.root])
    assert reused == ["card", "pubmlst"]
    fresh = DatabaseStore(new.root)
    assert fresh.is_installed("card") and fresh.is_installed("pubmlst")
    assert fresh.installed()["card"]["version"] == "4.0.1"
    assert (new.root / "nucl" / "card" / "card.fasta").exists()
    assert not fresh.is_installed("vfdb") and fresh.is_installed("ncbi")
    assert databases.adopt(fresh, ["card"], [old.root]) == []  # already there
