# HYDRA-Win

<p align="center">
  <a href="https://github.com/iowa69/HYDRA-Win/releases/latest/download/HYDRA-Win-windows-x64.zip">
    <img src="https://img.shields.io/badge/%E2%AC%87%20Download%20HYDRA--Win%20for%20Windows-2ea44f?style=for-the-badge" alt="Download HYDRA-Win for Windows" height="56">
  </a>
  <br>
  <sub>One zip, about 70 MB. Unzip, double-click <code>Hydra-win.exe</code>. No install.</sub>
</p>

A portable Windows app for the bacterial genome analyser
[Hydra](https://github.com/iowa69/hydra). Give it genome assemblies and it reports
acquired AMR genes, resistance point mutations, virulence factors, plasmid replicons,
MLST, lineage and serotype typing, and resistance/virulence scores, in one Excel
workbook per genome.

You don't install anything. There's no conda, no admin rights and no console window.

## Get started

1. Click the green **Download** button above (or get `HYDRA-Win-windows-x64.zip` from
   [Releases](https://github.com/iowa69/HYDRA-Win/releases)).
2. Unzip it into a folder you can write to, for example *Downloads* or *Desktop*
   (not *Program Files*).
3. Double-click `Hydra-win.exe`.

The first time it starts, HYDRA-Win downloads the databases it isn't allowed to
redistribute (see [Databases](#databases)). This needs an internet connection and takes
a few minutes. It only happens once.

**Using it:** drag FASTA files or folders onto the window, or click **Select files**.
Then choose a results folder, tick **Cumulative_results** if you want an extra workbook
that compares all the genomes, and click **Run analysis**. When it's done, click
**Open results folder**.

**Input:** assemblies only. The accepted extensions are `.fasta`, `.fa`, `.fna` and
`.fas`, each optionally gzipped (`.gz`). If you drop a folder, HYDRA-Win searches it
recursively.

### Headless mode

```
Hydra-win.exe --cli genome1.fasta genome2.fna.gz --out C:\results --cumulative
```

This runs the same code path as the window. Other options:

| Option | What it does |
| --- | --- |
| `--threads N` | Number of threads to use |
| `--offline` | Don't download missing databases |
| `--log FILE` | Also write the log to `FILE` |
| `--db-status` | Report which databases are installed |
| `--fetch-db` | Download the first-launch databases, then exit |
| `--version` | Print the version |

Every run also writes `hydra-win.log` into the results folder.

## Output

For each genome, `<results>\<genome>\<genome>.xlsx` contains these sheets:

| Sheet | Contents |
| --- | --- |
| `Summary` | Species, MLST scheme/ST/profile, scores (resistance 0-3, ESBL, carbapenemase, colistin, virulence), counts per category, detected genes per category, lineage/serotype typing, assembly QC, and database versions and thresholds |
| `AMR_genes` | Every acquired AMR hit and every stress hit (biocide/metal/heat) |
| `Point_mutations` | Resistance point mutations and gene disruptions, with the mutation (for example `gyrA_S83I`) |
| `Virulence` | Virulence factor hits |
| `Plasmids` | Plasmid replicon hits |
| `Typing` | Species call, MLST, every lineage/serotype/element scheme, and serotype loci |
| `All_hits` | Every hit in every category |
| `Pivot` | One row per locus, grouped by category and drug class, with one column per database. Each cell holds that database's % identity and is colour-coded |

Every hit row has the contig, start, end and strand, plus gene, database, % identity,
% coverage, drug class/subclass, product, accession, element type, method, resolution
and note.

When several databases find the same locus, upstream Hydra marks one call as primary.
The other calls stay in the sheets in grey, with `Primary call = no`. They aren't
counted.

Colours: green for 100% identity, then light green, yellow, orange and red as identity
falls. Point mutations are blue. Italic means partial coverage.

With **Cumulative_results** (and two or more genomes), `<results>\Cumulative_results.xlsx`
contains:

| Sheet | Contents |
| --- | --- |
| `Summary` | One row per assembly |
| `AMR_matrix` | Assembly × gene matrix of primary calls, colour-coded by identity, with the drug class above each gene |
| `Mutations_matrix` | Same layout, for point mutations |
| `Virulence_matrix` | Same layout, for virulence genes |
| `Plasmids_matrix` | Same layout, for plasmid replicons |
| `All_hits` | Every hit, with an `Assembly` column |

## What is (and isn't) included

HYDRA-Win runs upstream Hydra's own analysis code. It uses a pinned copy of
`hydra_amr` from [iowa69/hydra](https://github.com/iowa69/hydra) at commit `6d36c10`,
with two small, documented Windows patches (see `src/hydra_amr/VENDORED.txt`). The
settings match upstream's `--preset deep`:

* every installed gene database
* AMRFinderPlus translated search with `--plus` elements
* point mutations
* MLST
* lineage and element typing
* scores

Two pieces are added for Windows:

* **Species identification.** Upstream uses Mash, which has no Windows build.
  HYDRA-Win includes a pure-Python re-implementation of `mash dist` and runs it against
  Kleborate's species sketches. It gives the same shared-hash counts as Mash 2.3 on the
  test genomes. Upstream's species rules are then applied unchanged. Without it,
  upstream's MLST-only fallback names some *Klebsiella* genomes as *E. coli*.
* **BLAST+ path handling.** BLAST+ on Windows can't cope with spaces or non-ASCII
  characters in paths. HYDRA-Win runs it from an ASCII, space-free folder (the 8.3
  short name, or `%LOCALAPPDATA%\Hydra-win`) and passes it relative paths, so the app
  works from folders like `C:\Users\Jörg Müller\Downloads`. Its databases are built in
  BLAST's version-4 format, which has no LMDB index; on Windows each LMDB file takes up
  its full gigabyte-sized map.

**Limitations**

* **Reads aren't supported.** There's no FASTQ input and no heteroresistance or
  allele-fraction analysis. Upstream's read mode needs minimap2, samtools and pysam,
  and none of them runs natively on Windows. Use upstream Hydra on Linux or macOS for
  reads.
* **`vfdb_full` isn't used.** Upstream can't download it automatically, it overlaps
  with the core VFDB set, and it's by far the slowest search.
* The species sketches cover Enterobacterales. Other genera are named from their MLST
  scheme, as in upstream.
* PubMLST, CARD, VFDB, ARG-ANNOT, MEGARes, *E. coli* VF and EcOH need an internet
  connection on the first launch.

## Databases

The release workflow builds databases from their upstream sources with upstream
Hydra's own fetchers. Whether a database ships inside the zip depends on its licence.

| Database | How you get it | Licence / terms | Citation |
| --- | --- | --- | --- |
| NCBI AMRFinderPlus (protein, point mutations, nucleotide) | in the zip | Public domain | Feldgarden et al. 2021, Sci Rep 11:12728 |
| ResFinder | in the zip | Apache-2.0 | Bortolaia et al. 2020, J Antimicrob Chemother 75:3491 |
| PlasmidFinder | in the zip | Apache-2.0 | Carattoli et al. 2014, Antimicrob Agents Chemother 58:3895 |
| SCCmecFinder | in the zip | Apache-2.0 | Kaya et al. 2018, mSphere 3:e00612-17 |
| Kleborate typing loci and species sketches (v3.2.4) | in the zip | GPL-3.0 | Lam et al. 2021, Nat Commun 12:4188; Ondov et al. 2016, Genome Biol 17:132 |
| PubMLST 7-locus schemes | first launch | PubMLST terms (redistribution of downloaded data restricted since 2025) | Jolley, Bray & Maiden 2018, Wellcome Open Res 3:124 |
| CARD | first launch | CARD terms (free for academic/non-commercial use, no redistribution) | Alcock et al. 2023, Nucleic Acids Res 51:D690 |
| VFDB (core) | first launch | No redistribution licence stated | Liu et al. 2022, Nucleic Acids Res 50:D912 |
| ARG-ANNOT | first launch, from abricate's repository | No redistribution licence stated | Gupta et al. 2014, Antimicrob Agents Chemother 58:212 |
| MEGARes | first launch, from abricate's repository | No redistribution licence stated | Bonin et al. 2023, Nucleic Acids Res 51:D744 |
| *E. coli* VF | first launch, from abricate's repository | No explicit data licence | [phac-nml/ecoli_vf](https://github.com/phac-nml/ecoli_vf) |
| EcOH | first launch, from abricate's repository | No explicit data licence | Ingle et al. 2016, Microb Genom 2:e000064 |

The `db` folder in the zip contains `DATABASES.txt` and the licence texts.

If a first-launch download fails, the analysis still runs with the databases that are
available. The `Summary` sheet lists what was missing, and the download is retried on
the next run. Commercial users must check the CARD and PubMLST terms themselves.

NCBI BLAST+ 2.16.0 is in the zip under `blast\`. It's public domain; see
`blast\LICENSE`. It comes with the Microsoft Visual C++ runtime DLLs it needs, which
are deployed app-locally.

## Building

The Windows build runs on GitHub Actions (`.github/workflows/build.yml`) and goes
through these steps:

1. Unit tests
2. PyInstaller (`--onedir`, windowed)
3. BLAST+
4. Database build with the packaged exe
5. Zip
6. Smoke test of the packaged exe: first launch, then `--cli --cumulative` on two public
   NCBI genomes (*K. pneumoniae* HS11286 and *E. coli* EC958), with assertions on
   sheets, hits, coordinates and known genes and mutations
7. GUI start-up test

A `v*` tag publishes the zip as a release.

To run from source (Linux, macOS or Windows), with BLAST+ on `PATH`:

```
pip install -r requirements.txt
python -m hydra_win             # window
python -m hydra_win --cli ...   # headless
python -m pytest -q
```

`tools/compare_upstream.py` checks a HYDRA-Win output folder against upstream
`hydra run --preset deep --format json` on the same genomes and databases.

## Credit and licence

HYDRA-Win is MIT-licensed (see `LICENSE`). The analysis is upstream
[Hydra](https://github.com/iowa69/hydra), also MIT; its licence is kept in
`src/hydra_amr/LICENSE`. Please cite Hydra and the databases you rely on.
