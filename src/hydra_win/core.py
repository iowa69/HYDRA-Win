"""The analysis both front ends share: inputs -> upstream pipeline -> workbooks.

The GUI and ``HYDRA-Win.exe --cli`` call :func:`analyse` with the same
arguments; neither has any analysis logic of its own.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from hydra_amr.config import Config, Thresholds
from hydra_amr.db.manager import DatabaseStore
from hydra_amr.db.registry import DATABASES
from hydra_amr.pipeline import Pipeline, RunOptions
from hydra_amr.records import SampleResult
from hydra_amr.utils import HydraError, cpu_count

from . import (APP_NAME, UPSTREAM_COMMIT, UPSTREAM_URL, __version__, databases, excel, mashlite,
               netfetch, runtime, winsafe)

LOG = logging.getLogger("hydra")

FASTA_SUFFIXES = (".fasta", ".fa", ".fna", ".fas")
COMPRESSED = (".gz",)
FASTQ_SUFFIXES = (".fastq", ".fq")
READ_COMPRESSED = (".gz", ".bz2", ".xz", ".zst")

#: progress(fraction or None for "busy", message)
ProgressFn = Callable[[float | None, str], None]

SPECIES_NOTE = ("Species: Mash distance to the Kleborate species sketches (as upstream Hydra), "
                f"computed by {APP_NAME}'s built-in re-implementation of 'mash dist' because "
                "Mash has no Windows build; the sketches cover Enterobacterales, other genera "
                "are named from their MLST scheme.")
READS_NOTE = (f"{APP_NAME} analyses assemblies (FASTA) only: reads (FASTQ) and "
              "heteroresistance analysis are not part of the Windows version.")


# ------------------------------------------------------------------- inputs
def _strip(name: str, suffixes: Sequence[str]) -> str:
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_fasta_name(path: Path | str) -> bool:
    name = _strip(Path(path).name.lower(), COMPRESSED)
    return name.endswith(FASTA_SUFFIXES)


def is_fastq_name(path: Path | str) -> bool:
    name = _strip(Path(path).name.lower(), READ_COMPRESSED)
    return name.endswith(FASTQ_SUFFIXES)


@dataclass
class Intake:
    """What a set of dropped/selected paths contains."""

    assemblies: list[Path] = field(default_factory=list)
    #: FASTQ read files: never analysed, reported back to the user.
    fastq: list[Path] = field(default_factory=list)
    #: Files named explicitly that are neither FASTA nor FASTQ. Other files
    #: inside a dropped folder are ignored without comment.
    other: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)

    def rejection_message(self) -> str:
        """One sentence (or two) about what was not added, or ''."""
        parts = []
        n = len(self.fastq)
        if n:
            parts.append(f"{n} FASTQ read file{'s were' if n != 1 else ' was'} not added. "
                         f"{APP_NAME} analyses assembled genomes (FASTA) only; reads are not "
                         "analysed by the Windows version. Assemble the reads first, or use "
                         "upstream Hydra on Linux or macOS for read analysis.")
        n = len(self.other)
        if n:
            parts.append(f"{n} other file{'s were' if n != 1 else ' was'} not added: not a FASTA "
                         "assembly (.fasta .fa .fna .fas, optionally .gz).")
        n = len(self.missing)
        if n:
            parts.append(f"{n} path{'s' if n != 1 else ''} could not be found.")
        return " ".join(parts)


def scan_inputs(paths: Iterable[Path | str]) -> Intake:
    """Files and folders -> assemblies, plus what was left out (folders recurse)."""
    intake = Intake()
    seen: set[str] = set()

    def add(bucket: list[Path], path: Path) -> None:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            bucket.append(path)

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                if is_fasta_name(child):
                    add(intake.assemblies, child)
                elif is_fastq_name(child):
                    add(intake.fastq, child)
        elif path.is_file():
            if is_fasta_name(path):
                add(intake.assemblies, path)
            elif is_fastq_name(path):
                add(intake.fastq, path)
            else:
                add(intake.other, path)
        else:
            intake.missing.append(path)
    return intake


def expand_inputs(paths: Iterable[Path | str]) -> list[Path]:
    """Files and folders -> assembly files, logging whatever was left out."""
    intake = scan_inputs(paths)
    if intake.fastq:
        LOG.warning("not analysing %d FASTQ read file(s) (%s%s): %s analyses assemblies "
                    "only", len(intake.fastq), ", ".join(p.name for p in intake.fastq[:3]),
                    ", ..." if len(intake.fastq) > 3 else "", APP_NAME)
    for path in intake.other:
        LOG.warning("skipping %s: not a FASTA assembly (.fasta/.fa/.fna/.fas[.gz])", path.name)
    for path in intake.missing:
        LOG.warning("skipping %s: no such file or folder", path)
    return intake.assemblies


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
#: Names already used in the results folder by the run itself.
_TAKEN_BY_RUN = {"cumulative_results.xlsx", "hydra-win.log"}


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


@dataclass(frozen=True)
class Genome:
    """One assembly in a run and the name its folder and workbook get."""

    name: str
    path: Path
    #: The name derived from the file before de-duplication.
    base: str

    @property
    def renamed(self) -> bool:
        return self.name != self.base


def plan_genomes(files: Sequence[Path | str]) -> list[Genome]:
    """Name every assembly; a name already taken gets ``_2``, ``_3`` ...

    Names are compared case-insensitively because Windows folders are.
    """
    planned: list[Genome] = []
    taken: set[str] = set(_TAKEN_BY_RUN)
    for path in files:
        base = genome_name(path)
        name = base
        n = 2
        while name.lower() in taken:
            name = f"{base}_{n}"
            n += 1
        taken.add(name.lower())
        planned.append(Genome(name=name, path=Path(path), base=base))
    return planned


def name_genomes(files: Sequence[Path]) -> dict[str, Path]:
    return {g.name: g.path for g in plan_genomes(files)}


# ----------------------------------------------------------------- settings
class SettingsError(ValueError):
    """A setting the user typed cannot be used; the message says why."""


AUTO_WORDS = ("", "auto", "automatic", "default")
#: Upstream's global nucleotide defaults (hydra_amr.config.Thresholds).
DEFAULT_IDENTITY = Thresholds().min_identity
DEFAULT_COVERAGE = Thresholds().min_coverage
MAX_THREADS = 256


def parse_percent(text, label: str) -> float | None:
    """'' / 'Automatic' -> None, otherwise a number from 0 to 100 (upstream's range)."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        cleaned = str(text).strip().rstrip("%").strip()
        if cleaned.lower() in AUTO_WORDS:
            return None
        try:
            value = float(cleaned.replace(",", "."))
        except ValueError:
            raise SettingsError(f"{label} must be a number from 0 to 100, or Automatic "
                                f"(got {str(text).strip()!r})") from None
    if math.isnan(value) or not 0.0 <= value <= 100.0:
        raise SettingsError(f"{label} must be between 0 and 100% (got {value:g})")
    return value


def parse_threads(text) -> int | None:
    if text is None:
        return None
    cleaned = str(text).strip()
    if cleaned.lower() in AUTO_WORDS:
        return None
    try:
        value = int(cleaned)
    except ValueError:
        raise SettingsError(f"Threads must be a whole number of at least 1, or Automatic "
                            f"(got {cleaned!r})") from None
    if not 1 <= value <= MAX_THREADS:
        raise SettingsError(f"Threads must be between 1 and {MAX_THREADS} (got {value})")
    return value


def _short(db: str) -> str:
    return {"plasmidfinder": "PlasmidFinder", "ecoh": "EcOH", "ncbi": "NCBI",
            "card": "CARD", "vfdb": "VFDB", "resfinder": "ResFinder"}.get(db, db)


def database_defaults(kind: str, dbs: Sequence[str] = databases.SCREEN) -> list[tuple[str, float]]:
    """Databases whose own cut-off replaces the global one under Automatic."""
    default = DEFAULT_IDENTITY if kind == "identity" else DEFAULT_COVERAGE
    out = []
    for name in dbs:
        spec = DATABASES.get(name)
        value = getattr(spec, f"default_{kind}", None) if spec is not None else None
        if value is not None and float(value) != default:
            out.append((_short(name), float(value)))
    return out


def automatic_text(kind: str, dbs: Sequence[str] = databases.SCREEN) -> str:
    """What Automatic means for 'identity' or 'coverage', in upstream's terms."""
    default = DEFAULT_IDENTITY if kind == "identity" else DEFAULT_COVERAGE
    special = database_defaults(kind, dbs)
    text = f"{default:g}%"
    if special:
        text += " (" + ", ".join(f"{name} {value:g}%" for name, value in special) + ")"
    return text


def explain_automatic() -> str:
    """The window's explanation of Automatic, built from upstream's own values."""
    t = Thresholds()
    stricter = {}
    for kind in ("identity", "coverage"):
        for name, value in database_defaults(kind):
            stricter.setdefault(name, []).append(f"{value:g}% {kind}")
    special = "; ".join(f"{name} {' and '.join(parts)}" for name, parts in stricter.items())
    return (f"Automatic uses upstream Hydra's own thresholds: a gene hit must reach "
            f"{t.min_identity:g}% identity over {t.min_coverage:g}% of the reference gene, "
            f"except where a database sets a stricter default ({special}). A value you enter "
            "replaces these for every nucleotide database, exactly like upstream's "
            "--min-identity / --min-coverage. The AMRFinderPlus protein search "
            f"({t.protein_min_identity:g}% / {t.protein_min_coverage:g}%), point mutations "
            "and MLST/typing keep their own rules. Threads change speed, never results.")


@dataclass
class Settings:
    """User-adjustable options; ``None`` means Automatic (upstream's behaviour)."""

    min_identity: float | None = None
    min_coverage: float | None = None
    threads: int | None = None

    @classmethod
    def parse(cls, identity="", coverage="", threads="") -> Settings:
        return cls(min_identity=parse_percent(identity, "Minimum identity"),
                   min_coverage=parse_percent(coverage, "Minimum coverage"),
                   threads=parse_threads(threads))

    @property
    def automatic(self) -> bool:
        return self.min_identity is None and self.min_coverage is None

    def resolved_threads(self) -> int:
        return self.threads or cpu_count()

    def thresholds(self) -> Thresholds:
        """Exactly what upstream's ``--min-identity`` / ``--min-coverage`` build."""
        thresholds = Thresholds()
        if self.min_identity is not None:
            thresholds.set_explicit("min_identity", self.min_identity)
        if self.min_coverage is not None:
            thresholds.set_explicit("min_coverage", self.min_coverage)
        try:
            thresholds.validate()
        except HydraError as exc:
            raise SettingsError(str(exc)) from None
        return thresholds

    def summary(self) -> str:
        def show(value, unit="%"):
            return "Automatic" if value is None else f"{value:g}{unit}"
        threads = (f"Automatic ({cpu_count()})" if self.threads is None else str(self.threads))
        return (f"identity {show(self.min_identity)} · coverage {show(self.min_coverage)} · "
                f"threads {threads}")

    def cli_flags(self) -> list[str]:
        """The equivalent upstream ``hydra run`` flags."""
        flags = []
        if self.min_identity is not None:
            flags += ["--min-identity", f"{self.min_identity:g}"]
        if self.min_coverage is not None:
            flags += ["--min-coverage", f"{self.min_coverage:g}"]
        return flags

    def describe(self, dbs: Sequence[str] = databases.SCREEN) -> dict[str, str]:
        """Rows for the workbooks' Summary sheets: what was actually used."""
        def threshold(value, kind):
            if value is None:
                return f"Automatic: {automatic_text(kind, dbs)}"
            return (f"{value:g}% (set by user; applies to every nucleotide database, "
                    f"replacing the database defaults)")
        threads = (f"{cpu_count()} (Automatic: all CPU cores)" if self.threads is None
                   else f"{self.threads} (set by user)")
        flags = " ".join(self.cli_flags()) or "none (upstream defaults)"
        return {"Minimum identity (%)": threshold(self.min_identity, "identity"),
                "Minimum coverage (%)": threshold(self.min_coverage, "coverage"),
                "Threads": threads,
                "Equivalent upstream flags": flags}


# ----------------------------------------------------------------- progress
class _BlastProgress:
    """Turns the stream of BLAST calls into a progress fraction."""

    def __init__(self, expected: int, progress: Callable[[float, str], None] | None,
                 start: float, stop: float):
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
class GenomeEvent:
    """Per-genome news for the caller: running (with progress), done or failed."""

    genome: Genome
    status: str
    fraction: float = 0.0
    result: SampleResult | None = None
    workbook: Path | None = None
    error: str | None = None


GenomeFn = Callable[[GenomeEvent], None]


@dataclass
class AnalysisResult:
    outdir: Path
    results: list[SampleResult]
    workbooks: dict[str, Path]
    cumulative: Path | None
    log_path: Path | None
    databases: list[str]
    missing_databases: list[str] = field(default_factory=list)
    genomes: list[Genome] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)
    #: database -> what this run could not do without it (never a negative result).
    missing_analyses: dict[str, str] = field(default_factory=dict)


