"""Make external commands behave on Windows.

Installed as :data:`hydra_amr.utils.RUN_HOOK`, so every BLAST+ call upstream
makes goes through :func:`hook` first. It does three things:

* runs the tool from a fixed working directory (the HYDRA-Win home, which
  holds both ``db`` and ``work``) and rewrites ``-db``/``-query``/``-out``/``-in``
  to paths relative to it. BLAST+ treats ``-db`` as a space-separated list and,
  on Windows, opens files through the ANSI code page, so a database under
  ``C:\\Users\\Jane Doe\\`` or ``C:\\Users\\Jörg\\`` fails. Relative paths below a
  directory whose own name never reaches BLAST avoid both problems;
* falls back to the 8.3 short path for anything outside that directory;
* hides the console window that would otherwise flash for every subprocess of
  a windowed application, and detaches stdin (a windowed process has none).

The rewriting is pure path arithmetic and is applied on every platform, so the
Linux test suite exercises the same code the Windows build runs.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

#: Arguments whose value is a file path BLAST+ has to open.
PATH_FLAGS = frozenset({"-db", "-query", "-out", "-in", "-subject"})

CREATE_NO_WINDOW = 0x08000000

_anchor: Path | None = None
#: The form of the anchor handed to BLAST+ as its working directory. Identical
#: to the anchor unless that contains spaces or non-ASCII characters, in which
#: case it is the 8.3 short form: makeblastdb builds absolute paths from its
#: working directory internally and fails ("Database memory map file error")
#: on a directory with a space in it even when every argument is relative.
_anchor_cwd: Path | None = None
_listeners: list[Callable[[list[str]], None]] = []
_lock = threading.Lock()


def set_anchor(path: Path | str | None, cwd: Path | str | None = None) -> None:
    """Directory external tools run from; paths below it are passed relatively.

    *cwd* is the spelling of the same directory to run from (its short form
    when *path* is not ASCII); it defaults to *path*.
    """
    global _anchor, _anchor_cwd
    _anchor = Path(os.path.abspath(path)) if path else None
    _anchor_cwd = Path(cwd) if cwd else _anchor


def anchor() -> Path | None:
    return _anchor


def blast_alias(path: Path | str) -> Path | None:
    """A spelling of *path* BLAST+ can use as a working directory, or None."""
    text = str(path)
    if is_safe(text):
        return Path(text)
    short = short_path(Path(text))
    if short and is_safe(short):
        return Path(short)
    return None


def add_listener(callback: Callable[[list[str]], None]) -> None:
    """Call *callback(cmd)* before each external command (used for progress)."""
    with _lock:
        _listeners.append(callback)


def remove_listener(callback: Callable[[list[str]], None]) -> None:
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


def is_safe(text: str) -> bool:
    """True when BLAST+ can take *text* as a path on any platform."""
    return text.isascii() and " " not in text and '"' not in text


def short_path(path: Path) -> str | None:
    """Windows 8.3 short form of *path* (or of its parent, for a new file)."""
    if os.name != "nt":
        return None
    import ctypes  # noqa: PLC0415 - Windows only
    from ctypes import wintypes  # noqa: PLC0415

    get_short = ctypes.windll.kernel32.GetShortPathNameW
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD

    def short(target: Path) -> str | None:
        buffer = ctypes.create_unicode_buffer(32768)
        if get_short(str(target), buffer, len(buffer)):
            return buffer.value
        return None

    if path.exists():
        return short(path)
    parent = short(path.parent) if path.parent.exists() else None
    return str(Path(parent) / path.name) if parent else None


def safe_path(value: str, *, is_db: bool = False, base: Path | None = None) -> str:
    """Rewrite one path argument into a form BLAST+ will parse."""
    base = base if base is not None else _anchor
    path = Path(os.path.abspath(value))
    if base is not None:
        try:
            relative = os.path.relpath(path, base)
        except ValueError:  # different drive on Windows
            relative = None
        if relative is not None and not relative.startswith(".."):
            if is_safe(relative):
                return relative
    if base is None and is_safe(value):
        return value
    absolute = str(path)
    if is_safe(absolute):
        return absolute
    short = short_path(path)
    if short and is_safe(short):
        return short
    if is_db and " " in absolute:
        # Last resort, the quoting BLAST+ documents for -db with spaces.
        return f'"{absolute}"'
    return absolute


def rewrite(cmd: list[str], base: Path | None = None) -> list[str]:
    """Return *cmd* with every path argument made safe for BLAST+."""
    out = list(cmd)
    for index in range(len(cmd) - 1):
        flag = cmd[index]
        if flag in PATH_FLAGS:
            out[index + 1] = safe_path(cmd[index + 1], is_db=(flag == "-db"), base=base)
    return out


def hook(cmd: list[str], has_input: bool) -> tuple[list[str], dict]:
    """The :data:`hydra_amr.utils.RUN_HOOK` HYDRA-Win installs."""
    with _lock:
        listeners = list(_listeners)
    for callback in listeners:
        try:
            callback(cmd)
        except Exception:  # noqa: BLE001 - progress must never break a run
            pass
    kwargs: dict = {}
    if cmd and Path(cmd[0]).stem.lower() == "makeblastdb" and "-blastdb_version" not in cmd:
        # Version 4 databases carry no LMDB index. On Windows an LMDB file is
        # allocated at the full map size (1 GB or more, per index file), which
        # turns a 150 MB database into tens of GB on disk; Hydra never looks
        # sequences up by accession, which is all the LMDB index adds.
        cmd = [*cmd, "-blastdb_version", "4"]
    if _anchor is not None:
        cmd = rewrite(cmd)
        kwargs["cwd"] = str(_anchor_cwd or _anchor)
    if not has_input:
        kwargs["stdin"] = subprocess.DEVNULL
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return cmd, kwargs


def install() -> None:
    """Route every upstream subprocess through :func:`hook`."""
    from hydra_amr import utils  # noqa: PLC0415

    utils.RUN_HOOK = hook
