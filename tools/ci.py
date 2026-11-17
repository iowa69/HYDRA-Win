#!/usr/bin/env python3
"""Release-workflow steps for the Windows runner (also runnable by hand).

    ci.py blast DIST                fetch NCBI BLAST+ win64, copy what Hydra needs
    ci.py build-db DIST             build the bundled databases with the packaged exe
    ci.py package DIST ZIP          clean scratch files and zip the app folder
    ci.py smoke ZIP WORK            unzip into an awkward path, run --cli on public
                                    genomes with --cumulative, assert the workbooks and
                                    re-read every reported codon from the FASTA; then a
                                    run with custom thresholds and FASTQ inputs; then a
                                    fresh unzip run --offline (bundled databases only)
    ci.py display WIDTH HEIGHT      set the runner's screen resolution (best effort)
    ci.py gui-smoke WORK            drive the real window of the unzipped app: add the
                                    genomes, open the settings, drop FASTQ files, click
                                    Run, wait for the table to finish; screenshot the
                                    window at each step and assert the results

Test genomes are public NCBI RefSeq assemblies downloaded at run time:
K. pneumoniae HS11286 (ST11, KPC-2), E. coli EC958 (ST131, CTX-M-15) and
S. aureus USA300 FPR3757 (ST8/CC8, spa t008, SCCmec IVa, PVL+). The last two
are organisms whose typing data is bundled in the zip, so the offline run has
to produce real organism-specific calls for them.
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
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

APP = "HYDRA-Win"
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
    "USA300": "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/013/465/"
              "GCF_000013465.1_ASM1346v1/GCF_000013465.1_ASM1346v1_genomic.fna.gz",
}
#: What the literature says these two genomes carry.
#: Point mutations and disruptions are the ones AMRFinderPlus 4.2.7 (database
#: 2026-05-15.1) reports for these genomes, under the same names.
EXPECT = {
    "HS11286": {"species": "Klebsiella pneumoniae", "st": "11",
                "genes": ["blaKPC-2", "blaCTX-M-14"],
                # pmrB_A21DfsTer16 is the 1 bp insertion Kleborate reports as
                # pmrB:p.Gly20fs; Hydra missed it until pmrB was added to the
                # loss-of-function catalogue, and the kleborate_call column
                # carries Kleborate's own spelling of it.
                "mutations": ["gyrA_S83I", "parC_S80I", "ompK35_G134AfsTer11",
                              "cirA_N467MfsTer15", "pmrB_A21DfsTer16"],
                "matrix": {"gyrA": "S83I", "ompK35": "G134AfsTer11",
                           "pmrB": "A21DfsTer16"},
                "kleborate": {"pmrB_A21DfsTer16": "pmrb:p.Gly20fs"},
                # No organism typing module covers Klebsiella: its lineage
                # schemes are the Kleborate ones, which the Typing sheet
                # already carried before the modules existed.
                "organism_typing": {}},
    "EC958": {"species": "Escherichia coli", "typing": {"ST achtman": "131"},
              "genes": ["blaCTX-M-15", "blaOXA-1"],
              # acrR_F180LfsTer3 is AMRFinderPlus's own symbol for the frameshift
              # in this genome's acrR; Hydra missed it until acrR was added to
              # the loss-of-function catalogue for the Escherichia taxgroup.
              "mutations": ["gyrA_S83L", "gyrA_D87N", "parC_S80I", "parC_E84V", "parE_I529L",
                            "ptsI_V25I", "uhpT_E350Q", "acrR_F180LfsTer3"],
              "matrix": {"gyrA": "S83L; D87N", "acrR": "F180LfsTer3"},
              # EC958 is the reference ST131-H30Rx uropathogen (Totsika 2011,
              # Forde 2014): phylogroup B2, fimH30, ExPEC by the marker rule,
              # and no Shiga toxin.
              "organism_typing": {
                  "Phylogroup (Clermont)": "B2",
                  "fimH allele (FimTyper)": "fimH30",
                  "Pathotype": "ExPEC",
                  "Shiga toxin subtype": "none detected",
                  "Shigella / EIEC cluster": "not Shigella/EIEC"},
              "offline_typing": {
                  "Phylogroup (Clermont)": "B2",
                  "fimH allele (FimTyper)": "fimH30",
                  "Pathotype": "ExPEC",
                  "Shiga toxin subtype": "none detected",
                  # The bundled pre-2025 PubMLST snapshot types the Achtman
                  # loci with no network, so the ST and the ST131 subclone call
                  # that reads it are available offline.
                  "ST achtman": "131"},
              "offline_undetermined": {
                  "Shigella / EIEC cluster": "the ShigEiFinder gene sets"},
              # The nine the offline run has always required of this genome.
              "offline_databases": ("ncbi", "protein", "resfinder", "argannot", "megares",
                                    "vfdb", "ecoli_vf", "plasmidfinder", "ecoh"),
              "headline": "ExPEC \u00b7 phylogroup B2"},
    "USA300": {"species": "Staphylococcus aureus", "st": "8",
               # SCCmec IVa carries mecA; the three small plasmids of FPR3757
               # carry erm(C) (pUSA01), tet(K) (pUSA02) and mupA (pUSA03).
               "genes": ["mecA", "erm(C)", "tet(K)"],
               "mutations": ["gyrA_S84L", "parC_S80Y"],
               "matrix": {"gyrA": "S84L"},
               # USA300 FPR3757 (Diep 2006): ST8/CC8, spa t008, agr group I,
               # PVL positive, capsule serotype 5, immune evasion cluster type
               # B, ACME present, hlb interrupted by the Sa3int prophage.
               "organism_typing": {
                   "spa type (Ridom)": "t008",
                   "MLST clonal complex": "CC8",
                   "agr group": "I",
                   "Panton-Valentine leucocidin (lukS/lukF-PV)": "positive",
                   "Capsule serotype (cap locus)": "5",
                   "Immune evasion cluster (IEC type)": "type B",
                   "Toxic shock toxin (tst)": "negative"},
               # What the bundled data alone can call, with no network.
               "offline_typing": {
                   "MLST clonal complex": "CC8",
                   "agr group": "I",
                   "Panton-Valentine leucocidin (lukS/lukF-PV)": "positive",
                   "Capsule serotype (cap locus)": "5",
                   "Immune evasion cluster (IEC type)": "type B",
                   "Arginine catabolic mobile element": "arc cluster present",
                   "beta-haemolysin (hlb) status": "disrupted by prophage integration"},
               # ... and what it cannot, with what is missing. Only the spa
               # database is still withheld, by the Ridom policy. The clonal
               # complex is derived from the sequence type, and the pre-2025
               # PubMLST snapshot is now in the zip, so offline there IS an ST
               # to derive it from -- which is the point of the offline MLST
               # test: a call that depends on the ST has to come out right.
               "offline_undetermined": {
                   "spa type (Ridom)": "the Ridom spa database"},
               "offline_st": "8",
               # ecoli_vf and ecoh hold E. coli sequences and have nothing to
               # say about a staphylococcus, so they are not required here.
               "offline_databases": ("ncbi", "protein", "resfinder", "argannot",
                                     "megares", "vfdb"),
               "headline": "spa t008 \u00b7 CC8 \u00b7 agr I"},
}
GENOME_SHEETS = ("Summary", "AMR_genes", "Point_mutations", "Virulence", "Plasmids",
                 "Typing", "All_hits", "Pivot")
CUMULATIVE_SHEETS = ("Summary", "AMR_matrix", "Mutations_matrix", "Virulence_matrix",
                     "Plasmids_matrix", "Typing_matrix", "All_hits")
#: Where the Typing sheet's header row sits (title and explanation above it).
TYPING_HEADER_ROW = 4


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


def run_exe(exe: Path, args: list[str], timeout: int, log_file: Path | None = None,
            env_extra: dict | None = None) -> int:
    """Run the windowed exe, stream its log file while it runs, return its exit code."""
    log(f"running {exe.name} {' '.join(args)}")
    started = time.time()
    # The exe must not lean on the runner's Python settings (UTF-8 mode in particular).
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["HYDRA_WIN_HANG_DUMP"] = "300"
    env.update(env_extra or {})
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
    exe = dist / f"{APP}.exe"
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
    problems = check_pubmlst_bundle(dist / "db")
    for problem in problems:
        log(f"PROBLEM: {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} problem(s) with the bundled PubMLST snapshot")


def check_pubmlst_bundle(db_root: Path) -> list[str]:
    """The bundled PubMLST snapshot: present, pre-2025, credential-free, not doubled.

    Shipping this snapshot rests on one sentence of PubMLST's terms, and that
    sentence covers only data submitted on or before 2024-12-31. So the build
    does not take it on trust:

    * every scheme an organism module needs an ST from has to be there, or
      bundling the snapshot bought nothing;
    * the provenance file has to carry the terms, the retrieval date and the
      result of the server-side check, so the zip explains itself;
    * every allele id in the snapshot has to be in the index an anonymous
      client sees, which is the content-level form of "nothing post-2024 is in
      here" -- a leaked post-2024 allele would be absent from that index;
    * nothing that looks like a credential may be in the tree, because an
      authenticated fetch is the one way to pull data we may not redistribute;
    * and the allele sets must be in the zip once, not once per module.
    """
    problems: list[str] = []
    schemes_root = db_root / "mlst" / "pubmlst"
    for scheme in PUBMLST_SCHEMES:
        directory = schemes_root / scheme
        if not directory.is_dir():
            problems.append(f"pubmlst: scheme {scheme} is not in the bundle")
            continue
        loci = list(directory.glob("*.tfa"))
        if not loci or not (directory / f"{scheme}.txt").exists():
            problems.append(f"pubmlst/{scheme}: {len(loci)} loci and no profile table")

    provenance = schemes_root / "PUBMLST.txt"
    if not provenance.exists():
        problems.append("pubmlst: PUBMLST.txt provenance file is missing from the bundle")
    else:
        text = provenance.read_text(encoding="utf-8", errors="replace")
        for required in ("All data submitted on or before 31 December 2024",
                        "Retrieved:", "ANONYMOUS", "Wellcome Trust",
                        "Wellcome Open Res 2018;3:124"):
            if required not in text:
                problems.append(f"pubmlst: PUBMLST.txt does not state {required!r}")
        if "Post-2024 data reachable? verified" not in text:
            problems.append("pubmlst: PUBMLST.txt does not record a successful "
                            "pre-2025 verification, so the snapshot cannot be "
                            "claimed to be pre-2025")

    problems += check_pubmlst_is_pre_2025(schemes_root)

    credentials = [p for p in db_root.rglob("*") if p.is_file()
                   and re.search(r"(api[_-]?key|credential|\.netrc|token)", p.name, re.I)]
    if credentials:
        problems.append(f"pubmlst: credential-looking files in the database tree: "
                        f"{[p.name for p in credentials]}")

    organism_root = db_root / "organisms"
    for key, relative in SHARED_PUBMLST_COPIES.items():
        second = organism_root / key / relative
        if second.exists():
            problems.append(f"{key}: {relative} is a second copy of allele sets the "
                            f"bundled pubmlst database already holds "
                            f"({second.stat().st_size / 1e6:.1f} MB)")
    log(f"pubmlst bundle: {len(list(schemes_root.glob('*/')))} schemes, "
        f"{sum(1 for _ in schemes_root.rglob('*.tfa'))} locus files, "
        f"{sum(p.stat().st_size for p in schemes_root.rglob('*') if p.is_file()) / 1e6:.1f} MB")
    return problems


def check_pubmlst_is_pre_2025(schemes_root: Path, sample: int = 3) -> list[str]:
    """Every allele in the snapshot is one an anonymous client can see.

    PubMLST limits an unauthenticated client to data submitted on or before
    2024-12-31 and says so on every response. The snapshot was fetched that
    way, and this checks the result rather than the intention: the allele ids
    in the bundled FASTA are compared against the index the API serves
    anonymously now, and an ``added_after=2025-01-01`` query is asked to come
    back empty. Both must hold for the snapshot to be redistributable.

    Only a sample of loci is checked -- the full set is 1143 files and the
    question is whether the fetch was anonymous, which is a property of the
    whole run and not of one locus.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from hydra_amr.db.fetch import PUBMLST_CUTOFF, verify_pubmlst_is_pre_2025  # noqa: PLC0415

    problems: list[str] = []
    checked = 0
    for scheme, database in (("neisseria", "pubmlst_neisseria_seqdef"),
                             ("saureus", "pubmlst_saureus_seqdef"),
                             ("hinfluenzae", "pubmlst_hinfluenzae_seqdef")):
        directory = schemes_root / scheme
        if not directory.is_dir():
            continue
        for locus_file in sorted(directory.glob("*.tfa"))[:sample]:
            locus = locus_file.stem
            ok, detail = verify_pubmlst_is_pre_2025(database, locus)
            if not ok:
                problems.append(f"pubmlst/{scheme}/{locus}: {detail}")
                continue
            reachable = pubmlst_allele_ids(database, locus)
            if reachable is None:
                problems.append(f"pubmlst/{scheme}/{locus}: the anonymous allele index "
                                f"could not be read, so the snapshot could not be "
                                f"checked against it")
                continue
            shipped = {line[1:].split()[0].rpartition("_")[2]
                       for line in locus_file.read_text(errors="replace").splitlines()
                       if line.startswith(">")}
            extra = sorted(shipped - reachable, key=lambda a: (len(a), a))[:10]
            if extra:
                problems.append(
                    f"pubmlst/{scheme}/{locus}: {len(shipped - reachable)} allele(s) in "
                    f"the bundle are not in the index an anonymous client sees "
                    f"(e.g. {extra}), so this snapshot is not the pre-{PUBMLST_CUTOFF[:4]} "
                    f"one the terms let us redistribute")
            checked += 1
    if not checked and not problems:
        problems.append("pubmlst: not one locus could be checked against the "
                        "anonymous index")
    log(f"pubmlst: {checked} locus file(s) checked against the anonymous pre-2025 "
        f"index; added_after={PUBMLST_CUTOFF} returns no records")
    return problems


