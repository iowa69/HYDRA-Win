Portable Windows build of [Hydra](https://github.com/iowa69/hydra) (vendored at commit `75ecbe8`) by Giovanni Lorenzin · IOWA-BioTech.

**Install:** unzip into a folder you can write to (Downloads or Desktop, not Program Files), then double-click `HYDRA-Win.exe`. Species identification, MLST and almost every database work with no network. On first launch HYDRA-Win downloads the four databases it may not ship: CARD, the Ridom *spa* database, hicap's capsule database and ShigEiFinder. If this PC cannot reach them, copy them from another PC (**Databases… → Import from folder…**). The README explains how to [read the results correctly](https://github.com/iowa69/HYDRA-Win#read-your-results-correctly).

**What's new in 0.7.0**

- **The AMR genes on the Summary are the ones NCBI's AMRFinderPlus reports.** HYDRA-Win now follows AMRFinderPlus's own rules: each gene family's own identity cut-off, and an allele name only for an exact match. Genes that only other databases list, mostly the bacterium's own efflux pumps and regulators, are shown on a separate line, **AMR genes in other catalogues only (not counted)**, and no longer counted. **Expect lower AMR gene counts than in 0.6.0 for most genomes**: the genes that dropped off were never acquired resistance.
- **Gene names say how sure the match is.** `blaKPC-2` means identical to KPC-2. `blaKPC (closest blaKPC-2)` means a KPC gene that is not identical to any known variant, so it may be a new one. The `AMR_genes` sheet has a new *Closest allele* column. Internal database names such as `fosA5_fam` no longer appear as gene names, and fusion genes carry both names (`aac(6')-Ie/aph(2'')-Ia`).
- **Fixed: a gene split by an insertion was reported as complete, and could hide the gene inside it.** In one case the high-level gentamicin resistance gene *aac(6')-Ie/aph(2'')-Ia* disappeared from the Summary. A split gene is now reported as partial, to check.
- **Fixed: a gene with a premature stop codon was counted as found.** It is now listed to check, with the reason.
- **A simpler README:** download, run, and how to read every line of the Summary. The technical detail moved to `docs\how-it-works.md`, `docs\databases.md` and `docs\building.md`, which are also in the zip.

**What was new in 0.6.0**

- **Sixty more species are identified from the whole genome**, not from their MLST scheme: the staphylococci, enterococci and streptococci, *Listeria*, *C. difficile*, *Pseudomonas*, *Acinetobacter*, *Stenotrophomonas*, the *B. cepacia* complex, *Haemophilus*, *Neisseria*, *Campylobacter*, *Vibrio* and others. An *S. argenteus* is no longer reported as *S. aureus*, an *A. pittii* no longer as *A. baumannii*, and a gonococcus gets its own resistance catalogue.
- **Only confident calls are counted.** An AMR gene is counted only when it is complete and matches its reference closely; everything else is listed under **AMR genes to check**, with the reason. Every hit stays on its sheet with a *Confident call* column.
- **Fixed:** `--import-db` and `--db-status=FILE` opened the window instead of running headless, and a database whose source states no version read `unknown` in the workbook.

**Databases and licences.** Which data ships in the zip follows the project owner's policy: a source that states no licence or terms is shipped; a source that expressly restricts redistribution is downloaded on your own PC. Two sets are downloaded although their licence would permit redistribution — hicap's *cap* database and ShigEiFinder's gene sets are GPL-3.0, which is copyleft, and this zip is MIT. The Ridom *spa* database is expressly limited to non-commercial use by people who download it themselves. CARD withholds redistribution without McMaster University's written consent. PubMLST is shipped because its terms expressly permit redistributing the pre-2025 data an anonymous download returns, and that is all the snapshot contains; commercial users should note that PubMLST requires a separate licence for data submitted from 2025 onwards, none of which is in this zip or reachable from it.

**Input:** FASTA assemblies (`.fasta`, `.fa`, `.fna`, `.fas`, optionally `.gz`). Reads (FASTQ) aren't analysed.

**Output:** one Excel workbook per genome (Summary, AMR_genes, Point_mutations, Virulence, Plasmids, Typing, All_hits, Pivot), plus an optional `Cumulative_results.xlsx` (Summary, AMR_matrix, Mutations_matrix, Virulence_matrix, Plasmids_matrix, Typing_matrix, All_hits).

**Headless:** `HYDRA-Win.exe --cli <fasta...> --out DIR [--cumulative] [--min-identity PCT] [--min-coverage PCT] [--threads N]`; `--import-db FOLDER` installs the downloaded databases from a copy; `--db-status` prints what is installed.

**Bundled databases:** NCBI AMRFinderPlus, ResFinder, PlasmidFinder, SCCmecFinder, Kleborate v3.2.4 typing loci and species sketches, HYDRA-Win's clinical species sketch (NCBI RefSeq), VFDB (core), ARG-ANNOT, MEGARes, E. coli VF, EcOH, the PubMLST 7-locus MLST schemes (pre-2025 snapshot), and the organism typing data for *S. aureus* (except spa), *S. pyogenes*, *S. agalactiae*, *S. pneumoniae*, *H. influenzae* (except the *cap* locus), *N. meningitidis* (all of it), *Salmonella* and *E. coli*/*Shigella* (except the Shigella/EIEC cluster). NCBI BLAST+ 2.16.0 is included too. See `db/DATABASES.txt` for sources, dates, licences and citations.
