"""Which reference databases HYDRA-Win uses, and how each one reaches the user.

Two routes:

* **bundled** - built in CI from the upstream source and shipped inside the
  release zip. That covers every source whose licence allows redistribution,
  and, at the owner's request, the five sources that state no licence at all
  (VFDB, ARG-ANNOT, MEGARes, E. coli VF, EcOH), which abricate's public
  repository has redistributed for years; DATABASES.txt says so and invites a
  rights holder to ask for removal;
* **first launch** - downloaded from the upstream source on the user's machine,
  because the source's terms withhold redistribution (CARD, PubMLST). These can
  also be imported from a folder copied from another PC (:func:`import_folder`).

Building uses upstream Hydra's own fetchers and importers
(:meth:`hydra_amr.db.manager.DatabaseStore.download`), so the database is
exactly what ``hydra db download`` would install. The four abricate-only
sources that upstream can only *import* (ARG-ANNOT, MEGARes, E. coli VF, EcOH)
are fetched from abricate's repository at a pinned commit and passed through
the same importer.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hydra_amr.db import fetch as upstream_fetch
from hydra_amr.db.manager import DatabaseStore
from hydra_amr.db.registry import DATABASES, spec_for
from hydra_amr.typing.organisms import registry as organisms
from hydra_amr.utils import HydraError

LOG = logging.getLogger("hydra")

#: abricate repository commit the abricate-only databases are taken from.
ABRICATE_COMMIT = "e2064df7d193ad783d4c188d4ce79706faf9eb75"
ABRICATE_URL = ("https://raw.githubusercontent.com/tseemann/abricate/"
                f"{ABRICATE_COMMIT}/db/{{name}}/sequences")
ABRICATE_ONLY = ("argannot", "megares", "ecoli_vf", "ecoh")

#: Kleborate release the lineage loci and species sketches are taken from.
#: Upstream follows GitHub's "latest release"; Kleborate v3.3.0b2 (2026-11-15)
#: dropped the species sketches that upstream's fetcher expects, so the
#: release is pinned to upstream's own known-good fallback for reproducible builds.
KLEBORATE_RELEASE = upstream_fetch.KLEBORATE_FALLBACK


def _pin_kleborate() -> None:
    upstream_fetch._kleborate_release_url = lambda: KLEBORATE_RELEASE


@dataclass(frozen=True)
class Route:
    name: str
    route: str          # "bundled" | "first launch"
    licence: str
    why: str


NO_LICENCE = ("the source states no licence or terms; shipped under the project owner's "
              "policy (no stated terms: ship; expressly restrictive terms: download on first "
              "launch), which is not a licence from the source; a rights holder can ask for "
              "removal (see DATABASES.txt)")

#: Every database HYDRA-Win installs, in install order (protein first: the
#: nucleotide importers borrow its drug-class annotation).
ROUTES: tuple[Route, ...] = (
    Route("protein", "bundled", "public domain (NCBI AMRFinderPlus)",
          "US-government work, freely redistributable"),
    Route("ncbi", "bundled", "public domain (NCBI AMRFinderPlus)",
          "US-government work, freely redistributable"),
    Route("resfinder", "bundled", "Apache-2.0 (CGE ResFinder)", "redistribution permitted"),
    Route("plasmidfinder", "bundled", "Apache-2.0 (CGE PlasmidFinder)", "redistribution permitted"),
    Route("sccmec", "bundled", "Apache-2.0 (CGE SCCmecFinder)", "redistribution permitted"),
    Route("lineage", "bundled", "GPL-3.0 (Kleborate modules)",
          "redistribution permitted with the licence text and source location"),
    Route("species", "bundled", "GPL-3.0 (Kleborate species Mash sketches)",
          "redistribution permitted with the licence text and source location"),
    Route("vfdb", "bundled", "VFDB core set: no licence stated by the source", NO_LICENCE),
    Route("argannot", "bundled", "ARG-ANNOT: no licence stated by the source", NO_LICENCE),
    Route("megares", "bundled", "MEGARes: no licence stated by the source", NO_LICENCE),
    Route("ecoli_vf", "bundled", "E. coli VF: no licence stated by the source", NO_LICENCE),
    Route("ecoh", "bundled", "EcOH: no licence stated by the source", NO_LICENCE),
    Route("pubmlst", "first launch", "PubMLST terms of use",
          "PubMLST's terms forbid redistributing or repackaging data downloaded since 2025"),
    Route("card", "first launch", "CARD terms of use (academic/non-commercial)",
          "CARD's terms forbid redistribution without McMaster University's written consent"),
)

#: What is missing from a run when a database is not installed, in words.
#: A missing database must never read as a negative result.
IMPACT = {
    "protein": "no AMRFinderPlus protein search and no point mutations (required)",
    "ncbi": "NCBI AMRFinderPlus nucleotide genes not screened (required)",
    "resfinder": "ResFinder genes not screened",
    "plasmidfinder": "no plasmid replicon typing (PlasmidFinder not installed)",
    "sccmec": "no SCCmec typing (SCCmecFinder not installed)",
    "lineage": "no lineage/virulence-locus typing (Kleborate modules not installed)",
    "species": "species named from the MLST scheme only (Mash sketches not installed)",
    "vfdb": "VFDB virulence genes not screened",
    "argannot": "ARG-ANNOT genes not screened",
    "megares": "MEGARes genes not screened",
    "ecoli_vf": "E. coli virulence factors (ecoli_vf) not screened",
    "ecoh": "E. coli O/H serotype loci not screened (EcOH not installed)",
    "pubmlst": ("NO MLST: the PubMLST schemes are not installed, so no sequence type was "
                "determined; an empty ST is not a negative result"),
    "card": "CARD not screened: genes only CARD lists were not looked for",
}

#: Display names.
TITLES = {"protein": "AMRFinderPlus proteins, point mutations", "ncbi": "AMRFinderPlus genes (NCBI)",
          "resfinder": "ResFinder", "plasmidfinder": "PlasmidFinder", "sccmec": "SCCmecFinder",
          "lineage": "Kleborate lineage modules", "species": "Kleborate species sketches",
          "vfdb": "VFDB (core)", "argannot": "ARG-ANNOT", "megares": "MEGARes",
          "ecoli_vf": "E. coli VF", "ecoh": "EcOH", "pubmlst": "PubMLST (MLST schemes)",
          "card": "CARD"}

#: Last download outcome per database, kept next to the manifest.
STATUS_FILE = "download-status.json"

BUNDLED = tuple(r.name for r in ROUTES if r.route == "bundled")
FIRST_LAUNCH = tuple(r.name for r in ROUTES if r.route == "first launch")
ALL = BUNDLED + FIRST_LAUNCH

#: Gene-screening databases, in the order the Pivot sheet shows them. This is
#: upstream's ``-d all`` minus vfdb_full (not fetchable upstream, redundant with
#: the VFDB core set and the slowest search by far).
SCREEN = ("ncbi", "protein", "card", "resfinder", "argannot", "megares",
          "vfdb", "ecoli_vf", "plasmidfinder", "ecoh")

ProgressFn = Callable[[float, str], None]


def source_url(name: str) -> str:
    if name in ABRICATE_ONLY:
        return ABRICATE_URL.format(name=name)
    return spec_for(name).url


def missing(store: DatabaseStore, names: tuple[str, ...] = ALL) -> list[str]:
    return [name for name in names if not store.is_installed(name)]


def adopt(store: DatabaseStore, names, sources) -> list[str]:
    """Copy databases an earlier install already downloaded into another folder.

    v0.1.0 kept its databases in ``%LOCALAPPDATA%\\Hydra-win`` (or another
    fallback home) when its own folder was not writable; a newer version
    unzipped somewhere writable reuses them instead of downloading again.
    """
    adopted: list[str] = []
    for root in sources:
        root = Path(root)
        try:
            if not (root / "manifest.json").exists() or root.resolve() == store.root.resolve():
                continue
            other = DatabaseStore(root)
            entries = other.installed()
        except (OSError, HydraError):
            continue
        for name in names:
            if name in adopted or store.is_installed(name) or not other.is_installed(name):
                continue
            entry = dict(entries[name])
            relative = entry.get("path", "")
            if not relative:
                continue
            source, target = root / relative, store.root / relative
            try:
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            except OSError as exc:
                LOG.warning("could not reuse %s from %s: %s", name, root, exc)
                continue
            entry.pop("installed", None)
            store.record(name, **entry)
            LOG.info("reused %s from %s (downloaded by an earlier version)", name, root)
            adopted.append(name)
    return adopted


def status(store: DatabaseStore) -> list[dict]:
    rows = []
    installed = store.installed()
    failures = load_failures(store)
    for route in ROUTES:
        entry = installed.get(route.name, {})
        ok = store.is_installed(route.name)
        failure = failures.get(route.name, {}) if not ok else {}
        rows.append({
            "name": route.name, "title": TITLES.get(route.name, route.name),
            "route": route.route, "licence": route.licence,
            "installed": ok,
            "version": entry.get("version", ""),
            "sequences": entry.get("sequences", entry.get("schemes", "")),
            "installed_on": entry.get("installed", ""),
            "source": entry.get("source", ""),
            "reason": failure.get("reason", "" if ok else "not installed yet"),
            "failed_at": failure.get("when", ""),
            "impact": "" if ok else IMPACT.get(route.name, f"{route.name} not available"),
        })
    return rows


def missing_analyses(store: DatabaseStore, names: tuple[str, ...] = ALL) -> dict[str, str]:
    """name -> what the run cannot do because that database is not installed."""
    return {name: IMPACT.get(name, f"{name} not available")
            for name in names if not store.is_installed(name)}


# ----------------------------------------------------------- failure record
def load_failures(store: DatabaseStore) -> dict[str, dict]:
    try:
        data = json.loads((store.root / STATUS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_outcome(store: DatabaseStore, name: str, reason: str | None) -> None:
    """Remember why *name* failed (or forget a failure once it installs)."""
    data = load_failures(store)
    if reason:
        data[name] = {"reason": reason, "when": time.strftime("%Y-%m-%d %H:%M:%S")}
    else:
        data.pop(name, None)
    try:
        path = store.root / STATUS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError as exc:
        LOG.debug("could not record the download outcome of %s: %s", name, exc)


# ------------------------------------------------------- import from a folder
def _candidate_roots(folder: Path) -> list[Path]:
    """A database root inside *folder*: the folder itself, its db/ or HYDRA-Win/db."""
    folder = Path(folder)
    out = []
    for root in (folder, folder / "db", folder / "HYDRA-Win" / "db"):
        if (root / "manifest.json").exists():
            out.append(root)
    return out


def import_folder(store: DatabaseStore, folder: Path | str,
                  names: tuple[str, ...] = ALL) -> tuple[list[str], str]:
    """Install missing databases from a copy made on another PC.

    *folder* can be HYDRA-Win's ``db`` folder copied from a PC where the
    download worked, the whole HYDRA-Win folder, or an upstream Hydra database
    (``~/.hydra/db``). Returns (imported names, message).
    """
    roots = _candidate_roots(Path(folder))
    if not roots:
        return [], (f"{folder} is not a database folder: it has no manifest.json (copy the whole "
                    "'db' folder that sits next to HYDRA-Win.exe on the other PC)")
    # The organism typing data travels the same way: it is in the other PC's
    # manifest under typing-<key>, with its own path under organisms/.
    names = tuple(names) + tuple(name for name in organism_db_names()
                                 if name not in names)
    wanted = [name for name in names if not store.is_installed(name)]
    if not wanted:
        return [], "every database is already installed"
    imported = adopt(store, wanted, roots)
    for name in imported:
        record_outcome(store, name, None)
        store.record(name, imported_from=str(Path(folder)))
    still = [name for name in wanted if not store.is_installed(name)]
    message = (f"imported {', '.join(imported)} from {folder}" if imported
               else f"{folder} holds none of the missing databases ({', '.join(wanted)})")
    if imported and still:
        message += f"; still missing: {', '.join(still)}"
    return imported, message


def _download_abricate(store: DatabaseStore, name: str) -> None:
    work = store.root / ".download" / name
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        upstream_fetch._get(ABRICATE_URL.format(name=name), work / "sequences")
        store.import_one(spec_for(name), work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ncbi_version(store: DatabaseStore) -> str:
    """The AMRFinderPlus release, which upstream's fetcher does not record."""
    target = store.root / ".download" / "ncbi-version.txt"
    try:
        upstream_fetch._get(f"{upstream_fetch.NCBI_LATEST}/version.txt", target)
        return target.read_text(encoding="utf-8").strip().splitlines()[0]
    except Exception:  # noqa: BLE001 - a missing version stamp is cosmetic
        return ""
    finally:
        target.unlink(missing_ok=True)


