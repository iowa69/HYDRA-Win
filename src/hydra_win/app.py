"""Program entry point for ``HYDRA-Win.exe`` and ``python -m hydra_win``."""

from __future__ import annotations

import multiprocessing
import sys

#: Switches that mean "no window".
HEADLESS = ("--cli", "--build-db", "--fetch-db", "--db-status", "--version", "--help", "-h")


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg in HEADLESS or arg.startswith("--build-db=") for arg in argv):
        from .cli import main as cli_main  # noqa: PLC0415

        return cli_main(argv)
    from .gui import main as gui_main  # noqa: PLC0415

    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
