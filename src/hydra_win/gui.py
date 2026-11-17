"""The HYDRA-Win window (tkinter/ttk, with tkinterdnd2 for drag-and-drop).

All analysis runs in a worker thread through :func:`hydra_win.core.analyse`,
the same function ``--cli`` uses; the window only collects inputs, shows
progress and opens the results.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from hydra_amr.utils import cpu_count

from . import (APP_NAME, AUTHOR, ORGANISATION, REPO_URL, UPSTREAM_COMMIT, UPSTREAM_URL,
               __version__, core, excel)

LOG = logging.getLogger("hydra")
ASSETS = Path(__file__).resolve().parent / "assets"
APP_ID = "IOWA-BioTech.HYDRA-Win"

try:  # drag-and-drop is a nicety; the window works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001
    DND_FILES = None
    TkinterDnD = None

#: Colours: the logo's navy and cyan, a darker cyan for text on white, greys.
C = {
    "header": "#0b1220", "header_text": "#f8fafc", "header_muted": "#94a3b8",
    "cyan": "#22d3ee", "bg": "#eef2f6", "card": "#ffffff", "soft": "#f6f8fb",
    "border": "#d5dce5", "text": "#111827", "muted": "#5b6b7f",
    "accent": "#0e7490", "accent_active": "#155e75", "accent_pressed": "#164e63",
    "accent_disabled": "#a7cbd4", "select": "#d3eff5", "heading": "#f1f4f8",
    "ok": "#15803d", "fail": "#b91c1c", "queued": "#64748b",
    "warn_bg": "#fff6dc", "warn_border": "#efc04f", "warn_text": "#5c3d00",
    "footer": "#e2e8ef",
}

COLUMNS = (  # id, heading, width (in average characters), anchor, stretch
    ("sample", "Sample (output name)", 21, "w", False),
    ("file", "File", 21, "w", True),
    ("size", "Size", 9, "e", False),
    ("status", "Status", 12, "w", False),
    ("species", "Species", 21, "w", True),
    ("mlst", "MLST", 16, "w", False),
    ("amr", "AMR genes", 13, "center", False),
    ("mutations", "Mutations", 12, "center", False),
)


class _QueueHandler(logging.Handler):
    def __init__(self, events: queue.Queue):
        super().__init__(logging.DEBUG)
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        self._last_detail = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.levelno <= logging.DEBUG:
            # Download progress ("card.tar.bz2: 45%", "pubmlst: 300/1197 files").
            if message.endswith("%") or message.endswith(" files"):
                now = time.monotonic()
                if now - self._last_detail > 0.2:
                    self._last_detail = now
                    self.events.put(("detail", message))
            return
        self.events.put(("log", self.format(record)))


def default_output() -> Path:
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / f"{APP_NAME} results"


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


open_folder = open_path


def human_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1000:
        return f"{n / 1000:.0f} kB"
    return f"{n} B"


def _scale(root: tk.Misc) -> float:
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        return 1.0


def _work_area(root: tk.Misc) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the screen minus the taskbar."""
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def window_rect(root: tk.Misc) -> list[int]:
    """Screen rectangle of the whole window, title bar included where we can."""
    root.update_idletasks()
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            hwnd = wintypes.HWND(int(root.wm_frame(), 16))
            rect = wintypes.RECT()
            # DWMWA_EXTENDED_FRAME_BOUNDS: the visible frame, without the shadow.
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
                return [rect.left, rect.top, rect.right, rect.bottom]
        except Exception:  # noqa: BLE001
            pass
    x, y = root.winfo_rootx(), root.winfo_rooty()
    return [x, y, x + root.winfo_width(), y + root.winfo_height()]