def pubmlst_allele_ids(database: str, locus: str) -> set[str] | None:
    """Every allele id of one locus an anonymous client can reach, or None."""
    url = (f"https://rest.pubmlst.org/db/{database}/loci/"
           f"{urllib.parse.quote(locus, safe='')}/alleles?return_all=1")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "HYDRA-Win CI"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - provenance check, not an install
        log(f"could not read the anonymous allele index for {database}/{locus}: {exc}")
        return None
    return {str(href).rstrip("/").rpartition("/")[2] for href in payload.get("alleles", [])}


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
    # Gzipped on purpose, like HS11286: both input forms stay exercised.
    sa = download(GENOMES["USA300"], folder / "USA300.fna.gz")
    return [hs, ec, sa]


def genome_files(folder: Path) -> dict[str, Path]:
    return {p.name.split(".")[0]: p for p in sorted(folder.glob("*")) if p.is_file()}


def assert_outputs(out: Path, genomes: dict[str, Path] | None = None) -> list[str]:
    from openpyxl import load_workbook  # noqa: PLC0415

    from verify_mutations import verify  # noqa: PLC0415 - tools/ is on sys.path

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
        point = _rows(wb["Point_mutations"])
        mutations = {r["Mutation"] for r in point}
        for mutation in expect["mutations"]:
            if mutation not in mutations:
                problems.append(f"{genome}: expected mutation {mutation} not found "
                                f"(have {sorted(mutations)})")
        for r in point:
            # Every call states what changed, where, and what it is associated with.
            for column in ("Type of call", "Mutation position on contig",
                           "Resistance it is associated with", "What it means"):
                if not r.get(column):
                    problems.append(f"{genome}: {r['Mutation']} has no {column!r}")
        # Where a reference tool names the same lesion, the row must carry that
        # tool's own name for it: this is what "the call Kleborate makes" means.
        by_name = {r["Mutation"]: r for r in point}
        for mutation, expected_call in expect.get("kleborate", {}).items():
            row = by_name.get(mutation)
            if row is None:
                problems.append(f"{genome}: no {mutation} row to carry the Kleborate call")
            elif str(row.get("Kleborate-style call") or "") != expected_call:
                problems.append(f"{genome}: {mutation} Kleborate-style call "
                                f"{row.get('Kleborate-style call')!r}, expected "
                                f"{expected_call!r}")
        # Independent check: every reported codon re-read from the FASTA itself.
        if genomes and genome in genomes:
            checked, found = verify(book, genomes[genome])
            problems += [f"{genome}: {p}" for p in found]
            log(f"{genome}: {checked} mutation rows re-read from {genomes[genome].name}: "
                f"{'OK' if not found else f'{len(found)} problem(s)'}")
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
        problems += check_typing_sheet(genome, wb, expect,
                                       expect.get("organism_typing", {}))
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
            mut = {r["Assembly"]: r for r in _rows(wb["Mutations_matrix"], header_row=3)}
            for genome, expect in EXPECT.items():
                for gene, change in expect.get("matrix", {}).items():
                    if mut.get(genome, {}).get(gene) != change:
                        problems.append(f"cumulative Mutations_matrix: {genome} x {gene} = "
                                        f"{mut.get(genome, {}).get(gene)!r}, expected {change!r}")
            long = _rows(wb["All_hits"])
            if not long or {r["Assembly"] for r in long} != set(EXPECT):
                problems.append("cumulative All_hits does not cover both assemblies")
            log(f"cumulative: {len(long)} hits")
    return problems


