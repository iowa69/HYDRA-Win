"""Where things live: the application folder, the database, scratch space, BLAST+.

Layout of an unzipped release::

    Hydra-win/
      Hydra-win.exe
      _internal/          Python runtime (PyInstaller)
      blast/bin/          NCBI BLAST+ executables and DLLs
      db/                 Hydra database (bundled part + first-launch downloads)
      work/               scratch space for runs, emptied after each one

The application folder is the "home" when it is writable, which is the normal
case for a portable app unzipped into Downloads or onto the Desktop. When it is
not (for example under Program Files), the home moves to
``%LOCALAPPDATA%\\Hydra-win`` and the bundled database is copied there once.

Environment overrides, used by tests and CI:
``HYDRA_WIN_HOME`` (home), ``HYDRA_WIN_DB`` (database root),
``HYDRA_WIN_BLAST`` (directory holding blastn/blastx/makeblastdb).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import winsafe

APP_NAME = "Hydra-win"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder holding the executable (frozen) or the repository root (source)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{os.getpid()}"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "hydra-win"


@dataclass
class Runtime:
    home: Path
    db_root: Path
    work_root: Path
    blast_dir: Path | None
    bundled_db: Path | None
    blast_cwd: Path | None = None

    def describe(self) -> str:
        return (f"home={self.home} (BLAST runs from {self.blast_cwd}) db={self.db_root} "
                f"work={self.work_root} blast={self.blast_dir or 'PATH'}")


_current: Runtime | None = None


def _home_candidates() -> list[Path]:
    env = os.environ.get("HYDRA_WIN_HOME")
    if env:
        return [Path(os.path.abspath(env))]
    out = []
    if is_frozen():
        out.append(app_dir())
    out.append(_user_data_dir())
    if os.name == "nt":
        # ASCII-only fallbacks for accounts whose profile path is not ASCII and
        # whose drive has no 8.3 short names.
        out.append(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / APP_NAME)
        out.append(Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / APP_NAME)
    return out


def _resolve_home() -> tuple[Path, Path]:
    """(home, the spelling of home BLAST+ runs from).

    The first writable candidate with a BLAST-safe spelling wins. When none has
    one, the first writable candidate is used as it is.
    """
    writable = [c for c in _home_candidates() if _writable(c / "work")]
    if not writable:
        raise OSError("no writable folder for Hydra-win's databases and scratch files")
    for candidate in writable:
        alias = winsafe.blast_alias(candidate)
        if alias is not None:
            return candidate, alias
    return writable[0], writable[0]


def _find_blast() -> Path | None:
    env = os.environ.get("HYDRA_WIN_BLAST")
    if env:
        return Path(env)
    candidate = app_dir() / "blast" / "bin"
    return candidate if candidate.is_dir() else None


def prepare() -> Runtime:
    """Resolve the layout, put BLAST+ on PATH and install the subprocess hook."""
    global _current
    if _current is not None:
        return _current
    home, blast_cwd = _resolve_home()
    home.mkdir(parents=True, exist_ok=True)

    bundled = app_dir() / "db"
    bundled = bundled if (bundled / "manifest.json").exists() else None
    env_db = os.environ.get("HYDRA_WIN_DB")
    if env_db:
        db_root = Path(os.path.abspath(env_db))
    else:
        db_root = home / "db"
        if bundled is not None and db_root.resolve() != bundled.resolve() \
                and not (db_root / "manifest.json").exists():
            # Home moved off the application folder: seed it with the bundled
            # databases once, so first-launch downloads have somewhere to go.
            shutil.copytree(bundled, db_root, dirs_exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    work_root = home / "work"
    work_root.mkdir(parents=True, exist_ok=True)

    blast_dir = _find_blast()
    if blast_dir is not None:
        os.environ["PATH"] = str(blast_dir) + os.pathsep + os.environ.get("PATH", "")
    # BLAST+ reads configuration from these; a stray one on the user's machine
    # must not redirect database lookups.
    os.environ.pop("BLASTDB", None)
    # makeblastdb maps its LMDB index at a default size of hundreds of GB; on a
    # machine short of address space or commit charge that mapping fails with
    # "Database memory map file error". Hydra's indexes are a few MB at most.
    os.environ.setdefault("BLASTDB_LMDB_MAP_SIZE", "1000000000")
    os.environ["HYDRA_DB"] = str(db_root)

    winsafe.set_anchor(home, blast_cwd)
    winsafe.install()
    _current = Runtime(home=home, db_root=db_root, work_root=work_root,
                       blast_dir=blast_dir, bundled_db=bundled, blast_cwd=blast_cwd)
    return _current


def reset() -> None:
    """Forget the resolved layout (tests)."""
    global _current
    _current = None
    winsafe.set_anchor(None)