# --------------------------------------------------------------------- theme
def apply_theme(root: tk.Tk) -> dict[str, tkfont.Font]:
    """A restrained ttk theme on 'clam' (pure Tk, nothing extra to package)."""
    style = ttk.Style(root)
    style.theme_use("clam")
    family = "Segoe UI" if os.name == "nt" else tkfont.nametofont("TkDefaultFont").actual("family")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(name).configure(family=family, size=10)
        except tk.TclError:
            pass
    mono = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"
    f = {
        "base": tkfont.nametofont("TkDefaultFont"),
        "small": tkfont.Font(root, family=family, size=9),
        "bold": tkfont.Font(root, family=family, size=10, weight="bold"),
        "head": tkfont.Font(root, family=family, size=9, weight="bold"),
        "h2": tkfont.Font(root, family=family, size=11, weight="bold"),
        "title": tkfont.Font(root, family=family, size=16, weight="bold"),
        "run": tkfont.Font(root, family=family, size=11, weight="bold"),
        "link": tkfont.Font(root, family=family, size=9, underline=True),
        "mono": tkfont.Font(root, family=mono, size=9),
        "placeholder": tkfont.Font(root, family=family, size=11),
    }
    line = f["base"].metrics("linespace")
    root.configure(background=C["bg"])
    style.configure(".", background=C["bg"], foreground=C["text"], bordercolor=C["border"],
                    lightcolor=C["card"], darkcolor=C["card"], troughcolor=C["heading"],
                    focuscolor=C["accent"], selectbackground=C["select"],
                    selectforeground=C["text"], font=f["base"])
    for prefix, colour in (("", C["bg"]), ("Card.", C["card"]), ("Soft.", C["soft"])):
        style.configure(f"{prefix}TFrame", background=colour)
        style.configure(f"{prefix}TLabel", background=colour, foreground=C["text"])
        style.configure(f"Muted.{prefix}TLabel", background=colour, foreground=C["muted"],
                        font=f["small"])
        style.configure(f"Bold.{prefix}TLabel", background=colour, font=f["bold"])
        style.configure(f"{prefix}TCheckbutton", background=colour, foreground=C["text"],
                        indicatorbackground=C["card"], indicatorforeground=C["accent"],
                        upperbordercolor=C["border"], lowerbordercolor=C["border"])
        style.map(f"{prefix}TCheckbutton", background=[("active", colour)],
                  indicatorbackground=[("disabled", C["heading"])],
                  foreground=[("disabled", C["muted"])])
    style.configure("H2.Card.TLabel", background=C["card"], font=f["h2"])
    style.configure("Error.Soft.TLabel", background=C["soft"], foreground=C["fail"],
                    font=f["small"])
    style.configure("Error.Card.TLabel", background=C["card"], foreground=C["fail"],
                    font=f["small"])

    pad_x, pad_y = int(line * 0.7), int(line * 0.2)
    style.configure("TButton", background=C["card"], foreground=C["text"],
                    bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                    padding=(pad_x, pad_y), relief="raised", focusthickness=1)
    style.map("TButton",
              background=[("disabled", C["card"]), ("pressed", "#e2e8f0"), ("active", "#f1f5f9")],
              foreground=[("disabled", "#a3adba")],
              bordercolor=[("focus", C["accent"])])
    style.configure("Accent.TButton", background=C["accent"], foreground="#ffffff",
                    bordercolor=C["accent"], lightcolor=C["accent"], darkcolor=C["accent"],
                    font=f["run"], padding=(int(line * 1.4), int(line * 0.42)))
    style.map("Accent.TButton",
              background=[("disabled", C["accent_disabled"]), ("pressed", C["accent_pressed"]),
                          ("active", C["accent_active"])],
              lightcolor=[("disabled", C["accent_disabled"]), ("pressed", C["accent_pressed"]),
                          ("active", C["accent_active"])],
              darkcolor=[("disabled", C["accent_disabled"]), ("pressed", C["accent_pressed"]),
                         ("active", C["accent_active"])],
              bordercolor=[("disabled", C["accent_disabled"]), ("focus", C["accent_pressed"])],
              foreground=[("disabled", "#f1f7f9")])
    style.configure("Primary.TButton", background=C["accent"], foreground="#ffffff",
                    bordercolor=C["accent"], lightcolor=C["accent"], darkcolor=C["accent"],
                    padding=(int(line * 1.2), pad_y))
    style.map("Primary.TButton",
              background=[("pressed", C["accent_pressed"]), ("active", C["accent_active"])],
              lightcolor=[("pressed", C["accent_pressed"]), ("active", C["accent_active"])],
              darkcolor=[("pressed", C["accent_pressed"]), ("active", C["accent_active"])],
              bordercolor=[("focus", C["accent_pressed"])])
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, fieldbackground=C["card"], foreground=C["text"],
                        bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                        padding=(6, 3), arrowcolor=C["muted"], arrowsize=int(line * 0.6))
        style.map(name, bordercolor=[("focus", C["accent"])],
                  lightcolor=[("focus", C["accent"])],
                  fieldbackground=[("disabled", C["heading"])],
                  foreground=[("disabled", C["muted"])])
    style.configure("Invalid.TSpinbox", bordercolor=C["fail"], lightcolor=C["fail"])
    style.map("Invalid.TSpinbox", bordercolor=[("focus", C["fail"])],
              lightcolor=[("focus", C["fail"])])
    style.configure("Treeview", background=C["card"], fieldbackground=C["card"],
                    foreground=C["text"], bordercolor=C["border"], lightcolor=C["card"],
                    darkcolor=C["card"], rowheight=int(line * 1.6), font=f["base"])
    style.map("Treeview", background=[("selected", C["select"])],
              foreground=[("selected", C["text"])])
    style.configure("Treeview.Heading", background=C["heading"], foreground="#334155",
                    bordercolor=C["border"], lightcolor=C["heading"], darkcolor=C["heading"],
                    relief="flat", font=f["head"], padding=(8, int(line * 0.35)))
    style.map("Treeview.Heading", background=[("active", "#e7ecf2")])
    style.configure("Horizontal.TProgressbar", troughcolor="#e2e8f0", background=C["accent"],
                    bordercolor="#e2e8f0", lightcolor=C["accent"], darkcolor=C["accent"],
                    thickness=max(6, int(line * 0.45)))
    style.configure("Vertical.TScrollbar", background="#cbd5e1", troughcolor=C["card"],
                    bordercolor=C["card"], lightcolor="#cbd5e1", darkcolor="#cbd5e1",
                    arrowcolor=C["muted"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", "#94a3b8")])
    return f


class _Link(tk.Label):
    """A clickable text link."""

    def __init__(self, parent, text, command, *, bg, fg, font):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font, cursor="hand2", bd=0)
        self.bind("<Button-1>", lambda _e: command())


def _card(parent) -> tk.Frame:
    return tk.Frame(parent, bg=C["card"], highlightthickness=1,
                    highlightbackground=C["border"], highlightcolor=C["border"], bd=0)


def _wrap(label: tk.Widget, parent: tk.Widget, margin: int = 0) -> None:
    """Keep a label's text wrapped to its parent's width."""
    parent.bind("<Configure>", lambda e: label.configure(wraplength=max(200, e.width - margin)),
                add="+")


# ----------------------------------------------------------------------- app
class App:
    def __init__(self, root: tk.Tk, check_db: bool = True):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.files: list[Path] = []
        self.busy = False
        self.quiet = False  # smoke test: no modal dialogs
        self.last_output: Path | None = None
        self.dnd_enabled = False
        self.settings = core.Settings()
        self.settings_dialog: SettingsDialog | None = None
        self.db_dialog: DatabasesDialog | None = None
        #: database -> what a run cannot do without it (from the last check).
        self.missing_dbs: dict[str, str] = {}
        self.notice_text = ""
        #: Per-file state from the current/last run, keyed by normalised path.
        self.row_state: dict[str, dict] = {}
        self.iid_by_name: dict[str, str] = {}
        self.images: dict[str, tk.PhotoImage] = {}

        self.fonts = apply_theme(root)
        self.scale = _scale(root)
        root.title(f"{APP_NAME} {__version__}")
        self._set_icon()
        self._place_window()
        self._build()
        handler = _QueueHandler(self.events)
        LOG.addHandler(handler)
        LOG.setLevel(logging.DEBUG)
        LOG.propagate = False
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        if check_db:
            root.after(300, self.check_databases)

    # ------------------------------------------------------------- window
    def _image(self, size: int) -> tk.PhotoImage | None:
        key = f"logo-{size}"
        if key not in self.images:
            path = ASSETS / f"{key}.png"
            if not path.exists():
                return None
            self.images[key] = tk.PhotoImage(master=self.root, file=str(path))
        return self.images[key]

    def _logo(self, target: int) -> tk.PhotoImage | None:
        sizes = (24, 32, 48, 64, 96, 128)
        pick = next((s for s in sizes if s >= target * 0.95), sizes[-1])
        return self._image(pick)

    def _set_icon(self) -> None:
        try:
            if os.name == "nt" and (ASSETS / f"{APP_NAME}.ico").exists():
                self.root.iconbitmap(default=str(ASSETS / f"{APP_NAME}.ico"))
            else:
                icons = [i for i in (self._image(64), self._image(32)) if i is not None]
                if icons:
                    self.root.iconphoto(True, *icons)
        except tk.TclError:
            pass

    def _place_window(self) -> None:
        left, top, right, bottom = _work_area(self.root)
        s = self.scale
        avail_w, avail_h = right - left, bottom - top
        title_bar = int(34 * s)
        w = min(int(1180 * s), avail_w - int(24 * s))
        h = min(int(760 * s), avail_h - title_bar - int(12 * s))
        x = left + max(0, (avail_w - w) // 2)
        y = top + max(0, (avail_h - h - title_bar) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(int(900 * s), w), min(int(560 * s), h))

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        f = self.fonts
        line = f["base"].metrics("linespace")
        gap = int(line * 0.7)
        self._build_header()

        body = ttk.Frame(self.root, padding=(gap + 4, gap, gap + 4, gap))
        body.pack(fill="both", expand=True)
        # Packed bottom-up so the genome table, packed last, is what shrinks
        # on a small screen; the log and the Run button always stay visible.
        self._build_log(body)
        self._build_run_bar(body, gap)
        self._build_options(body, gap)
        self._build_genomes(body, gap)

        if TkinterDnD is not None and DND_FILES is not None:
            try:
                for widget in (self.root, self.tree, self.placeholder):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                self.dnd_enabled = True
            except Exception:  # noqa: BLE001 - tkdnd failed to load
                self.dnd_enabled = False
        if not self.dnd_enabled:
            self.placeholder.configure(text="Click Add files… or Add folder… to choose FASTA "
                                            "assemblies\n(drag-and-drop is unavailable on this "
                                            "system)")
        self._show_settings()
        self._refresh()

    def _build_header(self) -> None:
        f = self.fonts
        header = tk.Frame(self.root, bg=C["header"])
        header.pack(side="top", fill="x")
        inner = tk.Frame(header, bg=C["header"])
        inner.pack(fill="x", padx=int(18 * self.scale), pady=int(7 * self.scale))
        logo = self._logo(int(40 * self.scale))
        if logo is not None:
            tk.Label(inner, image=logo, bg=C["header"], bd=0).pack(side="left")
        titles = tk.Frame(inner, bg=C["header"])
        titles.pack(side="left", padx=(int(12 * self.scale), 0))
        tk.Label(titles, text=APP_NAME, font=f["title"], fg=C["header_text"],
                 bg=C["header"]).pack(anchor="w")
        tk.Label(titles, text="AMR genes, point mutations, virulence, plasmids, MLST and typing "
                              "from bacterial genome assemblies",
                 font=f["small"], fg=C["header_muted"], bg=C["header"]).pack(anchor="w")
        right = tk.Frame(inner, bg=C["header"])
        right.pack(side="right", anchor="e")
        tk.Label(right, text=f"{AUTHOR} · {ORGANISATION}", font=f["bold"],
                 fg=C["header_text"], bg=C["header"]).pack(anchor="e")
        links = tk.Frame(right, bg=C["header"])
        links.pack(anchor="e", pady=(2, 0))
        tk.Label(links, text=f"Version {__version__}", font=f["small"], fg=C["header_muted"],
                 bg=C["header"]).pack(side="left")
        for text, command in (("About", self.show_about),
                              ("GitHub", lambda: webbrowser.open(REPO_URL))):
            tk.Label(links, text="  ·  ", font=f["small"], fg=C["header_muted"],
                     bg=C["header"]).pack(side="left")
            _Link(links, text, command, bg=C["header"], fg=C["cyan"],
                  font=f["link"]).pack(side="left")
        tk.Frame(self.root, bg=C["cyan"], height=max(2, int(2 * self.scale))).pack(
            side="top", fill="x")

    def _step(self, parent, number: int, text: str, bg: str = C["card"]) -> tk.Frame:
        row = tk.Frame(parent, bg=bg)
        size = int(self.fonts["head"].metrics("linespace") * 1.45)
        badge = tk.Canvas(row, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        badge.create_oval(1, 1, size - 1, size - 1, fill=C["accent"], outline=C["accent"])
        badge.create_text(size / 2, size / 2, text=str(number), fill="#ffffff",
                          font=self.fonts["head"])
        badge.pack(side="left")
        tk.Label(row, text=text, font=self.fonts["h2"], fg=C["text"], bg=bg).pack(
            side="left", padx=(int(8 * self.scale), 0))
        return row

    def _build_genomes(self, body, gap: int) -> None:
        f = self.fonts
        card = _card(body)
        card.pack(side="top", fill="both", expand=True, pady=(0, gap))
        inner = ttk.Frame(card, style="Card.TFrame",
                          padding=(gap + 2, int(gap * 0.8), gap + 2, int(gap * 0.7)))
        inner.pack(fill="both", expand=True)

        head = tk.Frame(inner, bg=C["card"])
        head.pack(side="top", fill="x")
        self._step(head, 1, "Add genomes").pack(side="left")
        self.clear_button = ttk.Button(head, text="Clear", command=self.clear)
        self.remove_button = ttk.Button(head, text="Remove selected", command=self.remove_selected)
        self.folder_button = ttk.Button(head, text="Add folder…", command=self.select_folder)
        self.files_button = ttk.Button(head, text="Add files…", command=self.select_files)
        for button in (self.clear_button, self.remove_button, self.folder_button,
                       self.files_button):
            button.pack(side="right", padx=(int(6 * self.scale), 0))

        self.hint = tk.Label(
            inner, bg=C["card"], fg="#334155", font=f["small"], anchor="w", justify="left",
            text=("Assemblies only: FASTA files (.fasta .fa .fna .fas, optionally .gz), one "
                  f"genome per file. Reads (FASTQ) are not analysed by {APP_NAME}."))
        self.hint.pack(side="top", fill="x", pady=(int(gap * 0.45), int(gap * 0.55)))
        self.hint.bind("<Configure>", lambda e: self.hint.configure(wraplength=max(200, e.width)))

        # Notice about files that were not added (FASTQ and others); hidden until needed.
        self.notice = tk.Frame(inner, bg=C["warn_bg"], highlightthickness=1,
                               highlightbackground=C["warn_border"])
        self.notice_label = tk.Label(self.notice, text="", bg=C["warn_bg"], fg=C["warn_text"],
                                     font=f["base"], justify="left", anchor="w")
        self.notice_label.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=5)
        _Link(self.notice, "Dismiss", self.dismiss_notice, bg=C["warn_bg"], fg=C["accent"],
              font=f["link"]).pack(side="right", anchor="n", padx=(6, 10), pady=6)
        self.notice.bind("<Configure>", lambda e: self.notice_label.configure(
            wraplength=max(200, e.width - int(90 * self.scale))))

        bottom = tk.Frame(inner, bg=C["card"])
        bottom.pack(side="bottom", fill="x", pady=(int(gap * 0.5), 0))
        self.count_label = ttk.Label(bottom, text="", style="Muted.Card.TLabel")
        self.count_label.pack(side="left")
        self.rename_label = tk.Label(bottom, text="", font=f["small"], fg=C["warn_text"],
                                     bg=C["card"], anchor="w", justify="left")
        self.rename_label.pack(side="left", padx=(int(14 * self.scale), 0), fill="x",
                               expand=True)

        self.table = tk.Frame(inner, bg=C["border"], bd=0, highlightthickness=0)
        self.table.pack(side="top", fill="both", expand=True)
        holder = tk.Frame(self.table, bg=C["card"])
        holder.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(holder, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="extended", height=3)
        char = f["base"].measure("0")
        for cid, heading, width, anchor, stretch in COLUMNS:
            self.tree.heading(cid, text=heading, anchor="w" if anchor == "w" else anchor)
            self.tree.column(cid, width=int(width * char), minwidth=int(5 * char),
                             anchor=anchor, stretch=stretch)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("renamed", background=C["warn_bg"])
        self.tree.tag_configure("queued", foreground=C["queued"])
        self.tree.tag_configure("running", foreground=C["accent"])
        self.tree.tag_configure("done", foreground=C["text"])
        self.tree.tag_configure("failed", foreground=C["fail"])
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons())

        self.placeholder = tk.Label(
            self.tree, bg=C["card"], fg=C["muted"], font=f["placeholder"], justify="center",
            text="Drop FASTA assemblies or folders here\nor click Add files… / Add folder…")

    def _build_options(self, body, gap: int) -> None:
        card = _card(body)
        card.pack(side="bottom", fill="x", pady=(0, gap))
        inner = ttk.Frame(card, style="Card.TFrame",
                          padding=(gap + 2, int(gap * 0.8), gap + 2, int(gap * 0.8)))
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(1, weight=1)

        head = tk.Frame(inner, bg=C["card"])
        head.grid(row=0, column=0, columnspan=3, sticky="ew")
        self._step(head, 2, "Choose output and options").pack(side="left")
        self.settings_button = ttk.Button(head, text="Settings…", command=self.open_settings)
        self.settings_button.pack(side="right")
        self.settings_summary = ttk.Label(head, text="", style="Muted.Card.TLabel")
        self.settings_summary.pack(side="right", padx=(gap, gap))
        top = int(gap * 0.6)
        ttk.Label(inner, text="Results folder", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=(top, 0), padx=(0, gap))
        self.out_var = tk.StringVar(value=str(default_output()))
        self.out_entry = ttk.Entry(inner, textvariable=self.out_var)
        self.out_entry.grid(row=1, column=1, sticky="ew", pady=(top, 0))
        self.browse_button = ttk.Button(inner, text="Browse…", command=self.select_output)
        self.browse_button.grid(row=1, column=2, sticky="e", padx=(int(6 * self.scale), 0),
                                pady=(top, 0))

        self.cumulative_var = tk.BooleanVar(value=True)
        self.cumulative_check = ttk.Checkbutton(
            inner, style="Card.TCheckbutton", variable=self.cumulative_var,
            text="Also write Cumulative_results.xlsx comparing all genomes (two or more)")
        self.cumulative_check.grid(row=2, column=1, columnspan=2, sticky="w",
                                   pady=(int(gap * 0.5), 0))

    def _build_run_bar(self, body, gap: int) -> None:
        bar = ttk.Frame(body)
        bar.pack(side="bottom", fill="x", pady=(0, int(gap * 0.7)))
        self._step(bar, 3, "", bg=C["bg"]).pack(side="left", padx=(0, int(4 * self.scale)))
        self.run_button = ttk.Button(bar, text="Run analysis", style="Accent.TButton",
                                     command=self.run)
        self.run_button.pack(side="left")
        self.open_button = ttk.Button(bar, text="Open results folder", command=self.open_results,
                                      state="disabled")
        self.open_button.pack(side="left", padx=(int(8 * self.scale), 0), fill="y")
        status = ttk.Frame(bar)
        status.pack(side="left", fill="x", expand=True, padx=(gap * 2, 0))
        self.status = ttk.Label(status, text="Ready", anchor="w")
        self.status.pack(side="top", fill="x")
        self.bar = ttk.Progressbar(status, mode="determinate", maximum=1000)
        self.bar.pack(side="top", fill="x", pady=(int(4 * self.scale), 0))

    def _build_log(self, body) -> None:
        frame = ttk.Frame(body)
        frame.pack(side="bottom", fill="x")
        head = ttk.Frame(frame)
        head.pack(fill="x")
        ttk.Label(head, text="Log", style="Muted.TLabel").pack(side="left")
        self.db_link = _Link(head, "Databases…", self.show_databases, bg=C["bg"],
                             fg=C["accent"], font=self.fonts["small"])
        self.db_link.pack(side="right", padx=(int(8 * self.scale), 0))
        self.db_label = ttk.Label(head, text="Checking databases…", style="Muted.TLabel")
        self.db_label.pack(side="right")
        box = tk.Frame(frame, bg=C["border"])
        box.pack(fill="x")
        inner = tk.Frame(box, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.log = tk.Text(inner, height=5, state="disabled", wrap="word",
                           font=self.fonts["mono"], bg=C["card"], fg="#334155", relief="flat",
                           bd=0, highlightthickness=0, padx=8, pady=4)
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    def show_about(self) -> None:
        f = self.fonts
        win = tk.Toplevel(self.root)
        win.title(f"About {APP_NAME}")
        win.configure(bg=C["card"])
        win.transient(self.root)
        win.resizable(False, False)
        pad = int(22 * self.scale)
        logo = self._logo(int(88 * self.scale))
        if logo is not None:
            tk.Label(win, image=logo, bg=C["card"]).pack(pady=(pad, 8))
        tk.Label(win, text=APP_NAME, font=f["title"], bg=C["card"], fg=C["text"]).pack()
        tk.Label(win, text=f"Version {__version__}", font=f["small"], bg=C["card"],
                 fg=C["muted"]).pack()
        tk.Label(win, text=f"{AUTHOR} · {ORGANISATION}", font=f["bold"], bg=C["card"],
                 fg=C["text"]).pack(pady=(10, 0))
        tk.Label(win, bg=C["card"], fg=C["text"], justify="center", font=f["base"],
                 wraplength=int(380 * self.scale),
                 text=("The portable Windows edition of Hydra: AMR genes, point mutations, "
                       "virulence factors, plasmid replicons, MLST and typing from bacterial "
                       "genome assemblies, with one Excel workbook per genome.\n\n"
                       f"Analysis engine: Hydra ({UPSTREAM_URL.replace('https://', '')}) at "
                       f"commit {UPSTREAM_COMMIT[:7]}. MIT licence. Database licences and "
                       "citations: db\\DATABASES.txt.")).pack(padx=pad, pady=(10, 8))
        for text, url in ((REPO_URL.replace("https://", ""), REPO_URL),
                          (UPSTREAM_URL.replace("https://", ""), UPSTREAM_URL)):
            _Link(win, text, lambda u=url: webbrowser.open(u), bg=C["card"], fg=C["accent"],
                  font=f["link"]).pack()
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(14, pad))
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.bind("<Escape>", lambda _e: win.destroy())
        self.about_window = win

    # --------------------------------------------------------------- inputs
    def add_paths(self, paths) -> None:
        if self.busy:
            self.show_notice("An analysis is running; add genomes when it has finished.")
            return
        intake = core.scan_inputs([Path(p) for p in paths])
        known = {os.path.normcase(str(p.resolve())) for p in self.files}
        added = 0
        for path in intake.assemblies:
            key = os.path.normcase(str(path.resolve()))
            if key not in known:
                known.add(key)
                self.files.append(path)
                added += 1
        message = intake.rejection_message()
        if message:
            self.show_notice(message)
            self.append_log(message)
        elif paths and not intake.assemblies:
            self.show_notice("No FASTA assemblies found in what was added.")
        if added:
            self.append_log(f"Added {added} genome{'s' if added != 1 else ''}.")
        self._refresh()

    def on_drop(self, event) -> None:
        self.add_paths(self.root.tk.splitlist(event.data))

    def select_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            title="Select assemblies",
            filetypes=[("FASTA assemblies", "*.fasta *.fa *.fna *.fas *.fasta.gz *.fa.gz "
                                            "*.fna.gz *.fas.gz"), ("All files", "*.*")])
        if chosen:
            self.add_paths(chosen)

    def select_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Add every assembly in a folder")
        if chosen:
            self.add_paths([chosen])

    def select_output(self) -> None:
        chosen = filedialog.askdirectory(title="Results folder")
        if chosen:
            self.out_var.set(chosen)

    def remove_selected(self) -> None:
        if self.busy:
            return
        doomed = {int(iid[1:]) for iid in self.tree.selection()}
        self.files = [p for i, p in enumerate(self.files) if i not in doomed]
        self._refresh()

    def clear(self) -> None:
        if self.busy:
            return
        self.files.clear()
        self.row_state.clear()
        self.dismiss_notice()
        self._refresh()

    def show_notice(self, text: str) -> None:
        self.notice_text = text
        self.notice_label.configure(text=text)
        if not self.notice.winfo_manager():
            self.notice.pack(side="top", fill="x", pady=(0, int(8 * self.scale)),
                             before=self.table)

    def dismiss_notice(self) -> None:
        self.notice_text = ""
        if self.notice.winfo_manager():
            self.notice.pack_forget()

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(str(path))

    def genomes(self) -> list[core.Genome]:
        return core.plan_genomes(self.files)

    def _refresh(self) -> None:
        genomes = self.genomes()
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.iid_by_name.clear()
        total = 0
        renamed = []
        for index, genome in enumerate(genomes):
            iid = f"g{index}"
            self.iid_by_name[genome.name] = iid
            try:
                size = genome.path.stat().st_size
            except OSError:
                size = 0
            total += size
            state = self.row_state.get(self._key(genome.path), {})
            if state.get("name") not in (None, genome.name):
                state = {}  # the file's name changed since that run
            shown = human_size(size)
            tags = [state.get("tag", "ready")]
            if genome.renamed:
                tags.append("renamed")
                renamed.append(genome)
            head = state.get("headline") or {}
            self.tree.insert("", "end", iid=iid, tags=tags, values=(
                genome.name, genome.path.name, shown, state.get("status", "Ready"),
                head.get("species", ""), head.get("mlst", ""), head.get("amr", ""),
                head.get("mutations", "")))
        keep = [iid for iid in selection if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        n = len(genomes)
        self.count_label.configure(
            text=(f"{n} genome{'s' if n != 1 else ''} · {human_size(total)}" if n
                  else "No genomes yet"))
        if renamed:
            pairs = ", ".join(f"{g.path.name} → {g.name}" for g in renamed[:3])
            more = f" and {len(renamed) - 3} more" if len(renamed) > 3 else ""
            self.rename_label.configure(
                text=f"Same name as another file, renamed so nothing is overwritten: "
                     f"{pairs}{more}")
        else:
            self.rename_label.configure(text="")
        if n:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(relx=0.5, rely=0.55, anchor="center")
        self._update_buttons()

    def _update_buttons(self) -> None:
        n = len(self.files)
        idle = "normal" if not self.busy else "disabled"
        for button in (self.files_button, self.folder_button, self.browse_button,
                       self.settings_button):
            button.configure(state=idle)
        self.clear_button.configure(state="normal" if n and not self.busy else "disabled")
        self.remove_button.configure(
            state="normal" if self.tree.selection() and not self.busy else "disabled")
        self.cumulative_check.configure(state="normal" if n > 1 and not self.busy else "disabled")
        self.run_button.configure(state="normal" if n and not self.busy else "disabled")

    def table_snapshot(self) -> list[dict]:
        rows = []
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            rows.append({c[0]: str(v) for c, v in zip(COLUMNS, values)}
                        | {"tags": list(self.tree.item(iid, "tags"))})
        return rows

    # ------------------------------------------------------------- settings
    def open_settings(self) -> SettingsDialog | None:
        if self.busy:
            return None
        if self.settings_dialog is not None:
            self.settings_dialog.win.lift()
            return self.settings_dialog
        self.settings_dialog = SettingsDialog(self)
        return self.settings_dialog

    def apply_settings(self, settings: core.Settings) -> None:
        changed = settings != self.settings
        self.settings = settings
        self._show_settings()
        if changed:
            self.append_log(f"Settings: {settings.summary()}")

    def _show_settings(self) -> None:
        s = self.settings
        if s.automatic:
            thresholds = "Thresholds: Automatic"
        else:
            def one(name, value):
                return f"{name} {'Automatic' if value is None else f'≥ {value:g}%'}"
            thresholds = (f"Thresholds: {one('identity', s.min_identity)}, "
                          f"{one('coverage', s.min_coverage)}")
        threads = (f"{s.resolved_threads()} threads"
                   + (" (Automatic)" if s.threads is None else ""))
        self.settings_summary.configure(text=f"{thresholds}  ·  {threads}")

    def current_settings(self) -> core.Settings:
        return self.settings

    # ---------------------------------------------------------------- work
    def _start(self, target, *args) -> None:
        self.busy = True
        self._update_buttons()
        threading.Thread(target=target, args=args, daemon=True).start()

    def _finish(self) -> None:
        self.busy = False
        self._update_buttons()

    def database_status(self) -> list[dict]:
        """Per-database rows (installed, version, last failure reason, impact)."""
        from hydra_amr.db.manager import DatabaseStore  # noqa: PLC0415

        from . import databases, runtime  # noqa: PLC0415

        return databases.status(DatabaseStore(runtime.prepare().db_root))

    def refresh_db_status(self) -> list[dict]:
        """Update the status line under the log from the database folder."""
        try:
            rows = self.database_status()
        except Exception as exc:  # noqa: BLE001
            self.db_label.configure(text="Database folder problem (see the log)")
            self.append_log(f"Database check failed: {exc}")
            return []
        self.missing_dbs = {r["name"]: r["impact"] for r in rows if not r["installed"]}
        ok = len(rows) - len(self.missing_dbs)
        if not self.missing_dbs:
            self.db_label.configure(text=f"Databases: all {len(rows)} ready",
                                    foreground=C["muted"])
        else:
            names = ", ".join(SHORT_MISSING.get(n, n) for n in self.missing_dbs)
            self.db_label.configure(text=f"Databases: {ok} of {len(rows)} ready · missing: {names}",
                                    foreground=C["fail"])
        if self.db_dialog is not None:
            self.db_dialog.fill(rows)
        return rows

    def check_databases(self) -> None:
        from hydra_amr.db.manager import DatabaseStore  # noqa: PLC0415

        from . import databases, runtime  # noqa: PLC0415

        try:
            rt = runtime.prepare()
            missing = databases.missing(DatabaseStore(rt.db_root))
        except Exception as exc:  # noqa: BLE001
            self.db_label.configure(text="Database folder problem (see the log)")
            self.append_log(f"Database check failed: {exc}")
            return
        self.refresh_db_status()
        if not missing:
            return
        self.db_label.configure(text=f"Getting {len(missing)} database(s)…")
        self.append_log("First launch: getting the databases that cannot be shipped in the "
                        f"zip ({', '.join(missing)}), from an earlier installation if there is "
                        "one, otherwise by downloading them. This happens once and can take "
                        "several minutes.")
        self._start(self._download_worker)

    def retry_downloads(self) -> None:
        if self.busy:
            return
        self.append_log("Retrying the database downloads…")
        self.db_label.configure(text="Downloading databases…", foreground=C["muted"])
        self._start(self._download_worker)

    def import_databases(self, folder: str | None = None) -> str:
        """Install missing databases from a folder copied from another PC."""
        from hydra_amr.db.manager import DatabaseStore  # noqa: PLC0415

        from . import databases, runtime  # noqa: PLC0415

        if folder is None:
            folder = filedialog.askdirectory(
                title="Folder copied from another PC (its 'db' folder, or the whole HYDRA-Win "
                      "folder)", parent=self.db_dialog.win if self.db_dialog else self.root)
        if not folder:
            return ""
        try:
            _imported, message = databases.import_folder(
                DatabaseStore(runtime.prepare().db_root), folder)
        except Exception as exc:  # noqa: BLE001
            message = f"import failed: {exc}"
        self.append_log(f"Database import: {message}")
        self.refresh_db_status()
        return message

    def show_databases(self) -> DatabasesDialog:
        if self.db_dialog is not None:
            self.db_dialog.win.lift()
            self.db_dialog.fill(self.refresh_db_status())
            return self.db_dialog
        self.db_dialog = DatabasesDialog(self)
        return self.db_dialog

    def _download_worker(self) -> None:
        try:
            failures = core.ensure_databases(
                progress=lambda f, m: self.events.put(("progress", f, m)))
            self.events.put(("db_done", failures))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("db_done", {"databases": str(exc)}))

    def run(self) -> None:
        if not self.files or self.busy:
            return
        settings = self.current_settings()
        outdir = Path(self.out_var.get().strip() or default_output())
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._error(f"Cannot use the results folder:\n{exc}")
            return
        self.open_button.configure(state="disabled")
        self.last_output = outdir
        genomes = self.genomes()
        cumulative = bool(self.cumulative_var.get()) and len(genomes) > 1
        self.row_state = {self._key(g.path): {"name": g.name, "status": "Queued", "tag": "queued"}
                          for g in genomes}
        self._refresh()
        self.dismiss_notice()
        self.append_log(f"Starting analysis of {len(genomes)} genome(s) -> {outdir} "
                        f"({settings.summary()})")
        self._start(self._run_worker, [g.path for g in genomes], outdir, cumulative, settings)

    def _run_worker(self, files, outdir, cumulative, settings) -> None:
        try:
            result = core.analyse(files, outdir, cumulative=cumulative, settings=settings,
                                  progress=lambda f, m: self.events.put(("progress", f, m)),
                                  on_genome=lambda e: self.events.put(("genome", e)))
            self.events.put(("run_done", result))
        except Exception as exc:  # noqa: BLE001 - shown to the user, never swallowed
            LOG.exception("analysis failed")
            self.events.put(("run_failed", str(exc)))

    # ------------------------------------------------------------- events
    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._handle(event)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_row(self, genome: core.Genome, **state) -> None:
        key = self._key(genome.path)
        current = self.row_state.setdefault(key, {"name": genome.name})
        current.update(state)
        iid = self.iid_by_name.get(genome.name)
        if iid is None or not self.tree.exists(iid):
            return
        head = current.get("headline") or {}
        values = list(self.tree.item(iid, "values"))
        values[3] = current.get("status", "")
        values[4:8] = [head.get("species", ""), head.get("mlst", ""), head.get("amr", ""),
                       head.get("mutations", "")]
        tags = [current.get("tag", "ready")] + (["renamed"] if genome.renamed else [])
        self.tree.item(iid, values=values, tags=tags)

    def _handle(self, event) -> None:
        kind = event[0]
        if kind == "log":
            self.append_log(event[1])
        elif kind == "detail":
            self.status.configure(text=event[1])
        elif kind == "progress":
            fraction, message = event[1], event[2]
            if fraction is None:
                if str(self.bar.cget("mode")) != "indeterminate":
                    self.bar.configure(mode="indeterminate")
                    self.bar.start(15)
            else:
                if str(self.bar.cget("mode")) != "determinate":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                self.bar["value"] = int(1000 * max(0.0, min(1.0, fraction)))
            self.status.configure(text=message)
        elif kind == "genome":
            e: core.GenomeEvent = event[1]
            if e.status == "running":
                pct = int(100 * max(0.0, min(0.99, e.fraction)))
                self._set_row(e.genome, status=f"Running {pct}%" if pct else "Running",
                              tag="running")
            elif e.status == "done":
                self._set_row(e.genome, status="Done", tag="done",
                              headline=excel.headline(e.result, self.missing_dbs),
                              workbook=e.workbook)
            elif e.status == "failed":
                self._set_row(e.genome, status="Failed", tag="failed", error=e.error)
        elif kind == "db_done":
            self._finish()
            self._reset_bar()
            failures = event[1]
            self.refresh_db_status()
            if failures:
                for name, reason in failures.items():
                    self.append_log(f"{name} could not be downloaded: {reason}")
                missing = "; ".join(self.missing_dbs.values())
                self.status.configure(text=(
                    f"{', '.join(failures)} could not be downloaded (reason in the log and "
                    "under Databases…; Retry there, or import a copy from another PC). Runs "
                    f"go ahead without them: {missing}"))
            else:
                self.status.configure(text="Ready")
        elif kind == "run_done":
            result: core.AnalysisResult = event[1]
            self._finish()
            self.last_output = result.outdir
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.bar["value"] = 1000
            n, bad = len(result.genomes), len(result.failed)
            books = len(result.workbooks) + (1 if result.cumulative else 0)
            text = (f"Finished: {n - bad} of {n} genome{'s' if n != 1 else ''} analysed, "
                    f"{books} workbook{'s' if books != 1 else ''} in {result.outdir}")
            if bad:
                text += f". {bad} failed: see the log"
            if result.missing_analyses:
                text += ". Not performed: " + "; ".join(
                    SHORT_MISSING.get(n, n) for n in result.missing_analyses)
            self.status.configure(text=text)
            self.open_button.configure(state="normal")
            if bad == n:
                self._error("No genome could be analysed. The log explains why.")
        elif kind == "run_failed":
            self._finish()
            self._reset_bar()
            for key, state in self.row_state.items():
                if state.get("tag") in ("queued", "running"):
                    state.update(status="Not run", tag="failed")
            self._refresh()
            self.status.configure(text="Analysis failed: see the log")
            self._error(f"The analysis failed:\n\n{event[1]}")

    def _error(self, text: str) -> None:
        self.append_log(text.replace("\n\n", " ").replace("\n", " "))
        if not self.quiet:
            messagebox.showerror(APP_NAME, text, parent=self.root)

    def _reset_bar(self) -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar["value"] = 0

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        index = int(iid[1:])
        if index < len(self.files):
            workbook = self.row_state.get(self._key(self.files[index]), {}).get("workbook")
            if workbook and Path(workbook).exists():
                open_path(Path(workbook))

    def open_results(self) -> None:
        if self.last_output:
            open_path(self.last_output)

    def on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
                APP_NAME, "An analysis or download is still running. Quit anyway?",
                parent=self.root):
            return
        self.root.destroy()


