"""The Hydra-win window (tkinter, with tkinterdnd2 for drag-and-drop).

All analysis runs in a worker thread through :func:`hydra_win.core.analyse`,
the same function ``--cli`` uses; the window only collects inputs, shows
progress and opens the results.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, core

LOG = logging.getLogger("hydra")

try:  # drag-and-drop is a nicety; the window works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001
    DND_FILES = None
    TkinterDnD = None


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
    return (documents if documents.is_dir() else Path.home()) / "Hydra-win results"


def open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk, check_db: bool = True):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.files: list[Path] = []
        self.busy = False
        self.last_output: Path | None = None
        self.dnd_enabled = False

        root.title(f"Hydra-win {__version__}")
        root.geometry("860x660")
        root.minsize(680, 520)
        self._build()
        handler = _QueueHandler(self.events)
        LOG.addHandler(handler)
        LOG.setLevel(logging.DEBUG)
        LOG.propagate = False
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        if check_db:
            root.after(300, self.check_databases)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Hydra-win", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(top, text="AMR genes, point mutations, virulence, plasmids, MLST and typing "
                            "from bacterial genome assemblies").pack(anchor="w")

        files = ttk.LabelFrame(self.root, text="Assemblies (FASTA: .fasta .fa .fna .fas, "
                                               "optionally .gz)")
        files.pack(fill="both", expand=True, **pad)
        holder = ttk.Frame(files)
        holder.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.listbox = tk.Listbox(holder, selectmode="extended", height=8, activestyle="none")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.hint = ttk.Label(holder, foreground="#777777",
                              text="Drag FASTA files or folders here, or use Select files")
        self.hint.place(relx=0.5, rely=0.5, anchor="center")

        buttons = ttk.Frame(files)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Select files...", command=self.select_files).pack(side="left")
        ttk.Button(buttons, text="Add folder...", command=self.select_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="Remove selected", command=self.remove_selected).pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left", padx=6)
        self.count_label = ttk.Label(buttons, text="0 genomes")
        self.count_label.pack(side="right")

        out = ttk.LabelFrame(self.root, text="Output")
        out.pack(fill="x", **pad)
        row = ttk.Frame(out)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="Results folder:").pack(side="left")
        self.out_var = tk.StringVar(value=str(default_output()))
        ttk.Entry(row, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Browse...", command=self.select_output).pack(side="left")
        self.cumulative_var = tk.BooleanVar(value=True)
        self.cumulative_check = ttk.Checkbutton(
            out, text="Cumulative_results  (one extra workbook comparing all genomes; "
                      "needs two or more)", variable=self.cumulative_var)
        self.cumulative_check.pack(anchor="w", padx=8, pady=(0, 8))

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.run_button = ttk.Button(actions, text="Run analysis", command=self.run)
        self.run_button.pack(side="left", ipadx=18, ipady=6)
        self.open_button = ttk.Button(actions, text="Open results folder",
                                      command=self.open_results, state="disabled")
        self.open_button.pack(side="left", padx=8, ipady=6)
        self.db_label = ttk.Label(actions, text="Checking databases...")
        self.db_label.pack(side="right")

        progress = ttk.Frame(self.root)
        progress.pack(fill="x", **pad)
        self.bar = ttk.Progressbar(progress, mode="determinate", maximum=1000)
        self.bar.pack(fill="x")
        self.status = ttk.Label(progress, text="Ready")
        self.status.pack(anchor="w", pady=(4, 0))

        logs = ttk.LabelFrame(self.root, text="Log")
        logs.pack(fill="both", expand=False, **pad)
        self.log = ScrolledText(logs, height=8, state="disabled", wrap="word",
                                font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        if TkinterDnD is not None and DND_FILES is not None:
            try:
                for widget in (self.root, self.listbox):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                self.dnd_enabled = True
            except Exception:  # noqa: BLE001 - tkdnd failed to load
                self.dnd_enabled = False
        if not self.dnd_enabled:
            self.hint.configure(text="Use Select files or Add folder "
                                     "(drag-and-drop is unavailable on this system)")
        self._refresh()

    # --------------------------------------------------------------- inputs
    def add_paths(self, paths) -> None:
        found = core.expand_inputs([Path(p) for p in paths])
        known = {os.path.normcase(str(p.resolve())) for p in self.files}
        for path in found:
            key = os.path.normcase(str(path.resolve()))
            if key not in known:
                known.add(key)
                self.files.append(path)
        if paths and not found:
            self.append_log("No FASTA assemblies found in what was dropped.")
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
        for index in sorted(self.listbox.curselection(), reverse=True):
            del self.files[index]
        self._refresh()

    def clear(self) -> None:
        self.files.clear()
        self._refresh()

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for path in self.files:
            self.listbox.insert("end", str(path))
        n = len(self.files)
        self.count_label.configure(text=f"{n} genome{'s' if n != 1 else ''}")
        if n:
            self.hint.place_forget()
        else:
            self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.cumulative_check.configure(state="normal" if n > 1 else "disabled")
        self.run_button.configure(state="normal" if n and not self.busy else "disabled")

    # ---------------------------------------------------------------- work
    def _start(self, target, *args) -> None:
        self.busy = True
        self._refresh()
        threading.Thread(target=target, args=args, daemon=True).start()

    def check_databases(self) -> None:
        from hydra_amr.db.manager import DatabaseStore  # noqa: PLC0415

        from . import databases, runtime  # noqa: PLC0415

        try:
            rt = runtime.prepare()
            missing = databases.missing(DatabaseStore(rt.db_root))
        except Exception as exc:  # noqa: BLE001
            self.db_label.configure(text="Database folder problem")
            self.append_log(f"Database check failed: {exc}")
            return
        if not missing:
            self.db_label.configure(text=f"Databases ready ({len(databases.ALL)})")
            return
        self.db_label.configure(text=f"Downloading {len(missing)} database(s)...")
        self.append_log("First launch: downloading the databases that cannot be shipped in "
                        f"the zip ({', '.join(missing)}). This happens once and can take "
                        "several minutes.")
        self._start(self._download_worker)

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
        outdir = Path(self.out_var.get().strip() or default_output())
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Hydra-win", f"Cannot use the results folder:\n{exc}")
            return
        self.open_button.configure(state="disabled")
        cumulative = bool(self.cumulative_var.get()) and len(self.files) > 1
        self.append_log(f"Starting analysis of {len(self.files)} genome(s) -> {outdir}")
        self._start(self._run_worker, list(self.files), outdir, cumulative)

    def _run_worker(self, files, outdir, cumulative) -> None:
        try:
            result = core.analyse(files, outdir, cumulative=cumulative,
                                  progress=lambda f, m: self.events.put(("progress", f, m)))
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
        elif kind == "db_done":
            self.busy = False
            self._reset_bar()
            failures = event[1]
            if failures:
                self.db_label.configure(text=f"{len(failures)} database(s) unavailable")
                self.status.configure(text="Some databases could not be downloaded; they are "
                                           "retried at the next run. Analyses still work with "
                                           "the others.")
            else:
                self.db_label.configure(text="Databases ready")
                self.status.configure(text="Ready")
            self._refresh()
        elif kind == "run_done":
            result = event[1]
            self.busy = False
            self.last_output = result.outdir
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.bar["value"] = 1000
            self.status.configure(text=f"Done: {len(result.workbooks)} workbook(s) in "
                                       f"{result.outdir}")
            self.open_button.configure(state="normal")
            self._refresh()
        elif kind == "run_failed":
            self.busy = False
            self._reset_bar()
            self.status.configure(text="Analysis failed - see the log")
            self._refresh()
            messagebox.showerror("Hydra-win", f"The analysis failed:\n\n{event[1]}")

    def _reset_bar(self) -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar["value"] = 0

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_results(self) -> None:
        if self.last_output:
            open_folder(self.last_output)

    def on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
                "Hydra-win", "An analysis or download is still running. Quit anyway?"):
            return
        self.root.destroy()


def _dpi_aware() -> None:
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass


def make_root() -> tk.Tk:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk()
        except Exception:  # noqa: BLE001 - fall back to a plain window
            pass
    return tk.Tk()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    _dpi_aware()
    smoke_seconds = None
    report_path = None
    files: list[str] = []
    if "--gui-smoke" in argv:
        # CI: build the real window, load files, report, close. No analysis.
        i = argv.index("--gui-smoke")
        smoke_seconds = float(argv[i + 1])
        rest = argv[i + 2:]
        if "--report" in rest:
            j = rest.index("--report")
            report_path = Path(rest[j + 1])
            rest = rest[:j] + rest[j + 2:]
        files = rest
    root = make_root()
    app = App(root, check_db=smoke_seconds is None)  # no downloads in a smoke test
    if smoke_seconds is not None:
        if files:
            app.add_paths(files)

        def finish():
            report = {"tk": str(root.tk.call("info", "patchlevel")), "dnd": app.dnd_enabled,
                      "files": len(app.files), "run_enabled": str(app.run_button["state"]),
                      "title": root.title()}
            if report_path:
                report_path.write_text(json.dumps(report), encoding="utf-8")
            root.destroy()

        root.after(int(smoke_seconds * 1000), finish)
    root.mainloop()
    return 0
