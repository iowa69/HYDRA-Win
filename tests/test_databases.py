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


def test_thirteen_bundled_one_downloaded():
    assert len(databases.BUNDLED) == 13
    # Only CARD now: PubMLST's terms permit redistributing the pre-2025 data an
    # anonymous download returns, so the snapshot ships in the zip.
    assert set(databases.FIRST_LAUNCH) == {"card"}
    assert "pubmlst" in databases.BUNDLED
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


def test_downloads_fall_back_to_windows_and_remember_what_works(tmp_path, monkeypatch):
    calls = []

    def direct(url, dest, progress=None):
        calls.append("direct")
        try:
            raise urllib.error.URLError(socket.timeout("timed out"))
        except urllib.error.URLError as exc:
            raise HydraError(f"could not download {url}: {exc}") from exc

    def windows(url, dest):
        calls.append("windows")
        dest.write_text("data")
        return dest

    monkeypatch.setattr(netfetch, "WINDOWS", True)
    monkeypatch.setattr(netfetch, "_system_proxy", lambda url: None)
    monkeypatch.setattr(netfetch, "_via_windows", windows)
    monkeypatch.setattr(netfetch, "_route", {})
    monkeypatch.setattr(netfetch, "_dead", {})
    for i in range(3):
        netfetch.fetch_once(f"https://rest.example.org/f{i}", tmp_path / f"f{i}", _first=direct)
    # The direct route timed out once; the next files went straight to the one that worked.
    assert calls == ["direct", "windows", "windows", "windows"]


def test_an_unreachable_host_fails_fast_with_its_reason(tmp_path, monkeypatch):
    def direct(url, dest, progress=None):
        try:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        except urllib.error.URLError as exc:
            raise HydraError(f"could not download {url}: {exc}") from exc

    def windows(url, dest):
        raise HydraError("Windows downloader failed: The remote name could not be resolved")

    monkeypatch.setattr(netfetch, "WINDOWS", True)
    monkeypatch.setattr(netfetch, "_system_proxy", lambda url: None)
    monkeypatch.setattr(netfetch, "_via_windows", windows)
    monkeypatch.setattr(netfetch, "_route", {})
    monkeypatch.setattr(netfetch, "_dead", {})
    for i in range(netfetch.DEAD_AFTER):
        with pytest.raises(HydraError, match="could not be resolved"):
            netfetch.fetch_once(f"https://pubmlst.example/f{i}", tmp_path / "x", _first=direct)
    with pytest.raises(HydraError, match="gave up on pubmlst.example"):
        netfetch.fetch_once("https://pubmlst.example/last", tmp_path / "x", _first=direct)


def test_an_http_answer_is_not_retried_through_other_routes(tmp_path, monkeypatch):
    def direct(url, dest, progress=None):
        try:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        except urllib.error.HTTPError as exc:
            raise HydraError(f"could not download {url}: {exc}") from exc

    monkeypatch.setattr(netfetch, "WINDOWS", True)
    monkeypatch.setattr(netfetch, "_via_windows", lambda url, dest: pytest.fail("not tried"))
    monkeypatch.setattr(netfetch, "_route", {})
    monkeypatch.setattr(netfetch, "_dead", {})
    with pytest.raises(HydraError, match="HTTP 404"):
        netfetch.fetch_once("https://x.example/f", tmp_path / "f", _first=direct)


def test_a_version_the_source_never_stated_is_said_in_words():
    # abricate's copies of ARG-ANNOT, MEGARes, E. coli VF and EcOH carry no
    # version file, so upstream records "unknown". A workbook must say what is
    # known instead: the pinned abricate commit and the retrieval date.
    text = databases.version_text("argannot", {"version": "unknown",
                                               "installed": "2026-08-04 00:30:41"})
    assert "unknown" not in text
    assert "not stated by the source" in text
    assert databases.ABRICATE_COMMIT[:7] in text and "2026-08-04" in text
    assert databases.version_text("card", {"version": "4.0.1",
                                           "installed": "2026-11-01 10:00:00"}) == \
        "4.0.1, retrieved 2026-11-01"
    assert databases.version_text("resfinder", {}) == "not stated by the source"


def test_the_workbook_database_row_never_says_unknown(tmp_path):
    from hydra_amr.config import Config
    from hydra_win import core

    store = DatabaseStore(tmp_path / "db")
    for name, version in (("ncbi", "2026-05-15.1"), ("argannot", "unknown")):
        (store.root / "nucl" / name).mkdir(parents=True)
        store.record(name, kind="nucl", path=f"nucl/{name}", version=version)
    info = core._run_info(store, ["ncbi", "argannot"], [], Config(db_dir=store.root),
                          core.Settings())
    assert "unknown" not in info.databases
    assert "ncbi (2026-05-15.1, retrieved " in info.databases
    assert f"argannot (not stated by the source; abricate commit " \
           f"{databases.ABRICATE_COMMIT[:7]}; retrieved " in info.databases


