"""Database routes, import from another PC, and how failures are reported (no network)."""

from __future__ import annotations

import socket
import ssl
import urllib.error

import pytest
from openpyxl import load_workbook

from hydra_amr.db.manager import DatabaseStore
from hydra_amr.records import MlstCall, SampleResult
from hydra_amr.utils import HydraError
from hydra_win import databases, excel, netfetch


def test_twelve_bundled_two_downloaded():
    assert len(databases.BUNDLED) == 12
    assert set(databases.FIRST_LAUNCH) == {"pubmlst", "card"}
    for name in ("vfdb", "argannot", "megares", "ecoli_vf", "ecoh"):
        route = next(r for r in databases.ROUTES if r.name == name)
        assert route.route == "bundled" and "no licence" in route.licence
        assert "removal" in route.why
    assert set(databases.IMPACT) == set(databases.ALL)


def _source_store(root):
    """A database folder as another PC would have it: PubMLST and CARD installed."""
    store = DatabaseStore(root)
    (root / "mlst" / "pubmlst" / "klebsiella").mkdir(parents=True)
    (root / "mlst" / "pubmlst" / "klebsiella" / "gapA.tfa").write_text(">gapA_1\nACGT\n")
    (root / "nucl" / "card").mkdir(parents=True)
    (root / "nucl" / "card" / "sequences").write_text(">card~~~x\nACGT\n")
    store.record("pubmlst", kind="mlst", path="mlst", version="2026-11-01", schemes=1)
    store.record("card", kind="nucl", path="nucl/card", version="4.0.1", sequences=1)
    return store


def test_import_from_a_folder_copied_from_another_pc(tmp_path):
    other_pc = tmp_path / "USB stick" / "HYDRA-Win"
    _source_store(other_pc / "db")
    target = DatabaseStore(tmp_path / "this pc" / "db")
    databases.record_outcome(target, "pubmlst", "the server name could not be resolved")
    assert not target.is_installed("pubmlst")

    # The whole HYDRA-Win folder, its db folder, or the folder above both work.
    imported, message = databases.import_folder(target, other_pc)
    assert sorted(imported) == ["card", "pubmlst"]
    assert target.is_installed("pubmlst") and target.is_installed("card")
    assert (target.root / "mlst" / "pubmlst" / "klebsiella" / "gapA.tfa").exists()
    assert "imported" in message
    # A successful import clears the recorded failure.
    assert "pubmlst" not in databases.load_failures(target)
    rows = {r["name"]: r for r in databases.status(target)}
    assert rows["pubmlst"]["installed"] and rows["pubmlst"]["version"] == "2026-11-01"

    again, message = databases.import_folder(DatabaseStore(tmp_path / "third" / "db"),
                                             tmp_path / "USB stick")
    assert sorted(again) == ["card", "pubmlst"]


def test_import_refuses_a_folder_that_is_not_a_database(tmp_path):
    (tmp_path / "random").mkdir()
    imported, message = databases.import_folder(DatabaseStore(tmp_path / "db"),
                                                tmp_path / "random")
    assert imported == [] and "manifest.json" in message


@pytest.mark.parametrize("cause,expected", [
    (urllib.error.HTTPError("u", 407, "Proxy Authentication Required", None, None),
     "proxy server requires authentication"),
    (urllib.error.HTTPError("u", 503, "Service Unavailable", None, None),
     "HTTP 503 Service Unavailable"),
    (urllib.error.URLError(ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain")),
     "Windows certificate store"),
    (urllib.error.URLError(socket.timeout("timed out")), "timed out"),
    (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "could not be resolved"),
    (ConnectionResetError(10054, "reset"), "reset"),
])
def test_failures_are_reported_with_their_real_reason(cause, expected):
    try:
        try:
            raise cause
        except Exception as exc:
            raise HydraError(f"could not download https://pubmlst.org/x: {exc}") from exc
    except HydraError as wrapped:
        assert expected in netfetch.describe_failure(wrapped)


def test_install_records_why_a_database_failed(tmp_path, monkeypatch):
    store = DatabaseStore(tmp_path / "db")

    def unreachable(name, force=False):
        try:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        except urllib.error.URLError as exc:
            raise HydraError("could not download https://card.mcmaster.ca/latest/data") from exc

    monkeypatch.setattr(store, "download", unreachable)
    errors = databases.install(store, ["card"])
    assert "could not be resolved" in errors["card"]
    row = next(r for r in databases.status(store) if r["name"] == "card")
    assert not row["installed"] and "could not be resolved" in row["reason"]
    assert row["failed_at"] and "CARD not screened" in row["impact"]


def test_missing_databases_are_stated_not_mistaken_for_negatives(tmp_path):
    result = SampleResult(sample="g1", inputs=["g1.fasta"])
    result.mlst = MlstCall()                                  # no scheme, no ST
    missing = {"pubmlst": databases.IMPACT["pubmlst"], "card": databases.IMPACT["card"]}
    info = excel.RunInfo(app_version="test", missing_analyses=missing)
    wb = load_workbook(excel.write_genome_workbook(result, tmp_path / "g1.xlsx", info))
    cells = [(r[0], r[1]) for r in wb["Summary"].iter_rows(values_only=True) if r[0]]
    keys = [k for k, _v in cells]
    assert "Analyses NOT performed (database not installed)" in keys
    summary = dict(cells)
    assert summary["pubmlst"].startswith("NO MLST")
    assert summary["MLST ST"] == excel.NOT_TYPED
    assert "CARD not screened" in summary["card"]

    book = excel.write_cumulative_workbook([result, SampleResult(sample="g2")],
                                           tmp_path / "c.xlsx", info)
    ws = load_workbook(book)["Summary"]
    header = [c.value for c in ws[1]]
    assert ws.cell(row=2, column=header.index("ST") + 1).value == excel.NOT_TYPED
    labels = [c.value for c in ws["A"] if c.value]
    assert any(str(v).startswith("NOT PERFORMED (pubmlst") for v in labels)
    assert excel.headline(result, missing)["mlst"] == "not typed (no PubMLST)"