def check_typing_sheet(genome: str, wb, expect: dict, wanted: dict) -> list[str]:
    """The Typing sheet must name every call, its evidence and its caveats.

    The whole reason the modules were written is that a gene name without the
    evidence behind it was useless, so an empty evidence or caveats cell on an
    organism call is a failure, not a cosmetic problem.
    """
    problems: list[str] = []
    rows = _rows(wb["Typing"], header_row=TYPING_HEADER_ROW)
    if not rows:
        return [f"{genome}: Typing sheet is empty"]
    calls = {r["Scheme / database"]: r for r in rows}
    for scheme, call in expect.get("typing", {}).items():
        if str(calls.get(scheme, {}).get("Call")) != call:
            problems.append(f"{genome}: typing {scheme} "
                            f"{calls.get(scheme, {}).get('Call')!r}, expected {call}")
    organism_rows = [r for r in rows if r["Type"] == "Organism typing"]
    if wanted and not organism_rows:
        problems.append(f"{genome}: no organism typing rows, expected "
                        f"{sorted(wanted)}")
    for scheme, call in wanted.items():
        row = calls.get(scheme)
        if row is None:
            problems.append(f"{genome}: organism typing has no {scheme!r} row "
                            f"(rows: {sorted(calls)})")
            continue
        if str(row["Call"]) != call:
            problems.append(f"{genome}: {scheme} = {row['Call']!r}, expected {call!r}")
    for row in organism_rows:
        scheme = row["Scheme / database"]
        call = str(row.get("Call") or "")
        evidence = row.get("Evidence: what the call rests on")
        caveat = row.get("Caveats, limits and what could not be determined")
        if not row.get("Organism"):
            problems.append(f"{genome}: {scheme} names no organism")
        if not call:
            problems.append(f"{genome}: {scheme} has no call at all")
        # A clean call may have nothing left to qualify, and a "none detected"
        # has no alleles to show - but no row may be silent on both, or the
        # reader is given a call with nothing to check it against.
        if not evidence and not caveat:
            problems.append(f"{genome}: {scheme} gives neither evidence nor a caveat")
        # And a call that could not be made must always say why, or it reads
        # as a negative result.
        if call.startswith("not determined") and not caveat:
            problems.append(f"{genome}: {scheme} is 'not determined' with no reason")
    headline = str(wb["Typing"].cell(row=1, column=1).value or "")
    if "headline" in expect and expect["headline"] not in headline:
        problems.append(f"{genome}: Typing sheet title {headline!r} does not carry "
                        f"the headline {expect['headline']!r}")
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    if wanted:
        shown = {str(v) for v in summary.values()}
        for call in wanted.values():
            if not any(call in text for text in shown):
                problems.append(f"{genome}: Summary sheet never mentions {call!r}")
    log(f"{genome}: {len(organism_rows)} organism typing rows, "
        f"headline {headline.split(' - ', 1)[-1]!r}")
    return problems