def ensure_databases(progress: ProgressFn | None = None, offline: bool = False) -> dict[str, str]:
    """Download whatever first-launch database is missing. Returns failures."""
    netfetch.install()
    rt = runtime.prepare()
    store = DatabaseStore(rt.db_root)
    todo = databases.missing(store)
    if todo:
        reused = databases.adopt(store, todo, [r for r in runtime.legacy_db_roots()
                                               if r != rt.db_root])
        todo = [name for name in todo if name not in reused]
    if not todo:
        return {}
    if offline:
        LOG.warning("offline mode: not downloading %s", ", ".join(todo))
        return {name: "offline" for name in todo}
    LOG.info("first launch: downloading %d database(s): %s", len(todo), ", ".join(todo))
    return databases.install(store, todo, progress=progress)


def _run_info(store: DatabaseStore, used: Sequence[str], missing: Sequence[str],
              config: Config, settings: Settings) -> excel.RunInfo:
    installed = store.installed()
    db_text = ", ".join(f"{name} ({installed.get(name, {}).get('version') or 'n/a'})"
                        for name in list(used) + [n for n in ("pubmlst", "lineage", "species", "sccmec")
                                                  if store.is_installed(n)])
    t = config.thresholds
    if settings.automatic:
        nucleotide = (f"nucleotide >= {t.min_identity:g}% identity / {t.min_coverage:g}% "
                      "coverage (per-database defaults apply)")
    else:
        identity = (automatic_text("identity", used) if settings.min_identity is None
                    else f"{t.min_identity:g}% (set by user)")
        coverage = (automatic_text("coverage", used) if settings.min_coverage is None
                    else f"{t.min_coverage:g}% (set by user)")
        nucleotide = (f"nucleotide >= {identity} identity / {coverage} coverage; a value set "
                      "by the user applies to every nucleotide database")
    thresholds = (f"{nucleotide}; protein >= {t.protein_min_identity:g}% / "
                  f"{t.protein_min_coverage:g}%; point mutations >= "
                  f"{t.mutation_min_identity:g}% / {t.mutation_min_coverage:g}%; "
                  "AMRFinderPlus --plus elements on")
    return excel.RunInfo(
        app_version=__version__,
        upstream=f"{UPSTREAM_URL} @ {UPSTREAM_COMMIT[:7]}",
        date=time.strftime("%Y-%m-%d %H:%M:%S"),
        databases=db_text,
        missing_databases=", ".join(missing),
        thresholds=thresholds,
        notes=f"{SPECIES_NOTE} {READS_NOTE}",
        settings=settings.describe(used),
        missing_analyses=databases.missing_analyses(store),
    )