#: What a missing database costs, in a few words for the status line.
SHORT_MISSING = {"pubmlst": "PubMLST (no MLST)", "card": "CARD (not screened)",
                 "protein": "AMRFinderPlus proteins (required)", "ncbi": "NCBI genes (required)"}


class DatabasesDialog:
    """Every database: how it is installed, its status or why it is missing."""

    COLUMNS = (("title", "Database", 36), ("route", "How it is installed", 22),
               ("status", "Status", 52))

    def __init__(self, app: App):
        self.app = app
        f, s = app.fonts, app.scale
        win = self.win = tk.Toplevel(app.root)
        win.withdraw()
        win.title("Databases")
        win.configure(bg=C["card"])
        win.transient(app.root)
        pad = int(20 * s)
        body = ttk.Frame(win, style="Card.TFrame", padding=(pad, int(pad * 0.8), pad, pad))
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Databases", font=f["h2"], bg=C["card"], fg=C["text"]).pack(
            anchor="w")
        tk.Label(body, font=f["small"], bg=C["card"], fg=C["muted"], justify="left",
                 wraplength=int(760 * s),
                 text="Twelve databases ship inside the zip. PubMLST and CARD do not allow "
                      "redistribution, so they are downloaded on this PC the first time "
                      "HYDRA-Win starts. If that fails (proxy, firewall), Retry, or copy the "
                      "'db' folder from a PC where it worked and use Import from folder."
                 ).pack(anchor="w", pady=(2, int(10 * s)))
        frame = tk.Frame(body, bg=C["border"])
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c for c, _h, _w in self.COLUMNS],
                                 show="headings", height=14, selectmode="none")
        char = max(6, int(f["base"].measure("0")))
        for key, heading, width in self.COLUMNS:
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=width * char, anchor="w", stretch=key == "status")
        self.tree.tag_configure("missing", foreground=C["fail"])
        self.tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.detail = tk.Label(body, text="", font=f["small"], bg=C["card"], fg=C["text"],
                               justify="left", wraplength=int(760 * s))
        self.detail.pack(anchor="w", pady=(int(8 * s), 0))
        buttons = tk.Frame(body, bg=C["card"])
        buttons.pack(fill="x", pady=(int(10 * s), 0))
        self.retry_button = ttk.Button(buttons, text="Retry download", command=self.retry)
        self.retry_button.pack(side="left")
        ttk.Button(buttons, text="Import from folder…", command=self.import_folder).pack(
            side="left", padx=(int(8 * s), 0))
        ttk.Button(buttons, text="Close", style="Primary.TButton", command=self.close).pack(
            side="right")
        win.bind("<Escape>", lambda _e: self.close())
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.rows = app.refresh_db_status()
        self.fill(self.rows)
        win.update_idletasks()
        root = app.root
        x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_reqheight()) // 4)
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        if app.quiet:
            win.attributes("-topmost", True)

    @staticmethod
    def status_text(row: dict) -> str:
        if row["installed"]:
            version = row.get("version") or ""
            when = (row.get("installed_on") or "")[:10]
            return "Installed" + (f" · {version}" if version and version != "unknown" else "") + \
                (f" · {when}" if when else "")
        reason = row.get("reason") or "not installed"
        return f"MISSING: {reason}"

    def fill(self, rows: list[dict]) -> None:
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            route = "Bundled in the zip" if row["route"] == "bundled" else "Downloaded on this PC"
            self.tree.insert("", "end", values=(row["title"], route, self.status_text(row)),
                             tags=("missing",) if not row["installed"] else ())
        missing = [r for r in rows if not r["installed"]]
        self.detail.configure(
            text=("Without the missing databases a run still completes, and says so in every "
                  "Summary sheet: " + "; ".join(f"{r['title']}: {r['impact']}" for r in missing))
            if missing else "Every database is installed.",
            fg=C["fail"] if missing else C["ok"])
        can_retry = any(not r["installed"] and r["route"] != "bundled" for r in rows)
        self.retry_button.configure(state="normal" if can_retry and not self.app.busy
                                    else "disabled")

    def retry(self) -> None:
        self.app.retry_downloads()
        self.retry_button.configure(state="disabled")

    def import_folder(self) -> None:
        message = self.app.import_databases()
        if message:
            self.detail.configure(text=f"Import: {message}")

    def close(self) -> None:
        self.app.db_dialog = None
        self.win.destroy()


