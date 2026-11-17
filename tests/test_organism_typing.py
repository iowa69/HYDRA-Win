"""Organism typing in the Windows app: licence routes, the workbooks, the table.

No network and no databases: the routes are checked against what each upstream
module declares, and the sheets against synthetic results.
"""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from hydra_amr.db.manager import DatabaseStore
from hydra_amr.records import MlstCall, SampleResult, SpeciesCall, TypingResult
from hydra_amr.typing.organisms import registry as organisms
from hydra_win import databases, excel, gui


# ------------------------------------------------------------ licence routes
def test_every_upstream_module_has_a_route():
    assert {r.key for r in databases.ORGANISM_ROUTES} == set(organisms.modules())


def test_every_declared_database_is_either_bundled_or_downloaded():
    for route in databases.ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        declared = {db.name for db in entry.databases}
        assert set(route.bundled) | set(route.download) == declared, route.key
        assert not set(route.bundled) & set(route.download), route.key


def test_the_route_follows_what_the_source_states():
    """The owner's policy, applied to each module author's recorded status.

    No licence or terms stated -> shipped in the zip. Expressly restricted ->
    downloaded on the user's own PC.
    """
    exceptions = {("hinfluenzae", "cap"), ("ecoli", "shigeifinder")}
    for route in databases.ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        for db in entry.databases:
            where = "bundled" if db.name in route.bundled else "download"
            if db.redistribution == "restricted":
                assert where == "download", f"{route.key}/{db.name} is restricted"
            elif (route.key, db.name) in exceptions:
                assert where == "download", f"{route.key}/{db.name} is GPL-3.0"
            elif route.bundled:
                assert where == "bundled", f"{route.key}/{db.name} may be shipped"


def test_the_gpl_data_is_never_put_in_an_mit_zip():
    """hicap and ShigEiFinder are GPL-3.0: redistributable, but only as GPL."""
    for key, name in (("hinfluenzae", "cap"), ("ecoli", "shigeifinder")):
        route = databases.ORGANISM_BY_KEY[key]
        assert name in route.download
        assert "GPL" in route.why
        db = next(d for d in organisms.get(key).databases if d.name == name)
        assert "GPL" in db.licence


def test_the_ridom_spa_database_is_downloaded_not_shipped():
    route = databases.ORGANISM_BY_KEY["saureus"]
    assert route.download == ("spa",)
    assert "SpaServer" in route.why
    assert "markers" in route.bundled and "mlst" in route.bundled


def test_the_meningococcus_ships_nothing_because_all_of_it_is_pubmlst():
    route = databases.ORGANISM_BY_KEY["nmeningitidis"]
    assert route.bundled == ()
    assert "PubMLST" in route.why
    for db in organisms.get("nmeningitidis").databases:
        if db.name != "antigens":
            assert db.redistribution == "restricted"


def test_no_module_is_ever_given_a_pubmlst_api_key():
    """Anonymous access is what makes the pre-2025 data redistributable."""
    root = organisms.modules()["saureus"].module.__file__.rsplit("/", 1)[0]
    import pathlib

    for path in sorted(pathlib.Path(root).glob("*.py")):
        text = path.read_text()
        for forbidden in ("api_key", "apikey", "oauth", "Authorization",
                          "client_secret", "token="):
            assert forbidden not in text, f"{path.name} mentions {forbidden}"


def test_every_route_says_what_works_offline():
    for route in databases.ORGANISM_ROUTES:
        assert route.offline
        if route.download:
            assert route.why, f"{route.key} downloads something but gives no reason"


def test_organism_status_names_what_is_missing(tmp_path):
    store = DatabaseStore(tmp_path)
    rows = {row["name"]: row for row in databases.organism_status(store)}
    assert set(rows) == {f"typing-{r.key}" for r in databases.ORGANISM_ROUTES}
    saureus = rows["typing-saureus"]
    assert not saureus["installed"]
    assert "not a negative result" in saureus["impact"]
    assert saureus["route"] == "bundled + first launch"
    # Now give it the part the zip carries.
    root = tmp_path / "organisms" / "saureus"
    (root / "markers").mkdir(parents=True)
    (root / "markers" / "markers.fna").write_text(">x\nACGT\n")
    rows = {row["name"]: row for row in databases.organism_status(store)}
    assert rows["typing-saureus"]["installed"]
    assert rows["typing-saureus"]["missing"] == ["spa", "mlst"]


def test_organism_missing_lists_what_first_launch_must_fetch(tmp_path):
    store = DatabaseStore(tmp_path)
    assert set(databases.organism_missing(store)) == set(organisms.modules())
    root = tmp_path / "organisms"
    for key in ("spyogenes", "sagalactiae", "spneumoniae", "salmonella"):
        entry = organisms.get(key)
        for db in entry.databases:
            for pattern in organisms.DB_LAYOUT[key][db.name]:
                target = root / key / pattern.rstrip("/*")
                if pattern.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "data.fna").write_text("x")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("x")
    # Those four carry nothing a licence withholds, so nothing is left to fetch.
    assert set(databases.organism_missing(store)) == {
        "saureus", "hinfluenzae", "nmeningitidis", "ecoli"}