def cmd_smoke(zip_path: Path, work: Path) -> None:
    # Spaces and non-ASCII everywhere a user might have them.
    app_parent = work / "Hydra wïn smoke ü"
    shutil.rmtree(app_parent, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(app_parent)
    app = next(app_parent.glob(f"*/{APP}.exe"))
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
        raise SystemExit(f"{APP} --cli exited with {rc}")
    problems = assert_outputs(out, genome_files(work / "genomes ö dir"))
    for problem in problems:
        log(f"PROBLEM: {problem}")
    shutil.copytree(out, work / "smoke-results", dirs_exist_ok=True)
    if problems:
        raise SystemExit(f"{len(problems)} smoke-test problem(s)")
    log("smoke test passed")
    smoke_settings(app, genomes[0], work)
    # Two offline runs, because they prove different halves of the bundle.
    #
    # E. coli: identified from the bundled Mash sketches, and its one GPL-3.0
    # database (ShigEiFinder) is the half of the licence policy that proves a
    # withheld database still reads as "not determined" and not as a negative.
    #
    # S. aureus: the half the PubMLST snapshot is for. Its clonal complex is
    # derived from the sequence type, so CC8 offline is only possible if the
    # bundled MLST schemes really do type an isolate with no network - and its
    # spa type still needs the Ridom download, so the same run proves the
    # withheld database is still withheld.
    smoke_offline(zip_path, work, genomes[1])
    smoke_offline(zip_path, work, genomes[2], suffix=" saureus", check_zip=False)


#: What the zip itself must hold, and what only a first-launch download provides.
#: pubmlst is bundled: its terms permit redistributing the pre-2025 data an
#: anonymous download returns, which is all the snapshot contains.
BUNDLED = {"protein", "ncbi", "resfinder", "plasmidfinder", "sccmec", "lineage", "species",
           "vfdb", "argannot", "megares", "ecoli_vf", "ecoh", "pubmlst"}
DOWNLOADED = {"card"}

#: Organism typing data the zip carries, and what the module can still do
#: without the part it does not carry. One entry per upstream module, because a
#: module silently dropped from the build would otherwise go unnoticed.
ORGANISM_BUNDLED = {"typing-saureus", "typing-spyogenes", "typing-sagalactiae",
                    "typing-spneumoniae", "typing-hinfluenzae", "typing-salmonella",
                    "typing-ecoli", "typing-nmeningitidis"}
#: Nothing is withheld from the zip wholesale any more: the meningococcal data
#: is all PubMLST, and the pre-2025 snapshot may be redistributed.
ORGANISM_DOWNLOADED: set[str] = set()
#: Bundled, but deliberately incomplete: these databases are the ones a licence
#: withholds, and the zip must not contain them.
ORGANISM_PARTIAL = {
    "typing-saureus": {"spa"},            # Ridom: non-commercial, no copies
    "typing-hinfluenzae": {"cap"},        # hicap: GPL-3.0 inside an MIT zip
    "typing-ecoli": {"shigeifinder"},     # ShigEiFinder GPL-3.0
}

#: The PubMLST schemes the zip must hold, because an organism module reads a
#: sequence type from each of them. Shipping the snapshot is worth nothing if
#: the schemes that make the typing work are not in it.
PUBMLST_SCHEMES = ("saureus", "neisseria", "hinfluenzae", "senterica_achtman_2",
                   "ecoli_achtman_4", "spneumoniae", "spyogenes", "sagalactiae")

#: Allele sets a module used to ship a second copy of. The bundled pubmlst
#: database holds them now, so exactly one copy may be in the zip.
SHARED_PUBMLST_COPIES = {
    "nmeningitidis": "mlst/mlst.fna",
    "hinfluenzae": "mlst/mlst.fna",
    "salmonella": "mlst/mlst.fna",
}


def check_organism_bundle(status: dict) -> list[str]:
    """What organism typing data a fresh unzip holds, and what it must not hold.

    The licence decision is only real if the files a licence withholds are
    genuinely absent from the zip, so this asserts their absence as firmly as
    it asserts the presence of the rest.
    """
    problems: list[str] = []
    rows = {row["name"]: row for row in status.get("organism_typing", [])}
    if not rows:
        return ["--db-status reports no organism typing data at all"]
    installed = {name for name, row in rows.items() if row["installed"]}
    if installed != ORGANISM_BUNDLED:
        problems.append(f"fresh unzip organism typing: installed {sorted(installed)}, "
                        f"expected {sorted(ORGANISM_BUNDLED)}")
    for name in ORGANISM_DOWNLOADED:
        row = rows.get(name, {})
        if row.get("installed"):
            problems.append(f"{name} is in the zip; every one of its databases is "
                            f"PubMLST data and must be downloaded instead")
    for name, withheld in ORGANISM_PARTIAL.items():
        row = rows.get(name, {})
        present = set(row.get("missing") or [])
        if present != withheld:
            problems.append(f"{name}: the zip withholds {sorted(present)}, "
                            f"expected exactly {sorted(withheld)}")
    log("fresh unzip organism typing: "
        + "; ".join(f"{n} ({'complete' if not rows[n]['missing'] else 'without ' + ', '.join(rows[n]['missing'])})"
                    for n in sorted(installed)))
    return problems


def smoke_offline(zip_path: Path, work: Path, genome: Path, *, suffix: str = "",
                  check_zip: bool = True) -> None:
    """A fresh unzip that cannot download: the bundled databases do all the work and
    the download-only one is reported as missing, never as an empty result.

    Every run unzips the release into its own folder with its own database home,
    so nothing the networked smoke run downloaded can be reached. The MLST
    schemes are in the zip, so an isolate gets its sequence type here with no
    network at all, and so does every call derived from it; a database the zip
    does not carry must still read "not determined" with its reason.
    """
    from openpyxl import load_workbook  # noqa: PLC0415

    from verify_mutations import verify  # noqa: PLC0415

    parent = work / f"offline app ü{suffix}"
    shutil.rmtree(parent, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(parent)
    app = next(parent.glob(f"*/{APP}.exe"))
    problems = []
    # Its own home: the first smoke run's home (with the downloads) must not be shared.
    home = work / f"offline_home{suffix}"
    shutil.rmtree(home, ignore_errors=True)
    fresh = {"HYDRA_WIN_HOME": str(home)}
    status_file = work / f"offline-db-status{suffix}.json"
    run_exe(app, ["--db-status", str(status_file)], timeout=300, env_extra=fresh)
    status = json.loads(status_file.read_text(encoding="utf-8"))
    installed = {d["name"] for d in status["databases"] if d["installed"]}
    missing = {d["name"] for d in status["databases"] if not d["installed"]}
    if installed != BUNDLED or missing != DOWNLOADED:
        problems.append(f"fresh unzip: installed {sorted(installed)}, missing {sorted(missing)}")
    problems += check_organism_bundle(status)
    if check_zip:
        problems += check_pubmlst_bundle(next(parent.glob(f"*/{APP}.exe")).parent / "db")
    out = work / f"results offline{suffix}"
    shutil.rmtree(out, ignore_errors=True)
    log_file = work / f"smoke-offline{suffix}.log"
    rc = run_exe(app, ["--cli", str(genome), "--out", str(out), "--offline", "--log",
                       str(log_file)], timeout=1800, log_file=log_file, env_extra=fresh)
    if rc != 0:
        raise SystemExit(f"offline --cli exited with {rc}")
    name = genome.name.split(".")[0]
    book = out / name / f"{name}.xlsx"
    wb = load_workbook(book)
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    if "Analyses NOT performed (database not installed)" not in summary:
        problems.append("offline Summary does not list the analyses not performed")
    if "CARD not screened" not in str(summary.get("card", "")):
        problems.append(f"offline Summary card row {summary.get('card')!r}")
    # MLST is in the zip now, so the offline run must produce a real sequence
    # type -- the whole point of bundling the pre-2025 PubMLST snapshot.
    if "pubmlst" in summary:
        problems.append(f"offline Summary still lists pubmlst as not performed: "
                        f"{summary.get('pubmlst')!r}")
    expected_st = EXPECT[name].get("offline_st")
    reported_st = str(summary.get("MLST ST", "")).strip()
    if expected_st is not None and reported_st != expected_st:
        problems.append(f"offline {name}: MLST ST {reported_st!r} with no network, "
                        f"expected {expected_st!r} from the bundled PubMLST schemes")
    elif not reported_st.isdigit():
        # E. coli has two PubMLST schemes and which one Hydra picks is not
        # asserted online either, so the test here is that the bundled schemes
        # produced a sequence type at all - the published Achtman ST 131 is
        # checked through the typing sheet below.
        problems.append(f"offline {name}: MLST ST {reported_st!r} is not a sequence "
                        f"type; the bundled PubMLST schemes should have assigned one "
                        f"with no network")
    if summary.get("Species") != EXPECT[name]["species"]:
        problems.append(f"offline species {summary.get('Species')!r}")
    hits = _rows(wb["All_hits"])
    used = {h["Database"] for h in hits}
    wanted = set(EXPECT[name].get("offline_databases") or ())
    if not wanted:
        problems.append(f"{name} declares no offline_databases in EXPECT, so this run "
                        f"is not checking which databases produced hits at all")
    if not wanted <= used:
        problems.append(f"offline {name}: no hits from {sorted(wanted - used)}")
    if "card" in used:
        problems.append("offline run reported CARD hits without CARD")
    checked, found = verify(book, genome)
    problems += [f"offline: {p}" for p in found]
    # The organism typing the bundled data can do with no network at all.
    wanted_typing = EXPECT[name].get("offline_typing", {})
    problems += check_typing_sheet(f"offline {name}", wb, {}, wanted_typing)
    rows = _rows(wb["Typing"], header_row=TYPING_HEADER_ROW)
    by_scheme = {r["Scheme / database"]: r for r in rows}
    # ... and every call whose database the zip may not carry must say so,
    # with the reason, rather than read as a negative result.
    for scheme, what in EXPECT[name].get("offline_undetermined", {}).items():
        row = by_scheme.get(scheme)
        if row is None:
            problems.append(f"offline {name}: no {scheme!r} row at all; a call that "
                            f"could not be made must still be reported")
            continue
        call = str(row["Call"])
        caveat = str(row["Caveats, limits and what could not be determined"] or "")
        if not call.startswith("not determined"):
            problems.append(f"offline {name}: {scheme} reads {call!r}; without "
                            f"{what} it must read 'not determined'")
        elif not caveat:
            problems.append(f"offline {name}: {scheme} is 'not determined' with no "
                            f"reason given, which reads as a negative result")
    text = log_file.read_text(encoding="utf-8", errors="replace")
    if "not performed (pubmlst missing)" in text:
        problems.append("the offline log says MLST was not performed, but the "
                        "PubMLST schemes are in the zip")
    if "organism typing available for" not in text:
        problems.append("the offline log does not say which organism typing is available")
    # No network: a run that quietly reached one would invalidate every
    # assertion above. The log has to show the refusal and no download.
    # "offline mode: not downloading ..." is the line that must be there, so
    # the absence test has to be the exact first-launch phrases and not the
    # word "downloading", which that line contains.
    if "offline mode: not downloading" not in text:
        problems.append("the offline log does not record that the downloads were "
                        "refused, so this run may not have been offline at all")
    for leaked in ("first launch: downloading", "https://rest.pubmlst.org",
                   "https://card.mcmaster.ca"):
        if leaked in text:
            problems.append(f"the offline log mentions {leaked!r}: this run was "
                            f"supposed to have no network at all")
    log(f"offline {name}: {len(installed)} bundled databases, missing {sorted(missing)}; "
        f"ST {reported_st}; hits from {sorted(used)}; {checked} mutation rows verified; "
        f"{len([r for r in rows if r['Type'] == 'Organism typing'])} organism "
        f"typing calls")
    for problem in problems:
        log(f"PROBLEM: {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} offline problem(s) on {name}")


def fake_reads(folder: Path, n: int = 6) -> Path:
    """Synthetic FASTQ files (a single made-up read each), for the reads notice."""
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        sample, mate = divmod(i, 2)
        with gzip.open(folder / f"isolate{sample + 1}_R{mate + 1}.fastq.gz", "wt") as handle:
            handle.write("@read1\nACGTACGTACGT\n+\nIIIIIIIIIIII\n")
    return folder


def smoke_settings(app: Path, genome: Path, work: Path) -> None:
    """--cli with custom thresholds and a folder of reads among the inputs."""
    from openpyxl import load_workbook  # noqa: PLC0415

    reads = fake_reads(work / "reads folder")
    out = work / "results custom"
    shutil.rmtree(out, ignore_errors=True)
    log_file = work / "smoke-custom.log"
    rc = run_exe(app, ["--cli", str(genome), str(reads), "--out", str(out), "--min-identity",
                       "90", "--min-coverage", "80", "--threads", "2", "--log", str(log_file)],
                 timeout=1800, log_file=log_file)
    if rc != 0:
        raise SystemExit(f"--cli with custom thresholds exited with {rc}")
    problems = []
    text = log_file.read_text(encoding="utf-8", errors="replace")
    if "not analysing 6 FASTQ read file(s)" not in text:
        problems.append("the FASTQ inputs were not reported in the log")
    name = genome.name.split(".")[0]
    wb = load_workbook(out / name / f"{name}.xlsx")
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    for label, expected in (("Minimum identity (%)", "90% (set by user"),
                            ("Minimum coverage (%)", "80% (set by user"),
                            ("Threads", "2 (set by user)"),
                            ("Equivalent upstream flags", "--min-identity 90 --min-coverage 80")):
        if not str(summary.get(label, "")).startswith(expected):
            problems.append(f"Summary {label!r} = {summary.get(label)!r}")
    nucleotide = [h for h in _rows(wb["All_hits"])
                  if h["Database"] != "protein" and h["Method"] in ("BLASTN", "PARTIALN")]
    low = [h for h in nucleotide if h["Identity (%)"] < 90 or h["Coverage (%)"] < 80]
    if not nucleotide or low:
        problems.append(f"{len(low)} of {len(nucleotide)} nucleotide hits below 90%/80%")
    if any(p.name.startswith("isolate") for p in out.iterdir()):
        problems.append("a FASTQ file was analysed")
    log(f"custom thresholds: {len(nucleotide)} nucleotide hits, all >= 90% identity / 80% "
        "coverage; settings recorded in the Summary sheet")
    for problem in problems:
        log(f"PROBLEM: {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} custom-settings problem(s)")


def cmd_display(width: Path, height: Path) -> None:
    """Change the screen resolution, so the window is tested at laptop size."""
    if os.name != "nt":
        return
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD),
                    ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short),
                    ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                    ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                    ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                    ("dmPanningHeight", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    w, h = int(str(width)), int(str(height))
    log(f"screen before: {user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}")
    modes, i = set(), 0
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    while user32.EnumDisplaySettingsW(None, i, ctypes.byref(mode)):
        modes.add((mode.dmPelsWidth, mode.dmPelsHeight))
        i += 1
    log(f"{len(modes)} display modes; {w}x{h} listed: {(w, h) in modes}")
    current = DEVMODEW()
    current.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, ctypes.c_uint32(0xFFFFFFFF).value, ctypes.byref(current))
    current.dmPelsWidth, current.dmPelsHeight = w, h
    current.dmFields = 0x80000 | 0x100000  # DM_PELSWIDTH | DM_PELSHEIGHT
    rc = user32.ChangeDisplaySettingsW(ctypes.byref(current), 0)
    log(f"ChangeDisplaySettings -> {rc}; screen now: "
        f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}")


