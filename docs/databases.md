# Databases and licences

Back to the [README](../README.md).

The release workflow builds the databases from their upstream sources with upstream
Hydra's own fetchers, on the date recorded in `db\DATABASES.txt`. Thirteen of them
ship inside the zip; the one whose terms restrict redistribution (CARD) is downloaded
on your PC. The organism typing data follows the same rule and is listed in
[Organism typing data](#organism-typing-data) below.

| Database | How you get it | Licence / terms | Citation |
| --- | --- | --- | --- |
| NCBI AMRFinderPlus (protein, point mutations, nucleotide) | in the zip | Public domain | Feldgarden et al. 2021, Sci Rep 11:12728 |
| ResFinder | in the zip | Apache-2.0 | Bortolaia et al. 2020, J Antimicrob Chemother 75:3491 |
| PlasmidFinder | in the zip | Apache-2.0 | Carattoli et al. 2014, Antimicrob Agents Chemother 58:3895 |
| SCCmecFinder | in the zip | Apache-2.0 | Kaya et al. 2018, mSphere 3:e00612-17 |
| Kleborate typing loci and species sketches (v3.2.4) | in the zip | GPL-3.0 | Lam et al. 2021, Nat Commun 12:4188; Ondov et al. 2016, Genome Biol 17:132 |
| HYDRA-Win clinical species sketch (498 genomes, 60 species) | in the zip, next to Kleborate's in `db\sketch\species` | Public domain (NCBI RefSeq); every genome and its NCBI checks in `clinical_species_sources.tsv` | O'Leary et al. 2016, Nucleic Acids Res 44:D733; Ondov et al. 2016, Genome Biol 17:132 |
| VFDB (core) | in the zip, from VFDB (`VFDB_setA_nt.fas.gz`) | The source states no licence | Liu et al. 2022, Nucleic Acids Res 50:D912 |
| ARG-ANNOT | in the zip, from abricate's repository (pinned commit) | The source states no licence | Gupta et al. 2014, Antimicrob Agents Chemother 58:212 |
| MEGARes | in the zip, from abricate's repository (pinned commit) | The source states no licence | Bonin et al. 2023, Nucleic Acids Res 51:D744 |
| *E. coli* VF | in the zip, from abricate's repository (pinned commit) | The source states no licence | [phac-nml/ecoli_vf](https://github.com/phac-nml/ecoli_vf) |
| EcOH | in the zip, from abricate's repository (pinned commit) | The source states no licence | Ingle et al. 2016, Microb Genom 2:e000064 |
| PubMLST 7-locus schemes (pre-2025 snapshot) | in the zip | PubMLST terms: *"All data submitted on or before 31 December 2024 may continue to be downloaded, used, and redistributed without restriction, subject only to proper scientific citation and acknowledgement."* Fetched anonymously, so that is all it contains — see below | Jolley, Bray & Maiden 2018, Wellcome Open Res 3:124 |
| CARD | downloaded on first launch | CARD terms: no redistribution without McMaster University's written consent; free for academic/non-commercial use | Alcock et al. 2023, Nucleic Acids Res 51:D690 |

Which databases ship in the zip follows the project owner's policy: a database whose
source states no licence or terms is shipped inside the zip; a database whose source
expressly states terms that restrict redistribution (CARD) is downloaded on your PC
the first time HYDRA-Win runs. VFDB, ARG-ANNOT, MEGARes, *E. coli* VF and EcOH state
no licence at all, so they are shipped. That is the owner's decision for this project,
not a licence granted by those sources: their sources, the copy used, the date it was
retrieved and the citation are in `db\DATABASES.txt`. If you hold rights in one of
them and want it removed from the zip, please
[open an issue](https://github.com/iowa69/HYDRA-Win/issues) and it will go back to
being a first-launch download.

## PubMLST: why the MLST schemes are now in the zip

MLST, and everything derived from a sequence type, used to need the first-launch
download. The schemes now ship, so **MLST works with no network at all** — and with
them the calls that read a sequence type: the *S. aureus* clonal complex, the
*Salmonella* eBurst group, the meningococcal clonal complex and fine type, the
*H. influenzae* sequence type. The Windows release test proves this on a fresh unzip
with no network: an isolate gets its ST, and `CC8` is derived from it.

PubMLST publishes no open licence. Its
[Terms and Conditions](https://pubmlst.org/terms-conditions) split the data by
submission date, and one sentence decides this:

> All data submitted on or before 31 December 2024 may continue to be downloaded,
> used, and redistributed without restriction, subject only to proper scientific
> citation and acknowledgement.

The same terms say that *"Anonymous (non-logged in) users may view only pre 2025
data"*, and the unauthenticated API repeats it in the responses it sends: *"you are
currently restricted to accessing data that was submitted on or prior to
2024-12-31"*. So the
snapshot is fetched **anonymously, with no API key and no other credential**, and it
therefore contains only data the sentence above covers. That is not taken on trust:
the release workflow asks PubMLST's own API whether this client can reach anything
submitted on or after 1 January 2025 (it returns zero records), and checks the allele
identifiers in the bundled files against the index an anonymous client is served. Both
checks must pass or the build fails, and the result is written into
`db\mlst\pubmlst\PUBMLST.txt` with the retrieval date.

Data submitted from 1 January 2025 onwards is *not* in the zip and is not reachable
by HYDRA-Win. An allele defined after that date reads "not determined", with that
reason given, rather than being guessed.

**If you use this data, cite and acknowledge PubMLST.** Cite Jolley KA, Bray JE,
Maiden MCJ. *Open-access bacterial population genomics: BIGSdb software, the
PubMLST.org website and their applications.* Wellcome Open Res 2018;3:124. And
include the acknowledgement PubMLST asks for:

> This publication made use of the PubMLST website (https://pubmlst.org/) sited at
> the University of Oxford. The development of that website was funded by the
> Wellcome Trust.

The allele sets are in the zip **once**. Four organism typing modules want a sequence
type and all four read Hydra's own MLST call, so their own copies of the same schemes
are not shipped; only their profile tables travel with them, because those carry the
clonal complex and the eBurst group that a scheme-agnostic MLST call does not.

## Organism typing data

One set per organism, built by the upstream module that uses it. The same policy
decides the route, applied to the redistribution status each module's author recorded
from the source's own words.

| Organism typing data | How you get it | Licence / terms | Citation |
| --- | --- | --- | --- |
| *S. aureus* marker panel (NCBI RefSeq slices) and the PubMLST *S. aureus* profile table | in the zip | NCBI: public domain. PubMLST: data submitted on or before 31 December 2024 may be redistributed without restriction | Diep et al. 2006, Lancet 367:731; Enright et al. 2000, J Clin Microbiol 38:1008 |
| Ridom SpaServer repeats and type table | downloaded on first launch | Ridom SpaServer policy: non-commercial use by individuals who download it themselves; "copies of the SpaServer database may not be used without permission to produce database driven web server or any other product or service" | Harmsen et al. 2003, J Clin Microbiol 41:5442 |
| CDC emm database and the *S. pyogenes* RefSeq virulence panel | in the zip | CDC: "all materials on this site are in the public domain". NCBI: no copyright claimed | CDC *Streptococcus* Laboratory; O'Leary et al. 2016, Nucleic Acids Res 44:D733 |
| GBS-SBG capsular references, CDC GBS surface-gene targets, the published *alp* alleles, the *S. agalactiae* RefSeq panel | in the zip | MIT (GBS-SBG). CDC surface targets: **the source states no licence**. NCBI: no copyright claimed | Tiruvayipati et al. 2021, Microb Genom 7:000688; Metcalf et al. 2017, Clin Microbiol Infect 23:574 |
| Pneumococcal *cps* references and the CDC serotype, PBP and resistance probe sets with the reference PBP-type MIC table | in the zip | **the sources state no licence** | Bentley et al. 2006, PLoS Genet 2:e31; Metcalf et al. 2016, Clin Microbiol Infect 22:1002 |
| *H. influenzae* PBP3 (*ftsI*) reference and the *blaTEM*/*blaROB* references | in the zip | NCBI: no licence attached | Skaare et al. 2014, Clin Microbiol Infect 20:O501 |
| hicap *cap* database | downloaded on first launch | **GPL-3.0**: redistributable, but only under the GPL, so it is not mixed into this MIT zip | Watts & Holt 2019, J Clin Microbiol 57:e00190-19 |
| *H. influenzae* and *N. meningitidis* PubMLST data (capsule loci, PorA/FetA and vaccine-antigen peptides, BAST, MLST, resistance alleles) | in the zip | PubMLST: the pre-2025 snapshot an anonymous download returns, redistribution unrestricted with citation and acknowledgement — see [above](#pubmlst-why-the-mlst-schemes-are-now-in-the-zip) | Jolley, Bray & Maiden 2018, Wellcome Open Res 3:124; Harrison et al. 2013, Emerg Infect Dis 19:566 |
| SISTR antigen alleles, the Grimont & Weill serovar table, the SPI references, *Salmonella* marker genes and the PubMLST *Salmonella* scheme | in the zip | Apache-2.0 (SISTR). NCBI: no copyright claimed. PubMLST: pre-2025 data, redistribution unrestricted | Yoshida et al. 2016, PLoS One 11:e0147101; Grimont & Weill 2007, WHO Collaborating Centre, Institut Pasteur |
| FimTyper *fimH* alleles, NCBI StxTyper references, VirulenceFinder *E. coli* panel | in the zip | FimTyper and VirulenceFinder: **the sources state no licence**. StxTyper: US government work, public domain | Roer et al. 2017, J Clin Microbiol 55:2538; Malberg Tetzschner et al. 2020, J Clin Microbiol 58:e01269-20 |
| ShigEiFinder cluster-specific genes | downloaded on first launch | **GPL-3.0**: redistributable, but only under the GPL, so it is not mixed into this MIT zip | Zhang et al. 2021, Microb Genom 7:000704 |

Only three sets are still downloaded on your PC. Two of them are downloaded although
their licence would permit redistribution: hicap's *cap* database and ShigEiFinder's
gene sets are GPL-3.0, which is copyleft, and this zip is MIT, so downloading them on
your own PC keeps the question from arising. The third, the Ridom *spa* database, is
expressly limited to non-commercial use by people who download it themselves.
Everything else — including all the meningococcal data, which is PubMLST
nomenclature throughout — is in the zip.

The organism typing data is about 34 MB before compression, and the PubMLST snapshot about 108 MB; the release workflow prints both figures as it builds them. `db\DATABASES.txt` lists, for
every one of these, the exact source URL, the version or retrieval date, the licence in
the source's own words, the redistribution status the source states, and the citation.
If you hold rights in any of them and want it removed from the zip, please
[open an issue](https://github.com/iowa69/HYDRA-Win/issues) and it will become a
first-launch download.

The `db` folder in the zip contains `DATABASES.txt` and the licence texts.

If a first-launch download fails, the analysis still runs with the other databases,
and says what was not done (see [The first-launch download failed](../README.md#the-first-launch-download-failed)).
Commercial users must check the CARD terms themselves, and note that PubMLST requires
a separate licence for any data submitted from 2025 onwards — none of which is in this
zip or reachable from it.

NCBI BLAST+ 2.16.0 is in the zip under `blast\`. It's public domain; see
`blast\LICENSE`. It comes with the Microsoft Visual C++ runtime DLLs it needs, which
are deployed app-locally.
