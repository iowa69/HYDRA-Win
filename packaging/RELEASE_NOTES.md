Portable Windows build of [Hydra](https://github.com/iowa69/hydra) (vendored at commit `0bad0b0`) by Giovanni Lorenzin · IOWA-BioTech.

**Install:** unzip into a folder you can write to (Downloads or Desktop, not Program Files), then double-click `HYDRA-Win.exe`. Twelve of the fourteen gene and typing databases, and the organism typing data for seven of the eight organisms, are in the zip. On first launch HYDRA-Win downloads what a licence does not let it carry: PubMLST (MLST), CARD, the Ridom *spa* database, hicap's *cap* database, ShigEiFinder and the *N. meningitidis* data. If this PC cannot reach them, import a copy from another PC (**Databases… → Import from folder…** or `--import-db`).

**What's new in 0.4.0**

- **Organism-specific typing, applied automatically from the species call.** Eight organisms:
  - ***Staphylococcus aureus*** — spa type, *agr* group, MLST clonal complex, SCCmec, Panton-Valentine leucocidin, *tst*, enterotoxin and haemolysin repertoires, *hlb* status and the Sa3int prophage that interrupts it, capsule serotype locus, immune evasion cluster type, ACME, *blaZ* operon
  - ***Streptococcus pyogenes*** — emm type and cluster with its tissue tropism, virulence and superantigen repertoire, prophage content, regulatory loci, adhesins
  - ***Streptococcus agalactiae*** — capsular serotype, alpha-like protein (Alp) type, surface proteins, pilus island type, marker genes, PBP2X substitutions
  - ***Streptococcus pneumoniae*** — capsular serotype, PBP type (1A:2B:2X) with the CDC reference MIC where that triplet is in the reference table, macrolide/lincosamide/tetracycline/fluoroquinolone determinants, pilus islets
  - ***Haemophilus influenzae*** — capsule type, PBP3 (*ftsI*) substitution pattern and rPBP3 group, β-lactam interpretation, MLST
  - ***Neisseria meningitidis*** — capsule serogroup, fine type, Bexsero antigen sequence type, MLST and clonal complex, resistance target alleles
  - ***Salmonella enterica*** — serovar from the antigenic formula, subspecies, H2 locus, pathogenicity islands, virulence plasmid, typhoidal markers, ST and eBurst group
  - ***Escherichia coli* and *Shigella*** — phylogroup, *fimH* allele, ST131 subclone, Shiga toxin subtype, pathotype, intimin subtype, ExPEC/UPEC panel
- **Every typing call now carries the evidence behind it and its caveats.** The `Typing` sheet is one row per call with the alleles, residues, identity, coverage, contig coordinates and database version the call was read from, and, beside it, what is provisional, what disagreed and what could not be determined. A call that could not be made is coloured and says why; "not determined" is never a negative result.
- **The headline call is in the window's table**, in the `Typing` sheet title and in both Summary sheets: `spa t008 · CC8 · agr I`.
- **New cumulative sheet `Typing_matrix`:** assemblies against typing schemes, the call in every cell, the organism above every column, and the caveat as the cell's comment — a whole batch compared at a glance.
- The existing sheets, the point-mutation detail and the mutation matrices are unchanged.
- `db\DATABASES.txt` now records, for every organism typing database, the exact source, the version or retrieval date, the licence in the source's own words, the redistribution status the source states, and the citation.
- Fixed in the vendored engine: BLAST+ 2.16.0 crashes on a translated search that finds nothing when `-max_target_seqs` is combined with more than one thread. Those searches now run single-threaded, which is what the virulence and toxin panels depend on.

**Databases and licences.** Which data ships in the zip follows the project owner's policy: a source that states no licence or terms is shipped; a source that expressly restricts redistribution is downloaded on your own PC. Two sets are downloaded although their licence would permit redistribution — hicap's *cap* database and ShigEiFinder's gene sets are GPL-3.0, which is copyleft, and this zip is MIT. PubMLST data is fetched anonymously and no API key is ever used; anonymous access returns only data submitted on or before 31 December 2024, which PubMLST's terms allow to be redistributed, so a sequence type assigned after that date reads "not determined" with that reason rather than being guessed.

**Input:** FASTA assemblies (`.fasta`, `.fa`, `.fna`, `.fas`, optionally `.gz`). Reads (FASTQ) aren't analysed.

**Output:** one Excel workbook per genome (Summary, AMR_genes, Point_mutations, Virulence, Plasmids, Typing, All_hits, Pivot), plus an optional `Cumulative_results.xlsx` (Summary, AMR_matrix, Mutations_matrix, Virulence_matrix, Plasmids_matrix, Typing_matrix, All_hits).

**Headless:** `HYDRA-Win.exe --cli <fasta...> --out DIR [--cumulative] [--min-identity PCT] [--min-coverage PCT] [--threads N]`; `--import-db FOLDER` installs the downloaded databases from a copy; `--db-status` prints what is installed.

**Bundled databases:** NCBI AMRFinderPlus, ResFinder, PlasmidFinder, SCCmecFinder, Kleborate v3.2.4 typing loci and species sketches, VFDB (core), ARG-ANNOT, MEGARes, E. coli VF, EcOH, and the organism typing data for *S. aureus* (except spa), *S. pyogenes*, *S. agalactiae*, *S. pneumoniae*, *H. influenzae* (PBP3 and β-lactamases), *Salmonella* and *E. coli*/*Shigella* (except the Shigella/EIEC cluster). NCBI BLAST+ 2.16.0 is included too. See `db/DATABASES.txt` for sources, dates, licences and citations.