def test_the_zip_only_carries_the_files_its_route_allows(tmp_path):
    root = tmp_path / "organisms"
    entry = organisms.get("saureus")
    for name, files in (("spa", ("sparepeats.fasta", "spatypes.txt")),
                        ("markers", ("markers.fna",)),
                        ("mlst", ("profiles.tsv",))):
        (root / "saureus" / name).mkdir(parents=True)
        for filename in files:
            (root / "saureus" / name / filename).write_text("x")
    (root / "saureus" / "manifest.json").write_text("{}")
    route = databases.ORGANISM_BY_KEY["saureus"]
    keep = {p.name for p in databases.organism_bundled_files(route, root)}
    assert keep == {"markers.fna", "profiles.tsv", "manifest.json"}
    assert "sparepeats.fasta" not in keep, "the Ridom data must not be in the zip"
    assert entry.files_for("spa", root), "but it is still found once downloaded"


def test_a_partly_bundled_module_ships_no_completion_stamp(tmp_path):
    """Its fetch() returns at once on a stamp, so the rest would never arrive."""
    root = tmp_path / "organisms"
    base = root / "hinfluenzae"
    for name in ("ftsI", "bla", "cap", "mlst"):
        (base / name).mkdir(parents=True)
        (base / name / f"{name}.fna").write_text(">x\nACGT\n")
    (base / "version.json").write_text('{"version": "1"}')
    route = databases.ORGANISM_BY_KEY["hinfluenzae"]
    keep = {p.name for p in databases.organism_bundled_files(route, root)}
    assert keep == {"ftsI.fna", "bla.fna"}
    assert "version.json" not in keep
    assert "cap.fna" not in keep and "mlst.fna" not in keep


def test_a_fully_bundled_module_keeps_its_provenance_file(tmp_path):
    root = tmp_path / "organisms"
    base = root / "salmonella"
    for name in ("antigens", "markers", "spi", "mlst"):
        (base / name).mkdir(parents=True)
    (base / "antigens" / "antigens.fna").write_text(">x\nACGT\n")
    (base / "antigens" / "serovars.csv").write_text("x\n")
    (base / "markers" / "markers.fna").write_text(">x\nACGT\n")
    (base / "spi" / "spi.fna").write_text(">x\nACGT\n")
    (base / "mlst" / "profiles.tsv").write_text("ST\n")
    (base / "provenance.json").write_text("{}")
    route = databases.ORGANISM_BY_KEY["salmonella"]
    keep = {p.name for p in databases.organism_bundled_files(route, root)}
    assert "provenance.json" in keep
    assert "serovars.csv" in keep


# ---------------------------------------------------------------- the sheets
def _typed() -> SampleResult:
    result = SampleResult(sample="USA300")
    result.species = SpeciesCall(name="Staphylococcus aureus", genus="Staphylococcus",
                                 species="aureus", confidence="strong", evidence="Mash")
    result.mlst = MlstCall(scheme="saureus", sequence_type="8",
                           alleles={"arcC": "3"}, loci_found=7, loci_total=7)
    result.typing = organisms.relabel([
        TypingResult(scheme="spa", call="t008",
                     lineage="11-19-12-21-17-34-24-34-22-25",
                     alleles={"repeat_succession": "11-19-12-21-17-34-24-34-22-25",
                              "region": "NC_007793.1:128391-128785 (395 bp)"},
                     loci_found=1, loci_total=1,
                     note="spa types are tandem arrays and short-read assemblies "
                          "lose repeats in about 1-15% of isolates"),
        TypingResult(scheme="clonal_complex", call="CC8", lineage="ST8",
                     alleles={"ST": "8", "profile": "3-3-1-1-4-4-3"},
                     loci_found=7, loci_total=7, note="ST8 is the founder of CC8"),
        TypingResult(scheme="agr", call="I", lineage="agr group I",
                     alleles={"agr-I": "100.0% identity"}, loci_found=1, loci_total=1,
                     note="agr group I from the agrB-agrD-agrC' window"),
        TypingResult(scheme="capsule", call="not determined",
                     note="the capsule marker set is not installed"),
    ], organism="Staphylococcus aureus", key="saureus")
    return result


def _table(ws, header_row=1):
    rows = list(ws.iter_rows(min_row=header_row, values_only=True))
    header = rows[0]
    out = []
    for r in rows[1:]:
        if all(v is None for v in r):
            break
        out.append(dict(zip(header, r)))
    return out


