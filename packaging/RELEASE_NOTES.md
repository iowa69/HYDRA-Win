Portable Windows build of [Hydra](https://github.com/iowa69/hydra) (vendored at commit `6d36c10`) by Giovanni Lorenzin · IOWA-BioTech.

**Install:** unzip into a folder you can write to (Downloads or Desktop, not Program Files), then double-click `HYDRA-Win.exe`. On first launch, HYDRA-Win downloads the databases that can't be redistributed (PubMLST, CARD, VFDB, ARG-ANNOT, MEGARes, E. coli VF, EcOH). This needs an internet connection, takes a few minutes and only happens once.

**What's new in 0.2.0**
- A redesigned window: the Hydra logo, name and credits in a header, a clear three-step flow (add genomes, choose output and options, run) and one Run button. It fits a 1366×768 laptop screen.
- Genomes are listed in a table: sample name (the name of its results folder and workbook), file, size and a live status (queued, running, done, failed), then species, MLST and the number of AMR genes and point mutations as each genome finishes. Files with the same name get `_2`, `_3`… and are highlighted, so nothing is overwritten.
- Assemblies only, and the window says so. FASTQ read files dropped or selected are not added, and one notice says how many were left out.
- Settings: minimum % identity and minimum % coverage (Automatic = upstream Hydra's own thresholds) and threads, also as `--min-identity`, `--min-coverage` and `--threads` in `--cli`. The values used are written into every workbook.
- One genome that fails no longer stops the others.
- The executable is now `HYDRA-Win.exe`. Databases a previous version downloaded into `%LOCALAPPDATA%\Hydra-win` are reused.

**Input:** FASTA assemblies (`.fasta`, `.fa`, `.fna`, `.fas`, optionally `.gz`). Reads (FASTQ) aren't analysed.

**Output:** one Excel workbook per genome (Summary, AMR_genes, Point_mutations, Virulence, Plasmids, Typing, All_hits, Pivot), plus an optional `Cumulative_results.xlsx` with matrices that compare all genomes.

**Headless:** `HYDRA-Win.exe --cli <fasta...> --out DIR [--cumulative] [--min-identity PCT] [--min-coverage PCT] [--threads N]`

**Bundled databases:**
- NCBI AMRFinderPlus
- ResFinder
- PlasmidFinder
- SCCmecFinder
- Kleborate v3.2.4 typing loci and species sketches

NCBI BLAST+ 2.16.0 is included too. See `db/DATABASES.txt` for licences and citations.
