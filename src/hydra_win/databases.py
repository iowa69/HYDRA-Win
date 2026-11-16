"""Which reference databases Hydra-win uses, and how each one reaches the user.

Two routes, decided by each source's licence:

* **bundled** - built in CI from the upstream source and shipped inside the
  release zip, because the licence allows redistribution;
* **first launch** - downloaded from the upstream source on the user's machine
  the first time the app starts, because redistribution is not granted.

Building uses upstream Hydra's own fetchers and importers
(:meth:`hydra_amr.db.manager.DatabaseStore.download`), so the database is
exactly what ``hydra db download`` would install. The four abricate-only
sources that upstream can only *import* (ARG-ANNOT, MEGARes, E. coli VF, EcOH)
are fetched from abricate's repository at a pinned commit and passed through
the same importer.
"""

from __future__ import annotations

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


#: Every database Hydra-win installs, in install order (protein first: the
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
    Route("pubmlst", "first launch", "PubMLST terms of use",
          "since 2025 PubMLST treats redistribution/repackaging of downloaded data as "
          "restricted use"),
    Route("card", "first launch", "CARD terms of use (academic/non-commercial)",
          "no redistribution grant; commercial use needs a McMaster licence"),
    Route("vfdb", "first launch", "VFDB (no redistribution licence stated)",
          "upstream Hydra classes it as academic use"),
    Route("argannot", "first launch", "ARG-ANNOT (no redistribution licence stated)",
          "upstream Hydra classes it as academic use"),
    Route("megares", "first launch", "MEGARes (no redistribution licence stated)",
          "upstream Hydra classes it as academic use"),
    Route("ecoli_vf", "first launch", "E. coli VF (no explicit data licence)",
          "redistribution not clearly granted"),
    Route("ecoh", "first launch", "EcOH (no explicit data licence)",
          "redistribution not clearly granted"),
)

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


def status(store: DatabaseStore) -> list[dict]:
    rows = []
    installed = store.installed()
    for route in ROUTES:
        entry = installed.get(route.name, {})
        rows.append({
            "name": route.name, "route": route.route, "licence": route.licence,
            "installed": store.is_installed(route.name),
            "version": entry.get("version", ""),
            "sequences": entry.get("sequences", entry.get("schemes", "")),
        })
    return rows


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
    """Download and import *names* in order. Returns name -> error for failures."""
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
            LOG.info("installed %s in %.0fs", name, time.time() - started)
        except Exception as exc:  # noqa: BLE001 - one source must not sink the rest
            errors[name] = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            LOG.error("could not install %s: %s", name, errors[name])
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
    install(store, list(names), stop_on_error=True)

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
    write_notice(db_root, kleborate_source=kleborate)
    return db_root


def write_notice(db_root: Path, kleborate_source: str = "") -> None:
    lines = [
        "Hydra-win reference databases",
        "=============================",
        "",
        "Each database keeps its own licence. Databases marked 'bundled' were built",
        "from the upstream source by the Hydra-win release workflow and are",
        "redistributed under that source's licence; databases marked 'first launch'",
        "are not redistributed and are downloaded from their source on your computer.",
        "",
    ]
    for route in ROUTES:
        spec = DATABASES.get(route.name)
        lines.append(f"{route.name:14s} {route.route:13s} {route.licence}")
        lines.append(f"{'':14s} source:   {source_url(route.name)}")
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
    (Path(db_root) / "DATABASES.txt").write_text("\n".join(lines), encoding="utf-8")


def require_core(store: DatabaseStore) -> None:
    if not store.is_installed("protein") or not store.is_installed("ncbi"):
        raise HydraError(
            f"the bundled databases are missing from {store.root}; re-extract the "
            "Hydra-win zip (the 'db' folder must sit next to Hydra-win.exe)")
