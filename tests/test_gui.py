"""The window's own logic, on a real (withdrawn) Tk window. Skipped without a display."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydra_win import __version__, core

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    from hydra_win import gui

    log = logging.getLogger("hydra")
    handlers, propagate, level = list(log.handlers), log.propagate, log.level
    window = gui.App(root, check_db=False)
    window.quiet = True
    yield window
    root.destroy()
    log.handlers[:], log.propagate, log.level = handlers, propagate, level


def touch(path: Path, text: str = ">c\nACGT\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_branding(app):
    assert app.root.title() == f"HYDRA-Win {__version__}"


def test_fastq_is_refused_with_one_notice(app, tmp_path):
    for name in ("a_R1.fastq.gz", "a_R2.fastq.gz", "b_R1.fq.gz", "b_R2.fq.gz"):
        touch(tmp_path / "reads" / name, "@r\nA\n+\nI\n")
    touch(tmp_path / "reads" / "a.fasta")
    app.add_paths([tmp_path / "reads"])
    assert [p.name for p in app.files] == ["a.fasta"]
    assert app.notice_text.startswith("4 FASTQ read files were not added.")
    assert app.notice.winfo_manager() == "pack"
    assert [r["sample"] for r in app.table_snapshot()] == ["a"]
    app.dismiss_notice()
    assert not app.notice.winfo_manager()


def test_duplicate_names_are_visible(app, tmp_path):
    app.add_paths([touch(tmp_path / "run1" / "S.fasta"), touch(tmp_path / "run2" / "S.fasta")])
    rows = app.table_snapshot()
    assert [r["sample"] for r in rows] == ["S", "S_2"]
    assert "renamed" in rows[1]["tags"] and "renamed" not in rows[0]["tags"]
    assert "S.fasta → S_2" in app.rename_label.cget("text")
    assert str(app.run_button["state"]) == "normal"
    app.add_paths([tmp_path / "run1" / "S.fasta"])  # the same file twice is one genome
    assert len(app.files) == 2


def test_settings_dialog_validates_and_applies(app):
    dialog = app.open_settings()
    dialog.set("identity", "150")
    assert "between 0 and 100" in dialog.error.cget("text")
    assert dialog.ok() is False and app.settings_dialog is dialog
    dialog.set("identity", "95")
    dialog.set("threads", "2")
    assert dialog.ok() is True and app.settings_dialog is None
    assert app.settings == core.Settings(min_identity=95, threads=2)
    assert "≥ 95%" in app.settings_summary.cget("text")
    dialog = app.open_settings()
    dialog.reset()
    dialog.ok()
    assert app.settings == core.Settings()
    assert app.settings_summary.cget("text").startswith("Thresholds: Automatic")


def test_about_window(app):
    app.show_about()
    texts = [w.cget("text") for w in app.about_window.winfo_children() if isinstance(w, tk.Label)]
    assert "HYDRA-Win" in texts and "Giovanni Lorenzin · IOWA-BioTech" in texts
    assert any("github.com/iowa69/HYDRA-Win" in t for t in texts)
    app.about_window.destroy()


def test_databases_dialog_shows_each_database_and_why_it_is_missing(app, tmp_path,
                                                                     monkeypatch):
    from hydra_amr.db.manager import DatabaseStore

    from hydra_win import databases

    store = DatabaseStore(tmp_path / "db")
    (store.root / "prot" / "amrfinderplus").mkdir(parents=True)
    store.record("protein", kind="prot", path="prot/amrfinderplus", version="2026-05-15.1")
    databases.record_outcome(store, "pubmlst", "the proxy server requires authentication "
                                               "(HTTP 407)")
    monkeypatch.setattr(type(app), "database_status",
                        lambda self: databases.status(store))
    dialog = app.show_databases()
    assert len(dialog.rows) == len(databases.ALL)
    statuses = {r["name"]: dialog.status_text(r) for r in dialog.rows}
    assert statuses["protein"].startswith("Installed")
    assert statuses["pubmlst"] == "MISSING: the proxy server requires authentication (HTTP 407)"
    assert "PubMLST (no MLST)" in app.db_label.cget("text")
    assert "NO MLST" in dialog.detail.cget("text")
    assert str(dialog.retry_button["state"]) == "normal"
    dialog.close()
    assert app.db_dialog is None
