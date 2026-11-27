"""Program entry point for ``HYDRA-Win.exe`` and ``python -m hydra_win``."""

from __future__ import annotations

import multiprocessing
import sys

#: Switches that mean "no window". Every maintenance switch the CLI accepts is
#: here: a windowed executable that opened its window for one of them would
#: leave the user who typed it with no output and nothing done.
HEADLESS = frozenset({"--cli", "--build-db", "--fetch-db", "--import-db", "--db-status",
                      "--version", "--help", "-h"})


def is_headless(argv: list[str]) -> bool:
    """Whether this command line is for the CLI. ``--switch=value`` counts too."""
    return any(arg.split("=", 1)[0] in HEADLESS for arg in argv)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:] if argv is None else argv)
    if is_headless(argv):
        from .cli import main as cli_main  # noqa: PLC0415

        return cli_main(argv)
    from .gui import main as gui_main  # noqa: PLC0415

    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
