#!/usr/bin/env python3
"""Release-workflow steps for the Windows runner (also runnable by hand).

    ci.py blast DIST                fetch NCBI BLAST+ win64, copy what Hydra needs
    ci.py build-db DIST             build the bundled databases with the packaged exe
    ci.py package DIST ZIP          clean scratch files and zip the app folder
    ci.py smoke ZIP WORK            unzip into an awkward path, run --cli on public
                                    genomes with --cumulative, assert the workbooks
    ci.py gui-smoke APPDIR WORK     open the real window briefly, screenshot, assert

Test genomes are public NCBI RefSeq assemblies downloaded at run time:
K. pneumoniae HS11286 (ST11, KPC-2) and E. coli EC958 (ST131, CTX-M-15).
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

BLAST_VERSION = "2.16.0"
BLAST_URL = ("https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/"
             f"{BLAST_VERSION}/ncbi-blast-{BLAST_VERSION}+-x64-win64.tar.gz")
BLAST_PROGRAMS = ("blastn", "blastx", "makeblastdb")
BLAST_DLLS = ("nghttp2.dll", "ncbi-vdb-md.dll")
BLAST_DOCS = ("LICENSE", "README", "BLAST_PRIVACY")
#: BLAST+ links the Visual C++ 2015-2022 runtime dynamically; shipping these
#: next to it (Microsoft's "app-local" deployment) means users need not install it.
VC_RUNTIME = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")

GENOMES = {
    "HS11286": "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/240/185/"
               "GCF_000240185.1_ASM24018v2/GCF_000240185.1_ASM24018v2_genomic.fna.gz",
    "EC958": "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/285/655/"
             "GCF_000285655.3_EC958.v1/GCF_000285655.3_EC958.v1_genomic.fna.gz",
}
#: What the literature says these two genomes carry.
EXPECT = {
    "HS11286": {"species": "Klebsiella pneumoniae", "st": "11",
                "genes": ["blaKPC-2", "blaCTX-M-14"], "mutations": ["gyrA_S83I"]},
    "EC958": {"species": "Escherichia coli", "typing": {"ST achtman": "131"},
              "genes": ["blaCTX-M-15", "blaOXA-1"], "mutations": ["gyrA_S83L", "parC_S80I"]},
}
GENOME_SHEETS = ("Summary", "AMR_genes", "Point_mutations", "Virulence", "Plasmids",
                 "Typing", "All_hits", "Pivot")
CUMULATIVE_SHEETS = ("Summary", "AMR_matrix", "Mutations_matrix", "Virulence_matrix",
                     "Plasmids_matrix", "All_hits")


def log(message: str) -> None:
    print(f"[ci] {message}", flush=True)


def download(url: str, dest: Path, attempts: int = 4) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "hydra-win-ci"})
            with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as out:
                shutil.copyfileobj(response, out)
            return dest
        except OSError as exc:
            log(f"download failed ({exc}); retry {attempt + 1}")
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"could not download {url}")


def run_exe(exe: Path, args: list[str], timeout: int, log_file: Path | None = None) -> int:
    """Run the windowed exe, stream its log file while it runs, return its exit code."""
    log(f"running {exe.name} {' '.join(args)}")
    started = time.time()
    # The exe must not lean on the runner's Python settings (UTF-8 mode in particular).
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["HYDRA_WIN_HANG_DUMP"] = "300"
    out_path = Path(os.environ.get("RUNNER_TEMP", ".")) / f"exe-output-{os.getpid()}.txt"
    with open(out_path, "w", encoding="utf-8") as out:
        proc = subprocess.Popen([str(exe), *args], stdout=out, stderr=subprocess.STDOUT, env=env)
        offset = 0
        while True:
            try:
                rc = proc.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                pass
            stacks = Path(f"{log_file}.stacks.txt") if log_file else None
            if stacks and stacks.exists() and stacks.stat().st_size and int(time.time()) % 300 < 10:
                print(f"----- thread stacks ({stacks.name}) -----")
                print(stacks.read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
            if log_file and log_file.exists():
                with open(log_file, encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    chunk = handle.read()
                    offset = handle.tell()
                for line in chunk.splitlines():
                    if " DEBUG " not in line:
                        print(f"  | {line}", flush=True)
            if time.time() - started > timeout:
                proc.kill()
                log(f"killed after {timeout}s")
                rc = -9
                break
    log(f"exit code {rc} after {time.time() - started:.0f}s")
    text = out_path.read_text(encoding="utf-8", errors="replace")
    if text.strip():
        print(text[-20000:], flush=True)
    if log_file and log_file.exists():
        with open(log_file, encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            for line in handle.read().splitlines():
                if " DEBUG " not in line:
                    print(f"  | {line}", flush=True)
    return rc


# ---------------------------------------------------------------- steps
def cmd_blast(dist: Path) -> None:
    work = Path(os.environ.get("RUNNER_TEMP", ".")) / "blast-download"
    archive = download(BLAST_URL, work / "blast.tar.gz")
    target = dist / "blast" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    wanted = {f"{p}.exe" for p in BLAST_PROGRAMS} | {f"{p}.exe.manifest" for p in BLAST_PROGRAMS}
    wanted |= set(BLAST_DLLS)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            parent = Path(member.name).parent.name
            if (parent == "bin" and name in wanted) or (name in BLAST_DOCS
                                                        and parent.startswith("ncbi-blast")):
                source = tar.extractfile(member)
                dest = (target if parent == "bin" else dist / "blast") / name
                with open(dest, "wb") as out:
                    shutil.copyfileobj(source, out)
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for dll in VC_RUNTIME:
        shutil.copy2(system32 / dll, target / dll)
    missing = [n for n in wanted | set(VC_RUNTIME) if not (target / n).exists()]
    if missing:
        raise SystemExit(f"BLAST+ files missing: {missing}")
    out = subprocess.run([str(target / "blastn.exe"), "-version"], capture_output=True, text=True)
    log(out.stdout.strip() or out.stderr.strip())
    if out.returncode != 0:
        raise SystemExit("blastn.exe does not run")


def cmd_build_db(dist: Path) -> None:
    exe = dist / "Hydra-win.exe"
    log_file = dist.parent / "build-db.log"
    rc = run_exe(exe, ["--build-db", str(dist / "db"), "--log", str(log_file), "-v"],
                 timeout=3600, log_file=log_file)
    if rc != 0:
        raise SystemExit("database build failed")
    status_file = dist.parent / "db-status.json"
    run_exe(exe, ["--db-status", str(status_file)], timeout=300)
    status = json.loads(status_file.read_text(encoding="utf-8"))
    print(json.dumps(status, indent=1))
    bundled = [d for d in status["databases"] if d["route"] == "bundled"]
    absent = [d["name"] for d in bundled if not d["installed"]]
    if absent:
        raise SystemExit(f"bundled databases not built: {absent}")
    shipped = [d["name"] for d in status["databases"]
               if d["route"] != "bundled" and d["installed"]]
    if shipped:
        raise SystemExit(f"non-redistributable databases present in the bundle: {shipped}")


def cmd_package(dist: Path, zip_path: Path) -> None:
    for scratch in (dist / "work", dist / "db" / ".download"):
        shutil.rmtree(scratch, ignore_errors=True)
    root = Path(__file__).resolve().parents[1]
    for name in ("README.md", "LICENSE"):
        shutil.copy2(root / name, dist / name)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    seven = shutil.which("7z") or next(
        (str(p) for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe",)
         if p.exists()), None)
    if seven:
        # Multi-threaded deflate; the archive is an ordinary .zip with a top-level folder.
        subprocess.run([seven, "a", "-tzip", "-mx=5", "-mmt=on", str(zip_path.resolve()),
                        dist.name], cwd=dist.parent, check=True, stdout=subprocess.DEVNULL)
    else:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(dist.rglob("*")):
                if path.is_file():
                    zf.write(path, Path(dist.name) / path.relative_to(dist))
    log(f"wrote {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")


def _rows(ws, header_row=1):
    values = list(ws.iter_rows(min_row=header_row, values_only=True))
    header = values[0]
    out = []
    for row in values[1:]:
        if all(v is None for v in row):
            break
        out.append(dict(zip(header, row)))
    return out


def fetch_genomes(folder: Path) -> list[Path]:
    """The two public genomes: one left gzipped, one unpacked to .fasta."""
    folder.mkdir(parents=True, exist_ok=True)
    hs = download(GENOMES["HS11286"], folder / "HS11286.fna.gz")
    ec_gz = download(GENOMES["EC958"], folder / "EC958.fna.gz")
    ec = folder / "EC958.fasta"
    with gzip.open(ec_gz, "rb") as src, open(ec, "wb") as dst:
        shutil.copyfileobj(src, dst)
    ec_gz.unlink()
    return [hs, ec]


def assert_outputs(out: Path) -> list[str]:
    from openpyxl import load_workbook  # noqa: PLC0415

    problems: list[str] = []
    for genome, expect in EXPECT.items():
        book = out / genome / f"{genome}.xlsx"
        if not book.exists():
            problems.append(f"{book} missing")
            continue
        wb = load_workbook(book, read_only=False)
        missing = [s for s in GENOME_SHEETS if s not in wb.sheetnames]
        if missing:
            problems.append(f"{genome}: sheets missing {missing}")
            continue
        hits = _rows(wb["All_hits"])
        amr = _rows(wb["AMR_genes"])
        if not hits or not amr:
            problems.append(f"{genome}: no hits ({len(hits)} total, {len(amr)} AMR)")
        bad = [h for h in hits if not (h["Contig"] and h["Start"] and h["End"]
                                       and h["Strand"] in ("+", "-"))]
        if bad:
            problems.append(f"{genome}: {len(bad)} hits lack contig/start/end/strand")
        genes = {h["Gene"] for h in amr}
        for gene in expect["genes"]:
            if gene not in genes:
                problems.append(f"{genome}: expected gene {gene} not found")
        mutations = {r["Mutation"] for r in _rows(wb["Point_mutations"])}
        for mutation in expect["mutations"]:
            if mutation not in mutations:
                problems.append(f"{genome}: expected mutation {mutation} not found "
                                f"(have {sorted(mutations)})")
        if not _rows(wb["Virulence"]):
            problems.append(f"{genome}: Virulence sheet empty")
        if not _rows(wb["Plasmids"]):
            problems.append(f"{genome}: Plasmids sheet empty")
        summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
        if summary.get("Species") != expect["species"]:
            problems.append(f"{genome}: species {summary.get('Species')!r}")
        if "st" in expect and str(summary.get("MLST ST")) != expect["st"]:
            problems.append(f"{genome}: MLST ST {summary.get('MLST ST')!r}, "
                            f"expected {expect['st']}")
        typing = {r["Scheme / database"]: r["Call"] for r in _rows(wb["Typing"])}
        for scheme, call in expect.get("typing", {}).items():
            if str(typing.get(scheme)) != call:
                problems.append(f"{genome}: typing {scheme} {typing.get(scheme)!r}, "
                                f"expected {call}")
        if wb["Pivot"].max_row < 7:
            problems.append(f"{genome}: Pivot sheet has no loci")
        log(f"{genome}: {len(hits)} hits, {len(amr)} AMR rows, species "
            f"{summary.get('Species')}, {summary.get('MLST scheme')} ST{summary.get('MLST ST')}, "
            f"mutations {sorted(mutations)}")
    cumulative = out / "Cumulative_results.xlsx"
    if not cumulative.exists():
        problems.append("Cumulative_results.xlsx missing")
    else:
        wb = load_workbook(cumulative)
        missing = [s for s in CUMULATIVE_SHEETS if s not in wb.sheetnames]
        if missing:
            problems.append(f"cumulative: sheets missing {missing}")
        else:
            assemblies = [r["Assembly"] for r in _rows(wb["Summary"])]
            if sorted(assemblies) != sorted(EXPECT):
                problems.append(f"cumulative Summary assemblies {assemblies}")
            matrix = {r["Assembly"]: r for r in _rows(wb["AMR_matrix"], header_row=2)}
            if not matrix.get("HS11286", {}).get("blaKPC-2"):
                problems.append("cumulative AMR_matrix: HS11286 x blaKPC-2 empty")
            if matrix.get("EC958", {}).get("blaKPC-2"):
                problems.append("cumulative AMR_matrix: EC958 x blaKPC-2 should be empty")
            long = _rows(wb["All_hits"])
            if not long or {r["Assembly"] for r in long} != set(EXPECT):
                problems.append("cumulative All_hits does not cover both assemblies")
            log(f"cumulative: {len(long)} hits")
    return problems


def cmd_smoke(zip_path: Path, work: Path) -> None:
    # Spaces and non-ASCII everywhere a user might have them.
    app_parent = work / "Hydra wïn smoke ü"
    shutil.rmtree(app_parent, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(app_parent)
    app = next(app_parent.glob("*/Hydra-win.exe"))
    genomes = fetch_genomes(work / "genomes ö dir")
    out = work / "results ä folder"
    shutil.rmtree(out, ignore_errors=True)
    # First launch, as a user gets it: download the non-redistributable databases.
    fetch_log = work / "smoke-fetch.log"
    started = time.time()
    rc = run_exe(app, ["--fetch-db", "--log", str(fetch_log), "-v"], timeout=3600,
                 log_file=fetch_log)
    log(f"first-launch download took {time.time() - started:.0f}s (exit {rc})")
    log_file = work / "smoke-run.log"
    rc = run_exe(app, ["--cli", *map(str, genomes), "--out", str(out), "--cumulative",
                       "--log", str(log_file)], timeout=2400, log_file=log_file)
    status_file = work / "smoke-db-status.json"
    run_exe(app, ["--db-status", str(status_file)], timeout=300)
    if status_file.exists():
        status = json.loads(status_file.read_text(encoding="utf-8"))
        print(json.dumps(status, indent=1))
        if not status.get("utf8_mode"):
            raise SystemExit("the packaged exe is not running in Python UTF-8 mode")
    if rc != 0:
        raise SystemExit(f"Hydra-win --cli exited with {rc}")
    problems = assert_outputs(out)
    for problem in problems:
        log(f"PROBLEM: {problem}")
    shutil.copytree(out, work / "smoke-results", dirs_exist_ok=True)
    if problems:
        raise SystemExit(f"{len(problems)} smoke-test problem(s)")
    log("smoke test passed")


def cmd_gui_smoke(app_dir: Path, work: Path) -> None:
    exe = app_dir / "Hydra-win.exe"
    genomes = sorted((work / "genomes ö dir").glob("*")) or fetch_genomes(work / "genomes ö dir")
    report = work / "gui-report.json"
    if report.exists():
        report.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    proc = subprocess.Popen([str(exe), "--gui-smoke", "12", "--report", str(report),
                             *map(str, genomes)], env=env)
    time.sleep(8)
    try:
        from PIL import ImageGrab  # noqa: PLC0415

        ImageGrab.grab().save(work / "gui-screenshot.png")
        log("screenshot saved")
    except Exception as exc:  # noqa: BLE001
        log(f"screenshot failed: {exc}")
    rc = proc.wait(timeout=120)
    if rc != 0 or not report.exists():
        raise SystemExit(f"GUI smoke failed (exit {rc}, report {report.exists()})")
    data = json.loads(report.read_text(encoding="utf-8"))
    log(f"GUI report: {data}")
    if not data.get("dnd"):
        raise SystemExit("drag-and-drop (tkdnd) did not load in the packaged exe")
    if data.get("files") != len(genomes) or data.get("run_enabled") != "normal":
        raise SystemExit("GUI did not accept the input files")


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    step, args = argv[1], [Path(a) for a in argv[2:]]
    {"blast": cmd_blast, "build-db": cmd_build_db, "package": cmd_package,
     "smoke": cmd_smoke, "gui-smoke": cmd_gui_smoke}[step](*args)


if __name__ == "__main__":
    main(sys.argv)