def _species_store(root):
    store = DatabaseStore(root)
    folder = store.root / "sketch" / "species"
    folder.mkdir(parents=True)
    (folder / "species_mash_sketches.msh").write_bytes(b"kleborate")
    store.record("species", kind="sketch", path="sketch/species",
                 sketches=["species_mash_sketches.msh"])
    return store, folder


def test_the_clinical_sketch_joins_kleborates_in_the_species_folder(tmp_path, monkeypatch):
    from hydra_amr.typing.species import SpeciesIdentifier

    packaged = tmp_path / "app" / "clinical_species.msh"
    packaged.parent.mkdir()
    packaged.write_bytes(b"clinical v2")
    monkeypatch.setattr(databases, "CLINICAL_SKETCH", packaged)
    store, folder = _species_store(tmp_path / "db")

    installed = databases.install_clinical_sketch(store)
    assert installed == folder / "clinical_species.msh"
    assert installed.read_bytes() == b"clinical v2"
    # Upstream reads every .msh in the folder: no engine change is needed.
    assert sorted(p.name for p in SpeciesIdentifier(store).sketches) == \
        ["clinical_species.msh", "species_mash_sketches.msh"]
    # The Kleborate entry keeps its own install date.
    installed_at = store.installed()["species"]["installed"]
    installed.write_bytes(b"clinical v1")           # a copy from an older release
    databases.install_clinical_sketch(store)
    assert installed.read_bytes() == b"clinical v2"
    assert store.installed()["species"]["installed"] == installed_at


def test_without_the_species_database_there_is_nowhere_to_put_it(tmp_path):
    assert databases.install_clinical_sketch(DatabaseStore(tmp_path / "db")) is None


def test_the_release_ships_the_clinical_sketch():
    # The packaged file the build copies into db/sketch/species.
    assert databases.CLINICAL_SKETCH.name == "clinical_species.msh"
    assert databases.CLINICAL_SKETCH.parent.name == "data"


def test_every_run_puts_the_clinical_sketch_in_place(tmp_path, monkeypatch):
    # A db folder from an older release, or imported from another PC, gets
    # the sketch on the next run, offline too: it ships with the program.
    from types import SimpleNamespace

    from hydra_win import core

    packaged = tmp_path / "app" / "clinical_species.msh"
    packaged.parent.mkdir()
    packaged.write_bytes(b"clinical")
    monkeypatch.setattr(databases, "CLINICAL_SKETCH", packaged)
    store, folder = _species_store(tmp_path / "db")
    monkeypatch.setattr(core.runtime, "prepare", lambda: SimpleNamespace(db_root=store.root))
    monkeypatch.setattr(core.netfetch, "install", lambda: None)
    monkeypatch.setattr(core.databases, "missing", lambda store: [])
    monkeypatch.setattr(core.databases, "organism_missing", lambda store: [])
    assert core.ensure_databases(offline=True) == {}
    assert (folder / "clinical_species.msh").read_bytes() == b"clinical"


def test_the_notice_says_where_the_clinical_sketch_comes_from(tmp_path, monkeypatch):
    packaged = tmp_path / "app"
    packaged.mkdir()
    (packaged / "clinical_species.msh").write_bytes(b"clinical")
    (packaged / "clinical_species_sources.tsv").write_text(
        "# Genomes behind clinical_species.msh, from NCBI RefSeq, retrieved 2026-11-27.\n"
        "# role ...\nspecies\trole\taccession\n"
        "Neisseria gonorrhoeae\tsketch\tGCF_1\nNeisseria gonorrhoeae\tvalidation\tGCF_2\n"
        "Staphylococcus aureus\tsketch\tGCF_3\nStaphylococcus aureus\tsketch\tGCF_4\n")
    monkeypatch.setattr(databases, "CLINICAL_SKETCH", packaged / "clinical_species.msh")
    monkeypatch.setattr(databases, "CLINICAL_SOURCES", packaged / "clinical_species_sources.tsv")
    store, folder = _species_store(tmp_path / "db")
    databases.install_clinical_sketch(store)
    # The table of genomes travels with the sketch, so the zip carries its provenance.
    assert (folder / "clinical_species_sources.tsv").exists()
    assert databases.clinical_sketch_summary() == {"genomes": 3, "species": 2,
                                                   "retrieved": "2026-11-27"}
    databases.write_notice(store.root)
    notice = (store.root / "DATABASES.txt").read_text(encoding="utf-8")
    assert "clinical_species.msh" in notice
    assert "3 genomes of 2 species" in notice and "NCBI RefSeq" in notice
    assert "2026-11-27" in notice
