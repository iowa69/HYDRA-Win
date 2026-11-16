"""Headless entry: ``Hydra-win.exe --cli <fasta...> --out DIR [--cumulative]``.

It calls exactly the same :func:`hydra_win.core.analyse` as the window does.
Maintenance switches used by the release workflow live here too.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import UPSTREAM_COMMIT, __version__

LOG = logging.getLogger("hydra")


def attach_console() -> None:
    """Give a windowed (no-console) executable somewhere to print.

    When the parent redirected our output (CI, scripts) the inherited handles
    already work. When started from cmd.exe or PowerShell they do not, so
    attach to the parent's console instead.
    """
    if os.name != "nt" or (sys.stdout is not None and sys.stderr is not None):
        return
    try:
        import ctypes  # noqa: PLC0415

        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
            sys.stderr = sys.stdout
    except Exception:  # noqa: BLE001 - output is a convenience, never a requirement
        pass


def setup_logging(verbose: bool, extra_log: Path | None) -> None:
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.propagate = False
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%H:%M:%S")
    LOG.handlers[:] = []
    if sys.stderr is not None:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        # Download progress is chatty at DEBUG; keep it out of the console.
        handler.addFilter(lambda r: r.levelno > logging.DEBUG or not r.getMessage().endswith("%"))
        LOG.addHandler(handler)
    if extra_log is not None:
        extra_log.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(extra_log, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        LOG.addHandler(file_handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Hydra-win.exe --cli",
        description="Hydra-win headless mode: analyse bacterial assemblies and write Excel "
                    "workbooks. Without --cli the window opens.")
    parser.add_argument("--cli", action="store_true", help="run without the window")
    parser.add_argument("inputs", nargs="*", type=Path,
                        help="FASTA assemblies (.fasta .fa .fna .fas, optionally .gz) or folders")
    parser.add_argument("--out", type=Path, help="output folder")
    parser.add_argument("--cumulative", action="store_true",
                        help="also write Cumulative_results.xlsx (more than one genome)")
    parser.add_argument("--threads", type=int, default=None, help="CPU threads (default: all)")
    parser.add_argument("--offline", action="store_true",
                        help="do not download missing first-launch databases")
    parser.add_argument("--keep-temp", action="store_true", help="keep the scratch directory")
    parser.add_argument("--log", type=Path, default=None, help="also log to this file")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    maintenance = parser.add_argument_group("maintenance")
    maintenance.add_argument("--fetch-db", action="store_true",
                             help="download missing first-launch databases and exit")
    maintenance.add_argument("--db-status", nargs="?", const="-", default=None, metavar="FILE",
                             help="write the database status as JSON (to FILE or stdout) "
                                  "and exit")
    maintenance.add_argument("--build-db", type=Path, metavar="DIR",
                             help="build the redistributable (bundled) databases into DIR")
    maintenance.add_argument("--version", action="store_true", help="print the version and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    attach_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose, args.log)

    if args.version:
        print(f"Hydra-win {__version__} (upstream Hydra {UPSTREAM_COMMIT[:7]})")
        return 0

    from hydra_amr.utils import HydraError  # noqa: PLC0415

    from . import core, databases, runtime  # noqa: PLC0415

    try:
        if args.build_db:
            target = Path(os.path.abspath(args.build_db))
            os.environ["HYDRA_WIN_DB"] = str(target)
            runtime.prepare()
            databases.build_bundle(target)
            LOG.info("bundled databases built in %s", target)
            return 0

        rt = runtime.prepare()
        LOG.debug("runtime: %s", rt.describe())
        if args.db_status:
            from hydra_amr.db.manager import DatabaseStore  # noqa: PLC0415

            rows = databases.status(DatabaseStore(rt.db_root))
            text = json.dumps({"version": __version__, "frozen": runtime.is_frozen(),
                               "utf8_mode": bool(sys.flags.utf8_mode),
                               "home": str(rt.home), "blast_cwd": str(rt.blast_cwd),
                               "db_root": str(rt.db_root), "blast_dir": str(rt.blast_dir),
                               "databases": rows}, indent=2)
            if args.db_status == "-":
                print(text)
            else:
                Path(args.db_status).write_text(text, encoding="utf-8")
            return 0
        if args.fetch_db:
            failures = core.ensure_databases(offline=False)
            for name, error in failures.items():
                LOG.error("%s: %s", name, error)
            return 1 if failures else 0

        if not args.inputs:
            parser.error("no inputs: give FASTA files or folders")
        if args.out is None:
            parser.error("--out DIR is required")
        result = core.analyse(args.inputs, args.out, cumulative=args.cumulative,
                              threads=args.threads, offline=args.offline,
                              keep_temp=args.keep_temp)
        for name, path in result.workbooks.items():
            print(f"{name}\t{path}")
        if result.cumulative:
            print(f"Cumulative_results\t{result.cumulative}")
        return 0
    except HydraError as exc:
        LOG.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 130