def install(store: DatabaseStore, names: list[str], progress: ProgressFn | None = None,
            stop_on_error: bool = False) -> dict[str, str]:
    """Download and import *names* in order. Returns name -> reason for failures."""
    from . import netfetch  # noqa: PLC0415

    netfetch.install()
    _pin_kleborate()
    order = [name for name in ALL if name in names] + [n for n in names if n not in ALL]
    errors: dict[str, str] = {}
    for index, name in enumerate(order):
        if progress:
            progress(index / max(1, len(order)), f"Downloading {name} ({index + 1}/{len(order)})")
        LOG.info("downloading database %s from %s", name, source_url(name))
        started = time.time()
        try:
            if name in ABRICATE_ONLY:
                _download_abricate(store, name)
            else:
                store.download(name, force=True)
            # The staging path recorded upstream is a scratch directory; the
            # source worth recording is where the data came from.
            extra = {}
            if name in ("protein", "ncbi"):
                extra["version"] = _ncbi_version(store)
            store.record(name, source=source_url(name), **{k: v for k, v in extra.items() if v})
            record_outcome(store, name, None)
            LOG.info("installed %s in %.0fs", name, time.time() - started)
        except Exception as exc:  # noqa: BLE001 - one source must not sink the rest
            from .netfetch import describe_failure  # noqa: PLC0415

            errors[name] = describe_failure(exc)
            LOG.error("could not install %s from %s: %s", name, source_url(name), errors[name])
            LOG.debug("details: %s", exc)
            record_outcome(store, name, errors[name])
            shutil.rmtree(store.root / ".download" / name, ignore_errors=True)
            if stop_on_error:
                raise
    if progress:
        progress(1.0, "Databases ready" if not errors else
                 f"{len(errors)} database(s) could not be downloaded")
    shutil.rmtree(store.root / ".download", ignore_errors=True)
    return errors