def analyse(inputs: Sequence[Path | str], outdir: Path | str, *, cumulative: bool = False,
            threads: int | None = None, offline: bool = False,
            progress: ProgressFn | None = None, keep_temp: bool = False,
            settings: Settings | None = None, on_genome: GenomeFn | None = None) -> AnalysisResult:
    """Run the full assembly analysis and write the workbooks.

    Genomes are analysed one after another, each with upstream's pipeline, so
    *on_genome* hears about each one as it starts, progresses and finishes, and
    a genome that fails does not take the others with it.
    """
    settings = settings or Settings()
    if threads is not None:
        settings = Settings(settings.min_identity, settings.min_coverage, threads)
    settings.thresholds()  # validate before anything slow happens
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
        return _analyse(rt, inputs, outdir, cumulative, settings, offline, progress, keep_temp,
                        log_path, on_genome)
    finally:
        LOG.removeHandler(file_handler)
        file_handler.close()


def _analyse(rt, inputs, outdir: Path, cumulative: bool, settings: Settings, offline, progress,
             keep_temp, log_path, on_genome) -> AnalysisResult:
    def report(fraction, message):
        if progress:
            progress(fraction, message)

    def notify(event: GenomeEvent) -> None:
        if on_genome:
            on_genome(event)

    LOG.info("%s %s (upstream Hydra %s)", APP_NAME, __version__, UPSTREAM_COMMIT[:7])
    files = expand_inputs(inputs)
    if not files:
        raise HydraError("no FASTA assemblies found among the inputs "
                         "(.fasta, .fa, .fna, .fas, optionally .gz)")
    genomes = plan_genomes(files)
    LOG.info("%d assembl%s: %s", len(genomes), "y" if len(genomes) == 1 else "ies",
             ", ".join(g.name for g in genomes))
    for g in genomes:
        if g.renamed:
            LOG.warning("%s: another assembly is already called %s; this one is written as %s",
                        g.path.name, g.base, g.name)

    failures = ensure_databases(progress=lambda f, m: report(None, m), offline=offline)
    store = DatabaseStore(rt.db_root)
    databases.require_core(store)
    used = [name for name in databases.SCREEN if store.is_installed(name)]
    missing = [name for name in databases.ALL if not store.is_installed(name)]
    if missing:
        LOG.warning("databases not available for this run: %s%s", ", ".join(missing),
                    "" if not failures else " (download failed; they are retried next run)")
        for name, impact in databases.missing_analyses(store).items():
            LOG.warning("not performed (%s missing): %s", name, impact)
    LOG.info("screening against: %s", ", ".join(used))

    config = Config(db_dir=rt.db_root, threads=settings.resolved_threads(), plus=True,
                    auto_organism=True, keep_temp=keep_temp, thresholds=settings.thresholds())
    LOG.info("settings: %s", settings.summary())
    options = RunOptions(databases=used, mlst=True, typing=True, protein=True,
                         point_mutations=True, reads_genes=False, reads_mlst=False,
                         reads_variants=False, heteroresistance=False, assemble_reads=False)
    info = _run_info(store, used, missing, config, settings)
    pipeline = Pipeline(config, store, options)

    run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{threading.get_ident() % 10000}"
    workdir = rt.work_root / run_id
    nucl = [n for n in used if n != "protein"]
    total = len(genomes)
    tail = 0.04 if cumulative and total > 1 else 0.0
    span = (0.98 - 0.02 - tail) / total
    results: list[SampleResult] = []
    workbooks: dict[str, Path] = {}
    failed: dict[str, str] = {}
    try:
        for index, genome in enumerate(genomes):
            start = 0.02 + span * index
            prefix = f"[{index + 1}/{total}] {genome.name}: " if total > 1 else f"{genome.name}: "

            def step(fraction, message, genome=genome, start=start, prefix=prefix):
                report(fraction, prefix + message)
                notify(GenomeEvent(genome, "running", fraction=(fraction - start) / span))

            notify(GenomeEvent(genome, "running"))
            report(start, prefix + "preparing")
            tracker = _BlastProgress(expected=len(nucl) + 6, progress=step, start=start,
                                     stop=start + 0.92 * span)
            winsafe.add_listener(tracker)
            try:
                [result] = pipeline.run({genome.name: genome.path}, {}, workdir / f"g{index}")
                step(start + 0.95 * span, f"writing {genome.name}.xlsx")
                path = outdir / genome.name / f"{genome.name}.xlsx"
                excel.write_genome_workbook(result, path, info, databases=databases.SCREEN)
            except Exception as exc:  # noqa: BLE001 - one bad genome must not stop the rest
                LOG.error("%s failed: %s", genome.name, exc)
                LOG.debug("traceback", exc_info=True)
                failed[genome.name] = str(exc) or type(exc).__name__
                notify(GenomeEvent(genome, "failed", error=failed[genome.name]))
                continue
            finally:
                winsafe.remove_listener(tracker)
                if not keep_temp:
                    shutil.rmtree(workdir / f"g{index}", ignore_errors=True)
            results.append(result)
            workbooks[genome.name] = path
            primary = [h for h in result.hits if h.primary]
            LOG.info("wrote %s", path)
            LOG.info("%s: %s, %s ST%s, %d primary calls", result.sample, result.species.name,
                     result.mlst.scheme, result.mlst.sequence_type, len(primary))
            LOG.info("%s: point mutations / disruptions: %s", result.sample,
                     "; ".join(excel.mutation_lines(result)) or "none")
            notify(GenomeEvent(genome, "done", fraction=1.0, result=result, workbook=path))
    finally:
        if not keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)

    cumulative_path = None
    if cumulative:
        if len(results) > 1:
            report(0.98 - tail / 2, "Writing Cumulative_results.xlsx")
            # Upstream orders samples by name; so does the comparison workbook.
            ordered = sorted(results, key=lambda r: r.sample)
            cumulative_path = excel.write_cumulative_workbook(
                ordered, outdir / "Cumulative_results.xlsx", info)
            LOG.info("wrote %s", cumulative_path)
        else:
            LOG.info("Cumulative_results needs more than one analysed genome; skipped")
    if failed:
        LOG.warning("%d of %d genome(s) failed: %s", len(failed), total, ", ".join(failed))
    report(1.0, "Done" if not failed else f"Done, {len(failed)} of {total} failed")
    return AnalysisResult(outdir=outdir, results=results, workbooks=workbooks,
                          cumulative=cumulative_path, log_path=log_path, databases=used,
                          missing_databases=missing, genomes=genomes, failed=failed,
                          settings=settings, missing_analyses=dict(info.missing_analyses))
