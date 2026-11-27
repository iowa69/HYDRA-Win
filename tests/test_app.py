"""Which front end a command line opens: the window, or the headless CLI."""

from __future__ import annotations

import pytest

from hydra_win import app


@pytest.mark.parametrize("argv", [
    ["--cli", "x.fasta", "--out", "o"],
    ["--import-db", r"C:\db"],
    [r"--import-db=C:\db"],
    ["--db-status"],
    ["--db-status=status.json"],
    ["--db-status", "status.json"],
    ["--fetch-db"],
    ["--build-db", "dist/db"],
    ["--build-db=dist/db"],
    ["--version"],
    ["--help"],
    ["-h"],
])
def test_maintenance_switches_never_open_the_window(argv):
    # A windowed executable that opens its window for --import-db leaves the
    # user who typed it in cmd.exe with no output and nothing imported.
    assert app.is_headless(argv)


@pytest.mark.parametrize("argv", [
    [],
    [r"C:\genomes\EC958.fasta"],  # a file dropped on the .exe
    ["--gui-smoke", "--report", "r.json"],
])
def test_everything_else_opens_the_window(argv):
    assert not app.is_headless(argv)


def test_main_hands_import_db_to_the_cli(monkeypatch):
    seen = {}

    def fake_cli(argv):
        seen["argv"] = argv
        return 0

    def no_window(argv):
        raise AssertionError(f"the window was opened for {argv}")

    monkeypatch.setattr("hydra_win.cli.main", fake_cli)
    monkeypatch.setattr("hydra_win.gui.main", no_window)
    assert app.main([r"--import-db=C:\db"]) == 0
    assert seen["argv"] == [r"--import-db=C:\db"]


def test_import_db_help_names_only_what_is_downloaded():
    from hydra_win import cli, databases

    action = next(a for a in cli.build_parser()._actions if a.dest == "import_db")
    # PubMLST has shipped in the zip since 0.5.0; the help must not send a
    # user to another PC for something they already have.
    assert "PubMLST" not in action.help
    assert databases.FIRST_LAUNCH == ("card",)
    for word in ("CARD", "spa", "cap", "ShigEiFinder"):
        assert word in action.help