LICENCE_TEXTS = {
    "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
}


def build_bundle(db_root: Path, names: tuple[str, ...] = BUNDLED) -> Path:
    """Build the redistributable part of the database (CI)."""
    db_root = Path(db_root)
    store = DatabaseStore(db_root)
    _pin_kleborate()
    # A source server that is briefly unreachable from CI is retried, never
    # replaced by an older copy: the build fails if a source stays down.
    pending = list(names)
    for attempt in range(3):
        errors = install(store, pending)
        pending = [name for name in pending if name in errors]
        if not pending:
            break
        LOG.warning("bundle build: retrying %s in %ds", ", ".join(pending), 60 * (attempt + 1))
        time.sleep(60 * (attempt + 1))
    if pending:
        raise HydraError(f"could not build the bundled databases {', '.join(pending)}: "
                         + "; ".join(f"{n}: {load_failures(store).get(n, {}).get('reason')}"
                                     for n in pending))
    (db_root / STATUS_FILE).unlink(missing_ok=True)

    licences = db_root / "licences"
    licences.mkdir(parents=True, exist_ok=True)
    for filename, url in LICENCE_TEXTS.items():
        upstream_fetch._get(url, licences / filename)
    kleborate = upstream_fetch._kleborate_release_url()
    tag = re.search(r"/tags/([^/]+)\.tar\.gz$", kleborate)
    tag_name = tag.group(1) if tag else "main"
    upstream_fetch._get(f"https://raw.githubusercontent.com/klebgenomics/Kleborate/"
                        f"{tag_name}/LICENSE", licences / "Kleborate-GPL-3.0.txt")
    for name in ("lineage", "species"):
        if store.is_installed(name):
            store.record(name, source=kleborate, version=tag_name)
    sizes = build_organism_bundle(db_root)
    LOG.info("organism typing data bundled: %.2f MB in total",
             sum(sizes.values()) / 1e6)
    write_notice(db_root, kleborate_source=kleborate)
    return db_root


