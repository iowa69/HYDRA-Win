"""The analysis both front ends share: inputs -> upstream pipeline -> workbooks.

The GUI and ``Hydra-win.exe --cli`` call :func:`analyse` with the same
arguments; neither has any analysis logic of its own.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from hydra_amr.config import Config
from hydra_amr.db.manager import DatabaseStore
from hydra_amr.pipeline import Pipeline, RunOptions
from hydra_amr.records import SampleResult
from hydra_amr.utils import HydraError, cpu_count

from . import (UPSTREAM_COMMIT, UPSTREAM_URL, __version__, databases, excel, mashlite, runtime,
               winsafe)

LOG = logging.getLogger("hydra")

FASTA_SUFFIXES = (".fasta", ".fa", ".fna", ".fas")
COMPRESSED = (".gz",)

#: progress(fraction or None for "busy", message)
ProgressFn = Callable[[float | None, str], None]

SPECIES_NOTE = ("Species: Mash distance to the Kleborate species sketches (as upstream Hydra), "
                "computed by Hydra-win's built-in re-implementation of 'mash dist' because Mash "
                "has no Windows build; the sketches cover Enterobacterales, other genera are "
                "named from their MLST scheme.")


# ------------------------------------------------------------------- inputs
def is_fasta_name(path: Path | str) -> bool:
    name = Path(path).name.lower()
    for suffix in COMPRESSED:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.endswith(FASTA_SUFFIXES)


def expand_inputs(paths: Iterable[Path | str]) -> list[Path]:
    """Files and folders -> assembly files (folders are searched recursively)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            out.append(path)

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and is_fasta_name(child):
                    add(child)
        elif path.is_file():
            if is_fasta_name(path):
                add(path)
            else:
                LOG.warning("skipping %s: not a FASTA assembly (.fasta/.fa/.fna/.fas[.gz])",
                            path.name)
        else:
            LOG.warning("skipping %s: no such file or folder", path)
    return out


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def genome_name(path: Path | str) -> str:
    """A file-system-safe genome name from an assembly file name."""
    name = Path(path).name
    for suffix in COMPRESSED:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    for suffix in FASTA_SUFFIXES:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = "genome"
    if name.upper().split(".")[0] in _RESERVED:
        name = f"_{name}"
    return name[:100]


def name_genomes(files: Sequence[Path]) -> dict[str, Path]:
    named: dict[str, Path] = {}
    taken: set[str] = set()
    for path in files:
        base = genome_name(path)
        name = base
        n = 2
        while name.lower() in taken:
            name = f"{base}_{n}"
            n += 1
        taken.add(name.lower())
        named[name] = Path(path)
    return named


# ----------------------------------------------------------------- progress
class _BlastProgress:
    """Turns the stream of BLAST calls into a progress fraction."""

    def __init__(self, expected: int, progress: ProgressFn | None, start: float, stop: float):
        self.expected = max(1, expected)
        self.done = 0
        self.progress = progress
        self.start = start
        self.stop = stop

    def __call__(self, cmd: list[str]) -> None:
        program = Path(cmd[0]).stem if cmd else ""
        if program not in ("blastn", "blastx", "tblastn", "blastp"):
            return
        target = ""
        if "-db" in cmd:
            db = Path(cmd[cmd.index("-db") + 1].strip('"'))
            target = db.parent.name if db.parent.name not in ("blast", "") else db.parent.parent.name
            if db.parent.name == "dna":
                target = f"{db.stem.replace('_', ' ')} mutation reference"
        fraction = self.start + (self.stop - self.start) * min(1.0, self.done / self.expected)
        self.done += 1
        if self.progress:
            self.progress(fraction, f"Searching {target or 'reference'} ({program})")


# -------------------------------------------------------------- the analysis
@dataclass
class AnalysisResult:
    outdir: Path
    results: list[SampleResult]
    workbooks: dict[str, Path]
    cumulative: Path | None
    log_path: Path | None
    databases: list[str]
    missing_databases: list[str] = field(default_factory=list)


def ensure_databases(progress: ProgressFn | None = None, offline: bool = False) -> dict[str, str]:
    """Download whatever first-launch database is missing. Returns failures."""
    rt = runtime.prepare()
    store = DatabaseStore(rt.db_root)
    todo = databases.missing(store)
    if not todo:
        return {}
    if offline:
        LOG.warning("offline mode: not downloading %s", ", ".join(todo))
        return {name: "offline" for name in todo}
    LOG.info("first launch: downloading %d database(s): %s", len(todo), ", ".join(todo))
    return databases.install(store, todo, progress=progress)