def test_the_typing_sheet_carries_the_evidence_and_the_caveats(tmp_path):
    path = excel.write_genome_workbook(_typed(), tmp_path / "USA300.xlsx")
    ws = load_workbook(path)["Typing"]
    assert "spa t008 · CC8 · agr I" in ws.cell(row=1, column=1).value
    assert "never a negative result" in ws.cell(row=2, column=1).value
    rows = _table(ws, header_row=excel.TYPING_HEADER_ROW)
    by_scheme = {r["Scheme / database"]: r for r in rows}
    spa = by_scheme["spa type (Ridom)"]
    assert spa["Type"] == "Organism typing"
    assert spa["Organism"] == "Staphylococcus aureus"
    assert spa["Call"] == "t008"
    assert "repeat_succession = 11-19-12" in spa["Evidence: what the call rests on"]
    assert "NC_007793.1:128391-128785" in spa["Evidence: what the call rests on"]
    assert "tandem arrays" in spa["Caveats, limits and what could not be determined"]
    by_type = {r["Type"]: r for r in rows}
    assert by_type["Species"]["Call"] == "Staphylococcus aureus"
    assert by_type["MLST"]["Call"] == "8"
    assert by_type["MLST"]["Evidence: what the call rests on"] == "profile = arcC(3)"


def test_an_undetermined_call_is_coloured_and_explained(tmp_path):
    path = excel.write_genome_workbook(_typed(), tmp_path / "USA300.xlsx")
    ws = load_workbook(path)["Typing"]
    for row in range(excel.TYPING_HEADER_ROW + 1, ws.max_row + 1):
        if ws.cell(row=row, column=3).value == "Capsule serotype (cap locus)":
            cell = ws.cell(row=row, column=4)
            assert cell.value == "not determined"
            assert cell.fill.start_color.rgb.endswith(excel.MISSING_FILL)
            assert ws.cell(row=row, column=8).value == (
                "the capsule marker set is not installed")
            break
    else:
        pytest.fail("the undetermined call is not in the sheet at all")


def test_the_genome_summary_leads_with_the_headline(tmp_path):
    path = excel.write_genome_workbook(_typed(), tmp_path / "USA300.xlsx")
    ws = load_workbook(path)["Summary"]
    summary = {r[0]: r[1] for r in ws.iter_rows(values_only=True) if r[0]}
    assert summary["Organism typing"] == "spa t008 · CC8 · agr I"
    assert summary["spa type (Ridom)"].startswith("t008")
    assert summary["Capsule serotype (cap locus)"] == "not determined"


def test_the_cumulative_typing_matrix_compares_the_batch(tmp_path):
    other = _typed()
    other.sample = "OTHER"
    other.typing = organisms.relabel(
        [TypingResult(scheme="spa", call="t032", lineage="-")],
        organism="Staphylococcus aureus", key="saureus")
    path = excel.write_cumulative_workbook([_typed(), other],
                                           tmp_path / "Cumulative_results.xlsx")
    wb = load_workbook(path)
    assert "Typing_matrix" in wb.sheetnames
    ws = wb["Typing_matrix"]
    header = [ws.cell(row=2, column=c).value for c in range(1, ws.max_column + 1)]
    assert header[:4] == ["Assembly", "Species", "ST", "Organism typing (headline)"]
    assert "spa type (Ridom)" in header
    column = header.index("spa type (Ridom)") + 1
    calls = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=column).value
             for r in range(3, ws.max_row + 1)}
    assert calls == {"USA300": "t008", "OTHER": "t032"}
    # The organism band above the scheme columns.
    assert ws.cell(row=1, column=column).value == "Staphylococcus aureus"


def test_the_cumulative_summary_carries_the_headline(tmp_path):
    path = excel.write_cumulative_workbook([_typed()],
                                           tmp_path / "Cumulative_results.xlsx")
    rows = _table(load_workbook(path)["Summary"])
    assert rows[0]["Organism typing (headline)"] == "spa t008 · CC8 · agr I"


def test_a_species_no_module_covers_says_so_rather_than_nothing(tmp_path):
    plain = SampleResult(sample="KP")
    plain.species = SpeciesCall(name="Klebsiella pneumoniae", genus="Klebsiella",
                                species="pneumoniae")
    assert excel.typing_headline(plain) == ""
    assert excel.organism_typing_absence(plain) == "no module for this species"
    head = excel.headline(plain)
    assert head["typing"] == "no module for this species"
    path = excel.write_genome_workbook(plain, tmp_path / "KP.xlsx")
    summary = {r[0]: r[1] for r in load_workbook(path)["Summary"].iter_rows(values_only=True)
               if r[0]}
    assert summary["Organism typing"] == "no module for this species"


def test_a_module_that_could_not_run_is_not_read_as_a_negative():
    result = SampleResult(sample="SA")
    result.species = SpeciesCall(name="Staphylococcus aureus")
    result.warnings = ["Staphylococcus aureus typing skipped: its database is not "
                       "installed. Install it with:  hydra db download typing-saureus"]
    assert excel.organism_typing_absence(result) == "data not installed"
    assert excel.headline(result)["typing"] == "data not installed"


# --------------------------------------------------------------- the window
def test_the_window_table_has_a_column_for_the_organism_call():
    ids = [c[0] for c in gui.COLUMNS]
    assert "typing" in ids
    assert ids.index("typing") == ids.index("mlst") + 1
    width = next(c[2] for c in gui.COLUMNS if c[0] == "typing")
    # The table has to fit a 1366-wide laptop screen with every column visible.
    assert sum(c[2] for c in gui.COLUMNS) <= 155, "the table is too wide for a laptop"
    assert width >= len("spa t008 · CC8 · agr I")