def write_notice(db_root: Path, kleborate_source: str = "") -> None:
    store = DatabaseStore(db_root)
    installed = store.installed()
    lines = [
        "HYDRA-Win reference databases",
        "=============================",
        "",
        "Each database keeps its own terms. Databases marked 'bundled' were built from",
        "the upstream source by the HYDRA-Win release workflow on the date shown and",
        "ship inside the zip; databases marked 'first launch' are not redistributed and",
        "are downloaded from their source on your computer (or imported from a copy",
        "made on another PC: HYDRA-Win.exe --import-db FOLDER).",
        "",
        "Which databases ship follows the project owner's policy: a source that states",
        "no licence or terms is shipped in the zip; a source that expressly restricts",
        "redistribution (CARD, PubMLST) is downloaded on first launch. VFDB, ARG-ANNOT,",
        "MEGARes, E. coli VF and EcOH state no licence at all, so they are shipped. That",
        "is the owner's decision, not a licence granted by those sources. If you hold",
        "rights in one of them and want it removed from the zip, open an issue at",
        "https://github.com/iowa69/HYDRA-Win/issues and it will be moved back to a",
        "first-launch download.",
        "",
    ]
    for route in ROUTES:
        spec = DATABASES.get(route.name)
        entry = installed.get(route.name, {})
        lines.append(f"{route.name:14s} {route.route:13s} {route.licence}")
        lines.append(f"{'':14s} source:   {source_url(route.name)}")
        if route.name in ABRICATE_ONLY:
            lines.append(f"{'':14s} copy:     abricate repository, commit {ABRICATE_COMMIT}")
        if entry.get("version") or entry.get("installed"):
            version = entry.get("version")
            if not version or version == "unknown":
                version = "not stated by the source"
            lines.append(f"{'':14s} version:  {version}; retrieved {entry.get('installed', '')[:10]}")
        if spec and spec.citation:
            lines.append(f"{'':14s} citation: {spec.citation}")
        lines.append("")
    if kleborate_source:
        lines += ["The 'lineage' and 'species' databases are derived from the Kleborate",
                  "modules (GPL-3.0,",
                  "licences/Kleborate-GPL-3.0.txt). Corresponding source:",
                  f"  {kleborate_source}", ""]
    lines += ["ResFinder, PlasmidFinder and SCCmecFinder data: Apache-2.0,",
              "licences/Apache-2.0.txt. Sources are listed above.", ""]
    lines += organism_notice_lines(db_root)
    (Path(db_root) / "DATABASES.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- organisms
#: Organism-specific typing data, one entry per upstream module. Which of a
#: module's declared databases ships inside the zip follows the owner's policy
#: applied to the ``redistribution`` field the module author recorded:
#:
#:   * ``permitted`` or ``unstated`` -> bundled. A source that states no terms
#:     at all is shipped, which is the owner's decision and not a licence from
#:     that source; DATABASES.txt says so and invites a removal request.
#:   * ``restricted`` -> downloaded on the user's own machine on first launch.
#:
#: with two deliberate exceptions, both GPL-3.0 data inside an MIT zip. hicap's
#: *cap* database and ShigEiFinder's gene sets may be redistributed under the
#: GPL, but only under the GPL -- so they are downloaded rather than mixed into
#: this zip, which keeps the licence question from arising at all.
@dataclass(frozen=True)
class OrganismRoute:
    key: str
    #: Declared database names shipped inside the zip.
    bundled: tuple[str, ...]
    #: Declared database names fetched on the user's machine at first launch.
    download: tuple[str, ...]
    #: What works offline, and what has to wait for the download.
    offline: str
    #: Why anything is downloaded rather than shipped.
    why: str = ""


ORGANISM_ROUTES: tuple[OrganismRoute, ...] = (
    OrganismRoute(
        "saureus", bundled=("markers", "mlst"), download=("spa",),
        offline="agr group, SCCmec, PVL, tst, enterotoxins, haemolysins, hlb, "
                "capsule locus, immune evasion cluster, ACME, blaZ and the MLST "
                "clonal complex all work offline; the spa type needs the download",
        why="the Ridom spaServer policy expressly limits use of a copy of the "
            "database: \"Copies of the SpaServer database may not be used without "
            "permission to produce database driven web server or any other product "
            "or service\", and permits non-commercial use by individuals who "
            "download it themselves - which is what the first-launch download is"),
    OrganismRoute(
        "spyogenes", bundled=("emm", "panel"), download=(),
        offline="everything: emm type and cluster, virulence and superantigen "
                "repertoire, prophage content, regulatory loci, adhesins"),
    OrganismRoute(
        "sagalactiae",
        bundled=("cps", "panel", "surface_targets", "alp_alleles"), download=(),
        offline="everything: capsular serotype, Alp type, surface proteins, "
                "pilus islands, marker genes, PBP2X substitutions"),
    OrganismRoute(
        "spneumoniae",
        bundled=("cps", "cdc-serotype-probes", "cdc-pbp", "cdc-resistance-probes"),
        download=(),
        offline="everything: capsular serotype, PBP type and its reference MIC "
                "where the triplet is in the CDC table, resistance determinants, "
                "pilus islets"),
    OrganismRoute(
        "hinfluenzae", bundled=("ftsI", "bla"), download=("cap", "mlst"),
        offline="the PBP3 (ftsI) substitution pattern, its rPBP3 group and the "
                "beta-lactam interpretation work offline; the capsule type and "
                "the sequence type need the download",
        why="the cap reference set is package data of hicap, which is GPL-3.0: "
            "redistributable, but only under the GPL, so it is not mixed into "
            "this MIT zip. The MLST alleles are PubMLST data"),
    OrganismRoute(
        "nmeningitidis", bundled=(),
        download=("capsule", "peptides", "mlst", "amr", "antigens"),
        offline="nothing: every meningococcal call needs the first-launch "
                "download. Until it has run, the typing reads 'not determined' "
                "with that reason given",
        why="every one of this module's databases is PubMLST nomenclature data, "
            "whose terms restrict redistribution of anything submitted after "
            "2024-12-31. The two porA/fetA reference proteins could be shipped, "
            "but on their own they type nothing"),
    OrganismRoute(
        "salmonella",
        bundled=("antigens", "serovars", "spi", "markers", "mlst"), download=(),
        offline="everything: serovar from the antigenic formula, subspecies, H2 "
                "locus, pathogenicity islands, virulence plasmid, typhoidal "
                "markers, ST and eBurst group"),
    OrganismRoute(
        "ecoli", bundled=("fimtyper", "stxtyper", "virulencefinder"),
        download=("shigeifinder",),
        offline="phylogroup, fimH allele, ST131 subclone, Shiga toxin subtype, "
                "pathotype, intimin subtype and the ExPEC/UPEC virulence panel "
                "work offline; the Shigella/EIEC cluster call needs the download",
        why="ShigEiFinder's gene sets are GPL-3.0: redistributable, but only "
            "under the GPL, so they are not mixed into this MIT zip"),
)

ORGANISM_BY_KEY = {route.key: route for route in ORGANISM_ROUTES}

#: Organism modules with anything to download on the user's machine.
ORGANISM_DOWNLOADS = tuple(r.key for r in ORGANISM_ROUTES if r.download)


def organism_root(store: DatabaseStore) -> Path:
    return store.root / organisms.DB_SUBDIR


def organism_db_names() -> tuple[str, ...]:
    """The ``hydra db`` names of the organism typing databases."""
    return tuple(f"typing-{r.key}" for r in ORGANISM_ROUTES)


def organism_bundled_files(route: OrganismRoute, root: Path) -> list[Path]:
    """Every file of *route* that belongs inside the zip."""
    entry = organisms.get(route.key)
    out: list[Path] = []
    for name in route.bundled:
        out.extend(entry.files_for(name, root))
    out.extend(entry.provenance_files(root))
    return out


def organism_status(store: DatabaseStore) -> list[dict]:
    """One row per organism typing module, for the GUI and the log."""
    root = organism_root(store)
    rows = []
    for route in ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        missing_dbs = entry.missing_databases(root)
        rows.append({
            "name": f"typing-{route.key}",
            "title": f"{entry.title} typing",
            "route": "bundled" if route.bundled and not route.download else
                     "first launch" if not route.bundled else "bundled + first launch",
            "licence": " | ".join(
                f"{db.name}: {db.redistribution}" for db in entry.databases),
            "installed": entry.installed(root),
            "complete": not missing_dbs,
            "missing": missing_dbs,
            "offline": route.offline,
            "why": route.why,
            "impact": "" if entry.installed(root) else
                      f"no {entry.title} typing: its data is not installed "
                      f"(not a negative result)",
        })
    return rows


def organism_missing(store: DatabaseStore) -> list[str]:
    """Modules that still need their first-launch download."""
    root = organism_root(store)
    out = []
    for route in ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        if [name for name in route.download if not entry.files_for(name, root)]:
            out.append(route.key)
        elif not entry.installed(root):
            out.append(route.key)
    return out


def install_organisms(store: DatabaseStore, keys: list[str],
                      progress: ProgressFn | None = None) -> dict[str, str]:
    """Run each module's own fetch() on the user's machine. Returns failures."""
    from . import netfetch  # noqa: PLC0415

    netfetch.install()
    root = organism_root(store)
    root.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}
    ordered = [r.key for r in ORGANISM_ROUTES if r.key in keys]
    for index, key in enumerate(ordered):
        entry = organisms.get(key)
        if progress:
            progress(index / max(1, len(ordered)),
                     f"Downloading {entry.title} typing data "
                     f"({index + 1}/{len(ordered)})")
        started = time.time()
        try:
            # install_organism() runs the module's own fetch() and then records
            # it in the manifest; fetching here as well would download the same
            # files twice on a PC that has none of them yet.
            store.install_organism(f"typing-{key}", force=True)
            record_outcome(store, f"typing-{key}", None)
            LOG.info("installed %s typing data in %.0fs", entry.title,
                     time.time() - started)
        except Exception as exc:  # noqa: BLE001 - one module must not sink the rest
            from .netfetch import describe_failure  # noqa: PLC0415

            errors[key] = describe_failure(exc)
            LOG.error("could not install %s typing data: %s", entry.title, errors[key])
            record_outcome(store, f"typing-{key}", errors[key])
    return errors


