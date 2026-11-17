Portable Windows build of [Hydra](https://github.com/iowa69/hydra) (vendored at commit `6d36c10`) by Giovanni Lorenzin · IOWA-BioTech.

**Install:** unzip into a folder you can write to (Downloads or Desktop, not Program Files), then double-click `HYDRA-Win.exe`. Twelve of the fourteen databases are in the zip. On first launch HYDRA-Win downloads the two whose terms forbid redistribution, PubMLST (MLST) and CARD; if this PC cannot reach them, import a copy from another PC (**Databases… → Import from folder…** or `--import-db`).

**What's new in 0.3.0**
- **Point mutations say what mutated.** For every call the `Point_mutations` sheet now starts with the AMRFinderPlus name (`gyrA_S83I`), the type of call, the protein change (`S83I`, `p.Ser83Ile`), the nucleotide change (`c.248G>T`), the isolate's codon read from the assembly (`ATC`), the reference codon, the base that changed, the position of the mutated codon on the contig, the gene's span, the resistance it is associated with, Kleborate's name for the *K. pneumoniae* loci, and one plain sentence. The reference codon of a protein mutation is a parsimony inference (AMRFinderPlus has no reference coding sequence for these proteins) and is labelled as such in its own column; rRNA and promoter bases come from the reference sequence.
- **Gene disruptions are named by their lesion**, as AMRFinderPlus names them: `ompK35_G134AfsTer11` (frameshift, with the net indel and where the new frame stops), premature stops with their codon, interruptions by inserted sequence, start-codon loss. A gene cut by a contig end is labelled as not evidence of disruption.
- `Mutations_matrix` cells state the change (`S83L; D87N`), the Summary sheets list each mutation with its resistance, and the Pivot shows the change for mutation rows.
- VFDB, ARG-ANNOT, MEGARes, *E. coli* VF and EcOH now ship in the zip.
- Downloads use the Windows proxy settings (including automatic configuration), the Windows certificate store and, if needed, Windows' own downloader; the real reason for any failure is logged and shown per database in the new **Databases…** dialog, with **Retry** and **Import from folder…**.
- A missing database is stated in the window and in every Summary sheet ("NO MLST: the PubMLST schemes are not installed…"), so it is never read as a negative result.
- Which mutations are called is unchanged (checked against upstream Hydra).

**Input:** FASTA assemblies (`.fasta`, `.fa`, `.fna`, `.fas`, optionally `.gz`). Reads (FASTQ) aren't analysed.

**Output:** one Excel workbook per genome (Summary, AMR_genes, Point_mutations, Virulence, Plasmids, Typing, All_hits, Pivot), plus an optional `Cumulative_results.xlsx` with matrices that compare all genomes.

**Headless:** `HYDRA-Win.exe --cli <fasta...> --out DIR [--cumulative] [--min-identity PCT] [--min-coverage PCT] [--threads N]`; `--import-db FOLDER` installs PubMLST/CARD from a copy.

**Bundled databases:** NCBI AMRFinderPlus, ResFinder, PlasmidFinder, SCCmecFinder, Kleborate v3.2.4 typing loci and species sketches, VFDB (core), ARG-ANNOT, MEGARes, E. coli VF, EcOH. NCBI BLAST+ 2.16.0 is included too. See `db/DATABASES.txt` for sources, dates, licences and citations.