class SettingsDialog:
    """Analysis settings: each one Automatic unless the user enters a value."""

    ROWS = (("identity", "Minimum identity", "%"), ("coverage", "Minimum coverage", "%"),
            ("threads", "Threads", ""))

    def __init__(self, app: App):
        self.app = app
        f, s = app.fonts, app.scale
        current = app.settings
        win = self.win = tk.Toplevel(app.root)
        win.withdraw()
        win.title("Analysis settings")
        win.configure(bg=C["card"])
        win.transient(app.root)
        win.resizable(False, False)
        pad = int(22 * s)
        wrap = int(600 * s)
        body = ttk.Frame(win, style="Card.TFrame", padding=(pad, int(pad * 0.8), pad, pad))
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Analysis settings", font=f["h2"], bg=C["card"],
                 fg=C["text"]).grid(row=0, column=0, columnspan=5, sticky="w")
        tk.Label(body, font=f["small"], bg=C["card"], fg=C["muted"], justify="left",
                 wraplength=wrap,
                 text="Each setting is Automatic unless you untick it and enter a value. The "
                      "values used are written into every workbook's Summary sheet."
                 ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(2, int(12 * s)))
        values = {"identity": (current.min_identity, f"{core.DEFAULT_IDENTITY:g}", 0, 100,
                               f"Automatic: {core.automatic_text('identity')}"),
                  "coverage": (current.min_coverage, f"{core.DEFAULT_COVERAGE:g}", 0, 100,
                               f"Automatic: {core.automatic_text('coverage')}"),
                  "threads": (current.threads, str(cpu_count()), 1, max(cpu_count(), 1),
                              f"Automatic: all {cpu_count()} CPU cores")}
        self.auto: dict[str, tk.BooleanVar] = {}
        self.vars: dict[str, tk.StringVar] = {}
        self.spins: dict[str, ttk.Spinbox] = {}
        for r, (key, label, unit) in enumerate(self.ROWS, start=2):
            value, shown, low, high, note = values[key]
            self.auto[key] = tk.BooleanVar(value=value is None)
            self.vars[key] = tk.StringVar(value=shown if value is None else f"{value:g}")
            ttk.Label(body, text=label, style="Bold.Card.TLabel").grid(
                row=r, column=0, sticky="w", pady=int(4 * s), padx=(0, int(16 * s)))
            ttk.Checkbutton(body, text="Automatic", variable=self.auto[key],
                            style="Card.TCheckbutton", command=self._update).grid(
                row=r, column=1, sticky="w", padx=(0, int(12 * s)))
            spin = ttk.Spinbox(body, from_=low, to=high, increment=1, width=6,
                               textvariable=self.vars[key], justify="right")
            spin.grid(row=r, column=2, sticky="w")
            self.spins[key] = spin
            ttk.Label(body, text=unit, style="Card.TLabel").grid(
                row=r, column=3, sticky="w", padx=(4, int(16 * s)))
            ttk.Label(body, text=note, style="Muted.Card.TLabel").grid(row=r, column=4,
                                                                       sticky="w")
            self.vars[key].trace_add("write", lambda *_: self._update())
        tk.Label(body, text=core.explain_automatic(), wraplength=wrap, justify="left",
                 font=f["small"], fg=C["muted"], bg=C["card"]).grid(
            row=5, column=0, columnspan=5, sticky="w", pady=(int(12 * s), 0))
        self.error = tk.Label(body, text="", fg=C["fail"], bg=C["card"], font=f["small"],
                              justify="left", wraplength=wrap)
        self.error.grid(row=6, column=0, columnspan=5, sticky="w", pady=(int(8 * s), 0))
        buttons = tk.Frame(body, bg=C["card"])
        buttons.grid(row=7, column=0, columnspan=5, sticky="ew", pady=(int(10 * s), 0))
        ttk.Button(buttons, text="Reset to Automatic", command=self.reset).pack(side="left")
        ttk.Button(buttons, text="OK", style="Primary.TButton", command=self.ok).pack(
            side="right")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(
            side="right", padx=(0, int(8 * s)))
        win.bind("<Return>", lambda _e: self.ok())
        win.bind("<Escape>", lambda _e: self.cancel())
        win.protocol("WM_DELETE_WINDOW", self.cancel)
        self._update()
        win.update_idletasks()
        root = app.root
        x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_reqheight()) // 3)
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        if app.quiet:
            win.attributes("-topmost", True)
        try:
            win.grab_set()
        except tk.TclError:
            pass

    def set(self, key: str, value: str | None) -> None:
        """Set one value as a user would (None ticks Automatic)."""
        self.auto[key].set(value is None)
        if value is not None:
            self.vars[key].set(value)
        self._update()

    def parse(self) -> core.Settings:
        return core.Settings.parse(**{
            key: "" if self.auto[key].get() else self.vars[key].get() for key in self.vars})

    def _update(self) -> bool:
        problems = {}
        for key, spin in self.spins.items():
            spin.configure(state="disabled" if self.auto[key].get() else "normal")
            if self.auto[key].get():
                spin.configure(style="TSpinbox")
                continue
            try:
                core.Settings.parse(**{key: self.vars[key].get()})
            except core.SettingsError as exc:
                problems[key] = str(exc)
            spin.configure(style="Invalid.TSpinbox" if key in problems else "TSpinbox")
        self.error.configure(text=next(iter(problems.values()), ""))
        return not problems

    def reset(self) -> None:
        self.set("identity", None)
        self.set("coverage", None)
        self.set("threads", None)
        self.vars["identity"].set(f"{core.DEFAULT_IDENTITY:g}")
        self.vars["coverage"].set(f"{core.DEFAULT_COVERAGE:g}")
        self.vars["threads"].set(str(cpu_count()))

    def ok(self) -> bool:
        try:
            settings = self.parse()
        except core.SettingsError as exc:
            self.error.configure(text=str(exc))
            return False
        self.app.apply_settings(settings)
        self.close()
        return True

    def cancel(self) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
        self.app.settings_dialog = None


