Portable Windows build of [Hydra](https://github.com/iowa69/hydra) (vendored at commit `6d36c10`).

**Install:** unzip into a folder you can write to (Downloads or Desktop, not Program Files), then double-click `Hydra-win.exe`. On first launch, HYDRA-Win downloads the databases that can't be redistributed (PubMLST, CARD, VFDB, ARG-ANNOT, MEGARes, E. coli VF, EcOH). This needs an internet connection and takes a few minutes, and only happens once.

**Input:** FASTA assemblies (`.fasta`, `.fa`, `.fna`, `.fas`, optionally `.gz`). Reads aren't supported.

**Output:** one Excel workbook per genome (Summary, AMR_genes, Point_mutations, Virulence, Plasmids, Typing, All_hits, Pivot). There's also an optional `Cumulative_results.xlsx` with matrices that compare all genomes.

**Headless:** `Hydra-win.exe --cli <fasta...> --out DIR [--cumulative]`

**Bundled databases:**
- NCBI AMRFinderPlus
- ResFinder
- PlasmidFinder
- SCCmecFinder
- Kleborate v3.2.4 typing loci and species sketches

NCBI BLAST+ 2.16.0 is included too. See `db/DATABASES.txt` for licences and citations.
