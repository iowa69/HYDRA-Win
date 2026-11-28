# How HYDRA-Win makes its calls

Back to the [README](../README.md).

HYDRA-Win runs upstream Hydra's own analysis code. It uses a pinned copy of `hydra_amr`
from [iowa69/hydra](https://github.com/iowa69/hydra) at commit `75ecbe8` (released
upstream as Hydra 1.4.0), with six documented patches listed in
`src/hydra_amr/VENDORED.txt`: two for Windows, and four that belong upstream. With
Automatic settings it runs every installed gene database, the AMRFinderPlus protein
search with its `--plus` elements, point mutations, MLST, lineage and element typing,
the organism-specific typing for the species found, and the scores.

## Resistance genes

HYDRA-Win doesn't run NCBI's `amrfinder` program, which NCBI builds for Linux and macOS
only. It searches AMRFinderPlus's own database with upstream Hydra's BLAST code, and
applies AMRFinderPlus's own rules, read from that database and from NCBI's source code
(`amr_report.cpp`):

* **NCBI's curated identity cut-off for each gene family** (98% for the *aac(3)* and
  *dfrA* families, 85% for *cfr*, for example), moving up to the parent family when a
  hit misses its own family's cut-off, and 90% where NCBI sets none, over 90% of the
  protein.
* **An allele name only for an exact match.** Anything less is named by its family,
  with the closest allele next to it: `blaKPC (closest blaKPC-2)`. One amino acid can be
  a different allele with a different phenotype (KPC-33 is KPC-2 plus D179Y).
* A TTG or GTG start codon reads as methionine. A premature stop codon makes the call
  `INTERNAL_STOP`. A fusion gene carries both its names (`aac(6')-Ie/aph(2'')-Ia`). Two
  pieces of a gene separated by an insertion are not joined into one "complete" gene.