# ------------------------------------------------------------------ start-up
def _dpi_aware() -> None:
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        try:  # own taskbar button and icon, not python's
            import ctypes  # noqa: PLC0415

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass


def make_root() -> tk.Tk:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk()
        except Exception:  # noqa: BLE001 - fall back to a plain window
            pass
    return tk.Tk()


# --------------------------------------------------------------- smoke test
class _Drop:
    """A drop event as tkdnd delivers it: a Tcl list of forward-slash paths."""

    def __init__(self, paths):
        self.data = " ".join("{%s}" % Path(p).as_posix() for p in paths)


def _smoke_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"{APP_NAME}.exe --gui-smoke", add_help=False)
    parser.add_argument("--gui-smoke", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--shots", type=Path, help="folder for screenshot requests")
    parser.add_argument("--out", type=Path, help="results folder for --run")
    parser.add_argument("--fastq", type=Path, help="a folder of FASTQ files to drop")
    parser.add_argument("--run", action="store_true", help="click Run and wait for the result")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("genomes", nargs="*")
    return parser


def _smoke(app: App, opts, report: dict):
    """CI: drive the real window as a user would, step by step (a generator).

    Yields a number (wait that many seconds), ("shot", name) to have the CI
    runner capture the window, or ("until", predicate, seconds).
    """
    root = app.root
    root.lift()
    root.attributes("-topmost", True)
    yield 1.5
    report["empty"] = {"files": len(app.files), "run_enabled": str(app.run_button["state"])}
    yield ("shot", "1-empty")

    app.on_drop(_Drop(opts.genomes))
    report["loaded"] = {"files": len(app.files), "rows": app.table_snapshot(),
                        "run_enabled": str(app.run_button["state"])}
    yield 0.8
    yield ("shot", "2-genomes-loaded")

    app.settings_button.invoke()
    dialog = app.settings_dialog
    dialog.set("identity", "abc")
    report["settings_invalid"] = {"error": dialog.error.cget("text"), "accepted": dialog.ok()}
    dialog.set("identity", "90")
    yield 0.8
    yield ("shot", "3-settings-open")
    report["settings_custom"] = {"accepted": dialog.ok(),
                                 "summary": app.settings_summary.cget("text"),
                                 "identity": app.settings.min_identity}
    app.settings_button.invoke()  # back to Automatic for the run, as a user would
    app.settings_dialog.reset()
    app.settings_dialog.ok()
    report["settings_run"] = {"summary": app.settings_summary.cget("text"),
                              "automatic": app.settings.automatic}

    if opts.fastq:
        before = len(app.files)
        app.on_drop(_Drop([opts.fastq]))
        report["fastq"] = {"notice": app.notice_text, "files_before": before,
                           "files_after": len(app.files)}
        yield 0.8
        yield ("shot", "4-fastq-notice")
        app.dismiss_notice()

    if opts.run:
        app.out_var.set(str(opts.out))
        app.run_button.invoke()
        report["run_clicked"] = app.busy

        def running():
            rows = app.table_snapshot()
            return (any(r["status"].startswith("Running ") and int(r["status"].split()[1][:-1]) >= 25
                        for r in rows) or not app.busy)
        yield ("until", running, 900)
        yield ("shot", "5-running")
        yield ("until", lambda: not app.busy, opts.timeout)
        yield 1.0
        yield ("shot", "6-finished")
        report["finished"] = {"rows": app.table_snapshot(),
                              "status": app.status.cget("text"),
                              "open_enabled": str(app.open_button["state"])}

    dialog = app.show_databases()
    yield 0.8
    report["databases"] = {"label": app.db_label.cget("text"),
                           "rows": [{"name": r["name"], "installed": r["installed"],
                                     "route": r["route"], "status": dialog.status_text(r)}
                                    for r in dialog.rows]}
    yield ("shot", "7-databases")
    dialog.close()

    root.update_idletasks()
    left, top, right, bottom = _work_area(root)
    log_y = app.log.winfo_rooty() + app.log.winfo_height()
    report["screen"] = {"size": [root.winfo_screenwidth(), root.winfo_screenheight()],
                        "work_area": [left, top, right, bottom],
                        "window": window_rect(root), "log_bottom": log_y,
                        "scale": app.scale}


def _drive(app: App, steps, shots: Path | None, on_done) -> None:
    root = app.root

    def advance():
        try:
            step = next(steps)
        except StopIteration:
            on_done()
            return
        except Exception as exc:  # noqa: BLE001 - report, never hang the CI job
            LOG.exception("smoke step failed")
            on_done(error=str(exc))
            return
        if isinstance(step, (int, float)):
            root.after(int(step * 1000), advance)
        elif step[0] == "until":
            deadline = time.monotonic() + step[2]

            def check():
                if step[1]() or time.monotonic() > deadline:
                    advance()
                else:
                    root.after(250, check)
            check()
        elif step[0] == "shot":
            if shots is None:
                root.after(10, advance)
                return
            shots.mkdir(parents=True, exist_ok=True)
            root.update_idletasks()
            png = shots / f"{step[1]}.png"
            request = shots / f"{step[1]}.request.json"
            request.write_text(json.dumps({"rect": window_rect(root)}), encoding="utf-8")
            deadline = time.monotonic() + 30

            def wait():
                if png.exists() or time.monotonic() > deadline:
                    root.after(100, advance)
                else:
                    root.after(150, wait)
            wait()

    root.after(200, advance)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    _dpi_aware()
    smoke = "--gui-smoke" in argv
    opts = _smoke_parser().parse_args(argv) if smoke else None
    root = make_root()
    app = App(root)
    if smoke:
        app.quiet = True
        report: dict = {"tk": str(root.tk.call("info", "patchlevel")), "dnd": app.dnd_enabled,
                        "title": root.title(), "version": __version__}

        def finish(error: str | None = None):
            report["error"] = error
            if opts.report:
                opts.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
            root.destroy()

        _drive(app, _smoke(app, opts, report), opts.shots, finish)
    root.mainloop()
    return 0