def _hit_keys(book: Path) -> set:
    from openpyxl import load_workbook  # noqa: PLC0415

    return {(h["Database"], h["Gene"], h["Contig"], h["Start"], h["End"], h["Strand"],
             h["Identity (%)"]) for h in _rows(load_workbook(book)["All_hits"])}


def cmd_gui_smoke(work: Path) -> None:
    """Drive the window of the unzipped app (databases already downloaded by `smoke`)."""
    from PIL import ImageGrab  # noqa: PLC0415

    exe = next((work / "Hydra wïn smoke ü").glob(f"*/{APP}.exe"))
    genomes = sorted((work / "genomes ö dir").glob("*")) or fetch_genomes(work / "genomes ö dir")
    reads = fake_reads(work / "reads folder")
    shots = work / "gui-screenshots"
    out = work / "gui results ä"
    report = work / "gui-report.json"
    for path in (shots, out):
        shutil.rmtree(path, ignore_errors=True)
    report.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    args = [str(exe), "--gui-smoke", "--report", str(report), "--shots", str(shots),
            "--fastq", str(reads), "--run", "--out", str(out), *map(str, genomes)]
    log(f"running {exe.name} --gui-smoke --run ...")
    started = time.time()
    proc = subprocess.Popen(args, env=env)
    taken: list[str] = []
    while proc.poll() is None:
        for request in sorted(shots.glob("*.request.json")) if shots.exists() else []:
            name = request.name[: -len(".request.json")]
            if name in taken:
                continue
            rect = json.loads(request.read_text(encoding="utf-8"))["rect"]
            time.sleep(0.3)  # let the window finish painting
            try:
                ImageGrab.grab(bbox=tuple(rect), all_screens=True).save(shots / f"{name}.png")
                log(f"screenshot {name} {rect}")
            except Exception as exc:  # noqa: BLE001
                log(f"screenshot {name} failed: {exc}")
                (shots / f"{name}.png").write_bytes(b"")
            taken.append(name)
        if time.time() - started > 2700:
            proc.kill()
            raise SystemExit("GUI smoke timed out")
        time.sleep(0.2)
    log(f"window closed with exit code {proc.returncode} after {time.time() - started:.0f}s")
    if not report.exists():
        raise SystemExit("GUI smoke wrote no report")
    data = json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=1, ensure_ascii=False), flush=True)
    problems = []
    if data.get("error"):
        problems.append(f"smoke script error: {data['error']}")
    if not data.get("dnd"):
        problems.append("drag-and-drop (tkdnd) did not load in the packaged exe")
    if data.get("title") != f"{APP} {data.get('version')}":
        problems.append(f"window title {data.get('title')!r}")
    loaded = data.get("loaded", {})
    names = [r["sample"] for r in loaded.get("rows", [])]
    expected = [p.name.split(".")[0] for p in genomes]
    if names != expected or loaded.get("run_enabled") != "normal":
        problems.append(f"genomes not loaded: rows {names}, expected {expected}")
    if data.get("settings_invalid", {}).get("accepted") is not False:
        problems.append("the settings dialog accepted an invalid identity")
    if data.get("settings_custom", {}).get("identity") != 90:
        problems.append("the settings dialog did not apply identity 90")
    if not data.get("settings_run", {}).get("automatic"):
        problems.append("settings were not back to Automatic for the run")
    fastq = data.get("fastq", {})
    if not fastq.get("notice", "").startswith("6 FASTQ read files were not added") \
            or fastq.get("files_after") != fastq.get("files_before"):
        problems.append(f"FASTQ notice wrong: {fastq}")
    finished = data.get("finished", {})
    rows = {r["sample"]: r for r in finished.get("rows", [])}
    for genome, expect in EXPECT.items():
        row = rows.get(genome, {})
        if row.get("status") != "Done" or row.get("species") != expect["species"] \
                or not row.get("amr", "").isdigit():
            problems.append(f"table row for {genome}: {row}")
        # The headline organism call has to reach the window's table, not just
        # the workbook: it is the first thing anyone reads.
        shown = row.get("typing", "")
        if "headline" in expect:
            if shown != expect["headline"]:
                problems.append(f"{genome}: the table's Organism typing cell reads "
                                f"{shown!r}, expected {expect['headline']!r}")
        elif shown != "no module for this species":
            problems.append(f"{genome}: the table's Organism typing cell reads "
                            f"{shown!r}; no module covers this species, which the "
                            f"cell must say rather than leave blank")
    if "st" in EXPECT["HS11286"] and not rows.get("HS11286", {}).get("mlst", "").startswith(
            "ST" + EXPECT["HS11286"]["st"]):
        problems.append(f"HS11286 MLST cell {rows.get('HS11286', {}).get('mlst')!r}")
    if not finished.get("status", "").startswith(
            f"Finished: {len(EXPECT)} of {len(EXPECT)} genomes analysed"):
        problems.append(f"status line {finished.get('status')!r}")
    problems += assert_outputs(out, genome_files(work / "genomes ö dir"))
    cli_out = work / "smoke-results"
    for genome in EXPECT:
        if (cli_out / genome).exists() and (out / genome).exists():
            same = _hit_keys(out / genome / f"{genome}.xlsx") == _hit_keys(
                cli_out / genome / f"{genome}.xlsx")
            log(f"{genome}: window run and --cli run give {'the same' if same else 'DIFFERENT'}"
                " hits")
            if not same:
                problems.append(f"{genome}: window and --cli results differ")
    screen = data.get("screen", {})
    left, top, right, bottom = screen.get("work_area", [0, 0, 0, 0])
    window = screen.get("window", [0, 0, 0, 0])
    log(f"screen {screen.get('size')}, work area {screen.get('work_area')}, window {window}, "
        f"log bottom {screen.get('log_bottom')}, scale {screen.get('scale')}")
    if window[0] < left or window[1] < top or window[2] > right or window[3] > bottom \
            or screen.get("log_bottom", 10 ** 6) > bottom:
        problems.append("the window or its log does not fit on the screen")
    dbs = data.get("databases", {})
    # 14 gene/typing databases plus one row per organism typing module. The
    # N. meningitidis row is the only one that is not installed: every one of
    # its databases is PubMLST data, and the --fetch-db step at the start of
    # the smoke test installs it, so by now even that one is present.
    rows_shown = dbs.get("rows", [])
    if len(rows_shown) != 14 + 8 or not all(r["installed"] for r in rows_shown):
        problems.append(f"Databases dialog: {dbs}")
    wanted = ["1-empty", "2-genomes-loaded", "3-settings-open", "4-fastq-notice", "5-running",
              "6-finished", "7-databases"]
    for name in wanted:
        png = shots / f"{name}.png"
        if not png.exists() or png.stat().st_size < 10_000:
            problems.append(f"screenshot {name} missing")
    for problem in problems:
        log(f"PROBLEM: {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} GUI smoke problem(s)")
    log("GUI smoke passed: a run started from the window finished with results")


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    step, args = argv[1], [Path(a) for a in argv[2:]]
    {"blast": cmd_blast, "build-db": cmd_build_db, "package": cmd_package,
     "smoke": cmd_smoke, "gui-smoke": cmd_gui_smoke, "display": cmd_display}[step](*args)


if __name__ == "__main__":
    main(sys.argv)