* A gene family NCBI marks as not reportable is not reported (*Salmonella*'s
  chromosomal *aac(6')-Iy*, for example).

The nucleotide databases (NCBI, CARD, ResFinder, ARG-ANNOT, MEGARes) are searched too,
with the thresholds in [Settings](../README.md#settings), and their hits are all on the
`AMR_genes` sheet.

### What the Summary counts

The settings decide what is *found*. What is *counted* is fixed: the Summary, the window
and `Cumulative_results.xlsx` count an AMR gene only when it is a **confident call**:

* at least one database at that locus matches it at **>= 90% identity over >= 90% of
  the reference gene** (in the AMRFinderPlus protein search, at the family's curated
  cut-off instead);
* complete: not cut by a contig end, no internal stop codon, not split by inserted
  sequence;
* and **the AMRFinderPlus protein search calls it too**. MEGARes and ARG-ANNOT also hold
  the chromosomal efflux pumps, regulators and housekeeping genes NCBI leaves out of
  AMRFinderPlus on purpose (*acrA*, *cpxAR*, *mexQ*). A confident call that only such a
  catalogue makes is listed under **AMR genes in other catalogues only (not counted)**,
  and its sheet row says `not counted: AMRFinderPlus does not report this gene`.

Every other AMR hit is listed under **AMR genes to check**, with the reason
(`blaTEM-1 (partial: 72.4% of the reference gene)`), and every hit stays on its sheet
with a **Confident call** column. A drug class is listed when a counted gene *or* an
established point mutation is behind it, so `gyrA` S83I puts quinolones on the Summary
with no *qnr* gene present.

### Known differences from AMRFinderPlus

`tools/compare_amrfinder.py` compares HYDRA-Win with `amrfinder` itself on public
genomes (`docs/amrfinder_comparison.md`). Three differences remain by design or by
constraint:

* There is no HMM search: HMMER is not in the Windows bundle. A gene AMRFinderPlus keeps
  or drops only on its HMM can therefore differ.
* AMRFinderPlus's mosaic-PBP calls (*S. pneumoniae* *pbp1a*/*pbp2b*/*pbp2x*, the
  gonococcal *penA*) are not made, because upstream Hydra does not import the database
  file they come from (`AMRProt-susceptible.fa`). The PBP point mutations themselves
  are reported.
* A partial gene at a contig end is reported as partial, not as "contig end". Either way
  it is listed to check, not counted.

## Point mutations and gene disruptions

Every call in `Point_mutations` states, without decoding:

| Column | Example (HS11286 *gyrA*) | Example (HS11286 *ompK35*) |
| --- | --- | --- |
| Mutation (AMRFinderPlus name) | `gyrA_S83I` | `ompK35_G134AfsTer11` |
| Type of call | Amino-acid substitution | Gene disruption: frameshift |
| Protein change / HGVS | `S83I` / `p.Ser83Ile` | `G134AfsTer11` / `p.Gly134AlafsTer12` |
| Nucleotide change | `c.248G>T (inferred)` | `c.401delG (inferred)` |
| Isolate codon / base (read from the assembly) | `ATC` | new frame from codon 134 stops at `TGA` (NC_016845.1:1904952-1904954) |
| Reference codon (INFERRED by parsimony) | `AGC` | |
| Base changed | G>T at codon position 2 | net 1-bp deletion |
| Mutation position on contig | NC_016845.1:3738482-3738484 (-) | NC_016845.1:1904986-1904990 (-) |
| Intact reference | | residues 1-133 of 359 (37%) |
| Resistance it is associated with | quinolone resistance | carbapenem resistance; loss of function |
| Kleborate-style call | `GyrA:p.Ser83Ile` | `OmpK35:p.Trp133fs` |

followed by *What it means* (one sentence), *Basis of the base change* and *Not
resolved*, then the raw hit columns.

* **The isolate's codon is read from the assembly**: the alignment is walked to the
  mutated residue, so the strand, indels before the position and contig ends are
  handled, and the codon is re-translated as a check.
* **Where the reference base comes from.** For the DNA loci of the AMRFinderPlus
  catalogue (rRNA, promoters) it is read from the catalogue's reference sequence.
  AMRFinderPlus ships proteins, not coding sequences, for the point-mutation genes, so
  for a protein mutation (and the codon behind a premature stop or frameshift) the
  reference codon is the codon for the reference amino acid closest to the isolate's
  codon. That is an inference: it has its own column, the nucleotide change is marked
  *(inferred)*, and when two codons are equally close nothing is claimed.
* **Gene disruptions are named by their lesion**, the way AMRFinderPlus names them
  (`ompK35_G134AfsTer11`, `mgrB_Q30Ter`): premature stop (codon and base change),
  frameshift (the net indel, where the new frame stops, the HGVS `fsTer`, and the
  deleted or inserted base when only one change restores the protein, marked
  *inferred*), interruption by inserted sequence (its size; the element itself is not
  identified), start codon lost, or 5' part absent. AMRFinderPlus counts the novel
  residues before the stop (`fsTer11`); HGVS counts the stop as well (`fsTer12`).
* **A gene cut by a contig edge is reported, and the row says so.** The call is never
  suppressed — a gene running off the end of a contig is a real finding, and hiding it
  would hide the gene behind an assembly artefact. But it is not a confirmed loss of
  function, and no part of the row lets it pass for one:

  | Where | What it says |
  | --- | --- |
  | *Type of call* | **Gene cut by a contig end: NOT evidence of disruption, loss of function not assessed** |
  | *Element subtype* | `DISRUPTION_AT_CONTIG_END` |
  | *Resolution* | `CONTIG_END` |
  | *Note* | leads with "runs off the end of contig …, so the gene is cut by the assembly: this is NOT evidence of disruption and loss of function could not be assessed. Reported rather than suppressed, but it is not a confirmed loss-of-function call" |
  | *Resistance it is associated with* | "loss of function not established: the gene is cut by a contig end" — and what a confirmed one *would* have meant |
  | matrix and pivot cells | `cut by contig end - not assessed`, struck through and greyed |

  The resistance score ignores such a row too: the row is reported in full, but a
  lesion that could not be assessed is not counted as resistance that is present.
  AMRFinderPlus reports the same situation as `PARTIAL_CONTIG_END`.
* **Kleborate's name** is given for the *K. pneumoniae* loci Kleborate types (GyrA,
  ParC, OmpK35, OmpK36, MgrB, PmrB).
* Anything that cannot be resolved to a codon (a position in an alignment gap, a codon
  past a contig end, a mosaic allele) says so in *Not resolved*.

## Organism-specific typing

Once the species is known, HYDRA-Win applies the typing a clinical or public-health
laboratory actually reports for that organism. Nothing has to be chosen: the species
call selects the schemes, and the MLST scheme selects them when there is no species
call.

| Organism | What is typed | Works with no internet |
| --- | --- | --- |
| *Staphylococcus aureus* | spa type (Ridom), *agr* group, MLST clonal complex, SCCmec, Panton-Valentine leucocidin, *tst*, enterotoxin and haemolysin repertoires, *hlb* status (and the Sa3int prophage that interrupts it), capsule serotype locus, immune evasion cluster type, ACME, *blaZ* operon | everything **except the spa type**, which needs the Ridom download |
| *Streptococcus pyogenes* | emm type and emm cluster with its tissue tropism, virulence and superantigen repertoire, prophage content, regulatory loci, adhesins | everything |
| *Streptococcus agalactiae* | capsular serotype, alpha-like protein (Alp) type, surface proteins, pilus island type, marker genes, PBP2X substitutions | everything |
| *Streptococcus pneumoniae* | capsular serotype, PBP type (1A:2B:2X) with the CDC reference MIC where that triplet is in the reference table, macrolide/lincosamide/tetracycline/fluoroquinolone determinants, pilus islets | everything |
| *Haemophilus influenzae* | capsule type (*cap* locus), PBP3 (*ftsI*) substitution pattern and rPBP3 group, β-lactam interpretation, MLST | everything **except the capsule type**, which needs the first-launch download of hicap's GPL-3.0 *cap* database |
| *Neisseria meningitidis* | capsule serogroup (with the lesion, where the locus carries one), fine type, Bexsero antigen sequence type (BAST) and MenDeVAR index, MLST and clonal complex, resistance target alleles | **everything**: all of its data is PubMLST nomenclature, and the pre-2025 snapshot is now in the zip |
| *Salmonella enterica* | serovar from the antigenic formula, subspecies, H2 (*fljB*) locus, pathogenicity islands, virulence plasmid, typhoidal markers, ST and eBurst group | everything |
| *Escherichia coli* and *Shigella* | phylogroup (Clermont), *fimH* allele, ST131 subclone, Shiga toxin subtype, pathotype, intimin (*eae*) subtype, ExPEC/UPEC virulence panel | everything **except the *Shigella*/EIEC cluster call** |

Each call is reported with the evidence it rests on and with its caveats, on its own row
of the `Typing` sheet. For example, *S. aureus* USA300 FPR3757:

| Scheme | Call | Evidence | Caveats |
| --- | --- | --- | --- |
| spa type (Ridom) | `t008` | `repeat_succession = 11-19-12-21-17-34-24-34-22-25`, `repeats = 10`, `region = NC_007793.1:128391-128785 (395 bp)` | spa types are tandem arrays and short-read assemblies lose repeats in about 1-15% of isolates depending on the assembler (Mollerup 2022), so confirm before acting on a single-repeat difference |
| β-haemolysin (*hlb*) status | `disrupted by prophage integration` | `hlb = 100.0% identity over 1-993/993`, `alignments = 2`, `contig_gap_bp = 43036` | the two alignment pieces are 43 kb apart with the break at base 183 of 993: the signature of a β-haemolysin-converting (Sa3int) prophage inside *hlb*. β-haemolysin is therefore not produced, despite *hlb* being 100% covered |
| MLST clonal complex | `CC8` | `ST = 8`, `profile = 3-3-1-1-4-4-3`, `nearest_founders = CC8 (7/7), CC239 (6/7), CC9 (4/7)` | ST8 is the founder of CC8 (7/7 loci shared) |

The headline calls (`spa t008 · CC8 · agr I`) are in the **Organism typing** column of
the window's table, in the title of the `Typing` sheet, in the genome `Summary` sheet
and in the cumulative `Summary` and `Typing_matrix` sheets.

### The honest limits

* **"Not determined" is never a negative result.** Every undetermined call says why: a
  database that is not installed, a locus that reaches a contig end, a profile that is
  incomplete, an allele newer than the data. Undetermined calls are coloured in the
  `Typing` sheet so they cannot be skimmed past.
* **A capsule call states the type first and the lesion with it.** A meningococcus that
  carries a serogroup B locus it cannot express reads `B (capsule gene disrupted)`, not
  a bare `NG` with the genogroup hidden in another column — the laboratory's
  non-groupable result and the genome's genogroup are both true and belong together, and
  these lesions revert. The gene-by-gene evidence and the caveat are in the same row:
  which gene, what is wrong with it, that the laboratory will report non-groupable, and
  that an insertion-sequence or slipped-strand switch can turn the capsule back on. A
  capsule gene cut by a contig end is a third, distinct wording —
  `B (capsule gene at a contig end, expression not assessed)` — because an assembly
  boundary is neither an intact capsule nor a lesion. The same shape is used for
  *H. influenzae*: a single-copy *cap* locus with *bexA* truncated reads
  `b (capsule gene disrupted)`, while the normal virulent Hib arrangement (a duplicated
  locus with one *bexA* truncated) stays plain `b`.
* **Everything is read from the assembly.** A scheme that needs reads is not attempted.
  Repeat arrays (*spa*) and long loci (*cap*, *cps*, SCCmec) can be collapsed or split
  by a short-read assembler, which the caveats say for each affected call.
* **A locus that is present is not a locus that is expressed.** USA300 carries an intact
  *cap5* locus and does not make capsule; the caveat says so.
* **Where a call depends on the ST, it says so.** The *E. coli* ST131 subclone label
  (H30) is only meaningful if the Achtman ST is 131, which the row states.
* **PubMLST data is fetched anonymously and no API key is ever used.** Anonymous access
  returns only data submitted on or before 31 December 2024, which PubMLST's terms allow
  to be redistributed — which is what lets the snapshot ship in the zip and MLST work
  offline. A sequence type assigned after that date therefore reads *not determined*,
  with that reason, instead of being guessed. See
  [PubMLST: why the MLST schemes are now in the zip](databases.md#pubmlst-why-the-mlst-schemes-are-now-in-the-zip).
* **Serogroups W and Y are told apart on the sequence, not on a threshold.** They differ
  by one gene and those two genes (*csw*, *csy*) are 99% identical, so both clear any
  identity cut-off a protein search can set. The call goes to whichever serogroup's own
  gene the isolate matches better, the two scores are in the row's evidence, and when
  they are too close to separate the row says so and asks for serology or a
  serogroup-specific PCR.
* **Eight meningococcal serogroups are validated against genomes with published
  serogroups** — A, B, C, W, X, Y, E and Z, plus the capsule-null locus, 18 genomes in
  all, tabulated with their sources in upstream's
  [`docs/typing/hinf_nmen.md`](https://github.com/iowa69/hydra/blob/main/docs/typing/hinf_nmen.md).
  Serogroups **L and H are implemented but unvalidated** — no public assembly with a
  published L or H serogroup could be found — and a call of either says so in its own
  caveat rather than looking as solid as the other eight.
* **No MIC is predicted unless a reference laboratory published the value.** The
  pneumococcal PBP type gives the CDC reference MIC only for a 1A:2B:2X triplet that is
  in the CDC table, and declines otherwise. The nearest-neighbour mode-MIC model was
  looked up and deliberately not built: in its own validation it gave very major error
  rates above 50% for three of six β-lactams, meaning resistant isolates called
  susceptible.
* **Marker rules are screens, not diagnoses.** An ExPEC or UPEC genotype says what the
  isolate could do, not where it was grown or what it caused.
* **Group C/G streptococci are not group A.** The CDC emm database also holds the
  `stG`/`stC`/`stL` types of *S. dysgalactiae*. A *S. dysgalactiae* isolate is not put
  through the *S. pyogenes* module, and if one of those records is the best match in a
  genome called as *S. pyogenes*, the heading says *S. dysgalactiae* rather than "emm
  type" so it cannot be read as a group A type.
* Full method, thresholds, provenance, validation tables and bibliography for every
  scheme are in upstream Hydra's
  [`docs/typing/`](https://github.com/iowa69/hydra/tree/main/docs/typing).

## The workbooks in detail

For each genome, `<results>\<genome>\<genome>.xlsx` contains these sheets:

| Sheet | Contents |
| --- | --- |
| `Summary` | Any analysis not performed because a database is missing (first, highlighted), species, MLST scheme/ST/profile, scores (resistance 0-3, ESBL, carbapenemase, colistin, virulence), counts per category (AMR genes: confident calls the AMRFinderPlus search makes too), detected genes per category, the AMR genes to check with the reason, the confident calls only other catalogues make (not counted), each point mutation and disruption in one sentence with its resistance, lineage/serotype typing, assembly QC, the settings used, and database versions and thresholds |
| `AMR_genes` | Every acquired AMR hit and every stress hit (biocide/metal/heat), with a *Confident call* column (`confident`, or `check:` and the reason) |
| `Point_mutations` | Resistance point mutations and gene disruptions: what changed, where and what it means first, then the raw hit columns (see below) |
| `Virulence` | Virulence factor hits |
| `Plasmids` | Plasmid replicon hits |
| `Typing` | Every typing call for this genome: the species, MLST, the organism-specific schemes grouped by organism, the lineage/element schemes and the serotype loci. Each row carries **the evidence the call rests on** (alleles, residues, identity and coverage, contig coordinates, database version) and **its caveats** (what is provisional, what disagreed, what could not be determined). See [Organism-specific typing](#organism-specific-typing) |
| `All_hits` | Every hit in every category; mutation calls carry a one-line *Mutation: what changed* |
| `Pivot` | One row per locus, grouped by category and drug class, with one column per database. Each cell holds that database's % identity and is colour-coded; for a mutation it holds the change itself (`S83I`, `G134AfsTer11`) |

Every hit row has the contig, start, end and strand, plus gene, database, % identity,
% coverage, drug class/subclass, product, accession, element type, method, resolution
and note.

When several databases find the same locus, upstream Hydra marks one call as primary.
The other calls stay in the sheets in grey, with `Primary call = no`. They aren't
counted.

Colours: green for 100% identity, then light green, yellow, orange and red as identity
falls. Point mutations are blue, gene disruptions orange, and a gene cut by a contig
end grey. Italic means partial coverage.

With **Cumulative_results** (and two or more genomes), `<results>\Cumulative_results.xlsx`
contains:

| Sheet | Contents |
| --- | --- |
| `Summary` | One row per assembly: the headline organism typing, every typing call, each mutation and its resistance |
| `AMR_matrix` | Assembly × gene matrix of primary calls, colour-coded by identity, with the drug class above each gene |
| `Mutations_matrix` | Assembly × gene; each cell states the change(s) the assembly carries (`S83L; D87N`, `G134AfsTer11`), with the resistance above each gene |
| `Virulence_matrix` | Same layout, for virulence genes |
| `Plasmids_matrix` | Same layout, for plasmid replicons |
| `Typing_matrix` | Assembly × typing scheme, with the call in each cell and the organism above each column. The headline calls are in column D. A call that could not be made is coloured instead of left blank, and its caveat is the cell's comment |
| `All_hits` | Every hit, with an `Assembly` column |

## Species identification

Upstream uses Mash, which has no Windows build. HYDRA-Win includes a pure-Python
re-implementation of `mash dist`, which gives the same distances as Mash 2.3, and runs it
against Kleborate's sketch (the Enterobacterales) and HYDRA-Win's own clinical sketch of
60 more species: the staphylococci, enterococci, streptococci, *Listeria*,
*C. difficile*, the non-fermenters (*Pseudomonas*, *Acinetobacter*, *Stenotrophomonas*,
*Burkholderia*), *Haemophilus*, *Neisseria*, *Campylobacter*, *Vibrio* and others.
`tools/clinical_species.tsv` lists them, with why each is there, and why the
*M. tuberculosis* complex, the *B. cereus* group, *Brucella* and *B. mallei* are not (a
Mash distance cannot separate them from a neighbour). The sketch was checked on draft
assemblies it had never seen; every result is in `docs/species_sketch_validation.md`.

A species named by the sketch decides the AMRFinderPlus mutation catalogue and the
organism typing module: a gonococcus gets the gonococcal catalogue (*penA*, *mtrR*,
*gyrA* S91F) and not the meningococcal typing module. A species outside both sketches is
named from its MLST scheme, as upstream does. Where NCBI holds few genomes that pass its
own taxonomy check (*H. parainfluenzae*, for one), the sketch is thin, and more genomes
of that species fall back to MLST.

**BLAST+ on Windows** can't cope with spaces or non-ASCII characters in paths. HYDRA-Win
runs it from an ASCII, space-free folder (the 8.3 short name, or
`%LOCALAPPDATA%\Hydra-win`) and passes it relative paths, so the app works from folders
like `C:\Users\Jörg Müller\Downloads`.

## What is not included

* **Reads aren't analysed.** There's no FASTQ input and no heteroresistance or
  allele-fraction analysis: upstream's read mode needs minimap2, samtools and pysam, and
  none of them runs natively on Windows. Use upstream Hydra on Linux or macOS for reads.
* **`vfdb_full` isn't used.** Upstream can't download it automatically, it overlaps with
  the core VFDB set, and it's by far the slowest search.
* CARD needs an internet connection on the first launch, or a copy imported from
  another PC. So do the *spa* type, the *H. influenzae* capsule and the
  *Shigella*/EIEC cluster call (see [Organism typing data](databases.md#organism-typing-data)).
  Everything else, MLST and the whole *N. meningitidis* module included, works offline.
* Organism-specific typing covers the eight organisms above. Another species gets the
  species call, MLST, the lineage and element schemes and the full gene, mutation,
  virulence and plasmid analysis, and the **Organism typing** column says "no module
  for this species" rather than leaving a blank that could be read as a negative.

## What this software can achieve

From a folder of draft assemblies and nothing else — no Linux, no conda, no internet
after the first launch — HYDRA-Win gives a clinical microbiology laboratory, in a few
minutes per genome, a complete and checkable picture of each isolate:

* **What resistance it carries, and where.** Every acquired resistance gene from ten
  reference databases, each with its contig, coordinates, strand, identity and
  coverage, so every call can be gone back to in the sequence. When several databases
  find the same locus, one call is primary and the others stay visible rather than
  being quietly dropped.
* **What exactly mutated.** Not a gene name: the codon the isolate carries, read from
  its own contigs, the reference codon, the base change, the position, the lesion type
  (substitution, frameshift, premature stop, start loss, interruption), the HGVS name,
  and the resistance it is associated with — with a gene cut by a contig end labelled as
  such instead of being called a disruption.
* **What it is, in the nomenclature the field uses.** The species, the sequence type,
  and then the organism-specific typing a reference laboratory would report: the spa
  type and clonal complex of a *S. aureus*, the emm type of a *S. pyogenes*, the
  capsular serotype of a pneumococcus or a group B streptococcus with its PBP type, the
  serovar of a *Salmonella* from its antigenic formula, the pathotype and phylogroup of
  an *E. coli*, the serogroup and fine type of a meningococcus.
* **What it could do to a patient.** Virulence repertoires, toxin genes and their
  variants, the prophages that carry them, immune evasion clusters, capsule loci,
  pathogenicity islands, plasmid replicons — and the resistance, ESBL, carbapenemase,
  colistin and virulence scores on top.
* **Why every one of those calls was made.** Each typing call is reported with the
  evidence behind it — alleles, residues, identity and coverage, contig coordinates,
  the database version — and with its caveats. That is the difference between a result
  a microbiologist can sign and a number they have to take on trust.
* **What could *not* be determined, and why.** A missing database, an incomplete
  profile, a locus at a contig end, an allele newer than the data: each is named,
  highlighted and explained. Nothing in this software reports an absence of evidence as
  evidence of absence.
* **Something you can act on and keep.** One Excel workbook per genome, with the
  evidence beside each call, plus a cumulative workbook that puts a whole batch side by
  side — assemblies against genes, against mutations, against typing schemes — which is
  what turns a set of isolates into an outbreak question that can be answered. Every
  workbook carries the app version, the upstream commit, the database versions, the
  thresholds and the settings used, so a result can be reproduced a year later.

It does this on an ordinary Windows PC, from a zip you extract and double-click, with
no installation and no administrator rights; and it tells you the provenance and the
licence of every database it used to do it.

What it is not: it is not a replacement for phenotypic susceptibility testing, it does
not predict MICs except where a reference laboratory published the value for that exact
genotype, and it does not read raw reads. It tells you what is in the genome, with the
evidence; the interpretation stays with the microbiologist.