def build_organism_bundle(db_root: Path) -> dict[str, int]:
    """Build every module's data, then keep only what the zip may carry (CI).

    The modules build all of their own data in one pass, so the restricted
    parts are fetched here and then deleted: nothing a licence withholds leaves
    this machine. The download caches go too - 12 MB of RefSeq protein FASTA
    that nothing reads at run time.
    """
    root = organism_root(DatabaseStore(db_root))
    root.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for route in ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        if not route.bundled:
            LOG.info("%s: nothing may be bundled; it is a first-launch download",
                     entry.title)
            shutil.rmtree(entry.root(root), ignore_errors=True)
            sizes[route.key] = 0
            continue
        last: Exception | None = None
        for attempt in range(3):
            try:
                entry.fetch(root)
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                LOG.warning("%s typing data: attempt %d failed (%s); retrying in %ds",
                            entry.title, attempt + 1, exc, 30 * (attempt + 1))
                time.sleep(30 * (attempt + 1))
        if last is not None:
            raise HydraError(f"could not build the {entry.title} typing data: {last}")
        keep = {p.resolve() for p in organism_bundled_files(route, root)}
        for path in sorted(entry.root(root).rglob("*")):
            if path.is_file() and path.resolve() not in keep:
                path.unlink()
        for directory in sorted(entry.root(root).rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        sizes[route.key] = sum(p.stat().st_size for p in entry.root(root).rglob("*")
                               if p.is_file())
        LOG.info("%s: bundled %s (%.2f MB); %s downloaded on first launch",
                 entry.title, ", ".join(route.bundled), sizes[route.key] / 1e6,
                 ", ".join(route.download) or "nothing")
    return sizes


def organism_notice_lines(db_root: Path) -> list[str]:
    """The organism typing section of DATABASES.txt."""
    root = organism_root(DatabaseStore(db_root))
    lines = [
        "",
        "Organism-specific typing data",
        "-----------------------------",
        "",
        "One set per organism, built by the upstream module that uses it. The same",
        "policy decides the route: a source that states no licence or terms is shipped",
        "in the zip, a source that expressly restricts redistribution is downloaded on",
        "your own computer at first launch. Two sets are downloaded although their",
        "licence would permit redistribution: hicap's cap database and ShigEiFinder's",
        "gene sets are GPL-3.0, which is copyleft, and this zip is MIT.",
        "",
        "PubMLST data is fetched anonymously and no API key is ever used. Anonymous",
        "access returns only data submitted on or before 31 December 2024, which",
        "PubMLST's terms allow to be 'downloaded, used, and redistributed without",
        "restriction, subject only to proper scientific citation and acknowledgement'.",
        "A sequence type assigned after that date therefore reads 'not determined',",
        "with that reason given, rather than being guessed.",
        "",
        "If you hold rights in any of these and want it removed from the zip, open an",
        "issue at https://github.com/iowa69/HYDRA-Win/issues and it will be moved to a",
        "first-launch download.",
        "",
    ]
    for route in ORGANISM_ROUTES:
        entry = organisms.get(route.key)
        lines.append(f"{entry.title} (typing-{route.key})")
        lines.append(f"{'':2s}bundled in the zip: {', '.join(route.bundled) or 'nothing'}")
        lines.append(f"{'':2s}downloaded at first launch: "
                     f"{', '.join(route.download) or 'nothing'}")
        if route.why:
            for chunk in _wrap(route.why, 86):
                lines.append(f"{'':4s}{chunk}")
        lines.append(f"{'':2s}works offline: ")
        for chunk in _wrap(route.offline, 86):
            lines.append(f"{'':4s}{chunk}")
        for db in entry.databases:
            where = "bundled" if db.name in route.bundled else "first launch"
            lines.append(f"{'':2s}- {db.name} [{where}]")
            lines.append(f"{'':6s}source:   {db.source}")
            lines.append(f"{'':6s}version:  {db.version}")
            lines.append(f"{'':6s}licence:  {db.licence}")
            lines.append(f"{'':6s}redistribution as stated by the source: "
                         f"{db.redistribution}")
            if db.notes:
                lines.append(f"{'':6s}notes:    {db.notes}")
            ref = next((r for r in entry.references if r.key == db.reference), None)
            if ref is not None:
                doi = f" doi:{ref.doi}" if ref.doi else ""
                pmid = f" PMID:{ref.pmid}" if ref.pmid else ""
                lines.append(f"{'':6s}citation: {ref.authors} ({ref.year}) "
                             f"{ref.title}. {ref.journal}.{doi}{pmid}")
        installed = entry.missing_databases(root)
        if installed:
            lines.append(f"{'':2s}not present in this copy: {', '.join(installed)}")
        lines.append("")
    return lines


def _wrap(text: str, width: int) -> list[str]:
    import textwrap  # noqa: PLC0415

    return textwrap.wrap(" ".join(str(text).split()), width=width) or [""]


def require_core(store: DatabaseStore) -> None:
    if not store.is_installed("protein") or not store.is_installed("ncbi"):
        raise HydraError(
            f"the bundled databases are missing from {store.root}; re-extract the "
            "HYDRA-Win zip (the 'db' folder must sit next to HYDRA-Win.exe)")