def _run_info(store: DatabaseStore, used: Sequence[str], missing: Sequence[str],
              config: Config) -> excel.RunInfo:
    installed = store.installed()
    db_text = ", ".join(f"{name} ({installed.get(name, {}).get('version') or 'n/a'})"
                        for name in list(used) + [n for n in ("pubmlst", "lineage", "species", "sccmec")
                                                  if store.is_installed(n)])
    t = config.thresholds
    thresholds = (f"nucleotide >= {t.min_identity:g}% identity / {t.min_coverage:g}% coverage "
                  f"(per-database defaults apply); protein >= {t.protein_min_identity:g}% / "
                  f"{t.protein_min_coverage:g}%; AMRFinderPlus --plus elements on")
    return excel.RunInfo(
        app_version=__version__,
        upstream=f"{UPSTREAM_URL} @ {UPSTREAM_COMMIT[:7]}",
        date=time.strftime("%Y-%m-%d %H:%M:%S"),
        databases=db_text,
        missing_databases=", ".join(missing),
        thresholds=thresholds,
        notes=SPECIES_NOTE + " Reads/heteroresistance analysis is not part of Hydra-win.",
    )


def analyse(inputs: Sequence[Path | str], outdir: Path | str, *, cumulative: bool = False,
            threads: int | None = None, offline: bool = False,
            progress: ProgressFn | None = None, keep_temp: bool = False) -> AnalysisResult:
    """Run the full assembly analysis and write the workbooks."""
    rt = runtime.prepare()
    mashlite.install()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "hydra-win.log"
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s",
                                                "%Y-%m-%d %H:%M:%S"))
    file_handler.setLevel(logging.INFO)
    LOG.addHandler(file_handler)
    try:
        return _analyse(rt, inputs, outdir, cumulative, threads, offline, progress, keep_temp,
                        log_path)
    finally:
        LOG.removeHandler(file_handler)
        file_handler.close()


def _analyse(rt, inputs, outdir: Path, cumulative: bool, threads, offline, progress,
             keep_temp, log_path) -> AnalysisResult:
    def report(fraction, message):
        if progress:
            progress(fraction, message)

    LOG.info("Hydra-win %s (upstream Hydra %s)", __version__, UPSTREAM_COMMIT[:7])
    files = expand_inputs(inputs)
    if not files:
        raise HydraError("no FASTA assemblies found among the inputs "
                         "(.fasta, .fa, .fna, .fas, optionally .gz)")
    assemblies = name_genomes(files)
    LOG.info("%d assembl%s: %s", len(assemblies), "y" if len(assemblies) == 1 else "ies",
             ", ".join(assemblies))

    failures = ensure_databases(progress=lambda f, m: report(None, m), offline=offline)
    store = DatabaseStore(rt.db_root)
    databases.require_core(store)
    used = [name for name in databases.SCREEN if store.is_installed(name)]
    missing = [name for name in databases.ALL if not store.is_installed(name)]
    if missing:
        LOG.warning("databases not available for this run: %s%s", ", ".join(missing),
                    "" if not failures else " (download failed; they are retried next run)")
    LOG.info("screening against: %s", ", ".join(used))

    n_threads = threads or cpu_count()
    config = Config(db_dir=rt.db_root, threads=n_threads, plus=True, auto_organism=True,
                    keep_temp=keep_temp)
    options = RunOptions(databases=used, mlst=True, typing=True, protein=True,
                         point_mutations=True, reads_genes=False, reads_mlst=False,
                         reads_variants=False, heteroresistance=False, assemble_reads=False)

    workdir = rt.work_root / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{threading.get_ident() % 10000}"
    nucl = [n for n in used if n != "protein"]
    tracker = _BlastProgress(expected=len(nucl) + 6, progress=progress, start=0.03, stop=0.9)
    winsafe.add_listener(tracker)
    report(0.02, f"Preparing {len(assemblies)} assembl{'y' if len(assemblies) == 1 else 'ies'}")
    try:
        results = Pipeline(config, store, options).run(assemblies, {}, workdir)
    finally:
        winsafe.remove_listener(tracker)
        if not keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)


    info = _run_info(store, used, missing, config)
    workbooks: dict[str, Path] = {}
    total = len(results) + (1 if cumulative and len(results) > 1 else 0)
    for index, result in enumerate(results):
        report(0.9 + 0.1 * index / max(1, total), f"Writing {result.sample}.xlsx")
        path = outdir / result.sample / f"{result.sample}.xlsx"
        excel.write_genome_workbook(result, path, info, databases=databases.SCREEN)
        workbooks[result.sample] = path
        LOG.info("wrote %s", path)

    cumulative_path = None
    if cumulative:
        if len(results) > 1:
            report(0.9 + 0.1 * len(results) / max(1, total), "Writing Cumulative_results.xlsx")
            cumulative_path = excel.write_cumulative_workbook(
                results, outdir / "Cumulative_results.xlsx", info)
            LOG.info("wrote %s", cumulative_path)
        else:
            LOG.info("Cumulative_results needs more than one genome; skipped")
    report(1.0, "Done")
    for result in results:
        primary = [h for h in result.hits if h.primary]
        LOG.info("%s: %s, %s ST%s, %d primary calls", result.sample, result.species.name,
                 result.mlst.scheme, result.mlst.sequence_type, len(primary))
    return AnalysisResult(outdir=outdir, results=results, workbooks=workbooks,
                          cumulative=cumulative_path, log_path=log_path, databases=used,
                          missing_databases=missing)
