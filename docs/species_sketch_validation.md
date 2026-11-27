# Clinical species sketch: how well it names species

Built 2026-11-27 by `tools/build_species_sketch.py` from NCBI RefSeq. 498 genomes of 60 species are in the sketch (k=21, s=1000, the parameters of Kleborate's).

**Validation set:** draft assemblies (contig or scaffold level) that passed NCBI's ANI taxonomy check and were never sketch candidates. Each was named with this sketch plus Kleborate's (`species_mash_sketches.msh`), through `hydra_win.mashlite`, the code the Windows build runs, with upstream Hydra's thresholds: a name needs a Mash distance below 0.05, and is strong below 0.02.

| Outcome | Genomes | Share |
|---|---|---|
| correct, strong | 264 | 90.4% |
| correct, good | 27 | 9.2% |
| not named | 1 | 0.3% |
| WRONG | 0 | 0.0% |

mashlite and real Mash gave identical distances for 9960 of 9960 reference/query pairs checked.

## Limits of this validation

* **Cutibacterium acnes**: 2 sketch genome(s); all 16 candidates were within 0.005 of the genomes chosen.
* **Haemophilus parainfluenzae**: 1 sketch genome(s); NCBI holds only 3 genome(s) of it that pass its ANI taxonomy check, so a genome of this species far from those falls back to MLST.
* **Neisseria gonorrhoeae**: 1 sketch genome(s); all 16 candidates were within 0.005 of the genome chosen.
* **Bordetella pertussis**: 1 sketch genome(s); all 16 candidates were within 0.005 of the genome chosen.
* 7 validation genomes are within d < 0.0001 of a sketch genome, identical at this sketch's resolution (the same isolate assembled twice, or a clonal species): they show that the sketch reads such genomes, not how far its coverage reaches. Without them, 284 of 285 were named correctly and 0 wrongly. They are: Acinetobacter nosocomialis GCF_007680215.1, Corynebacterium striatum GCF_900447675.1, Haemophilus influenzae GCF_003414475.2, Haemophilus parainfluenzae GCF_000191405.1, Staphylococcus hominis GCF_053620395.1, Streptococcus gallolyticus GCF_026783485.1, Streptococcus gallolyticus GCF_026783565.1.

## Species whose sketch genomes are close

The smallest distance between any two sketch genomes of the two species. Below 0.05 a genome of one could be named as the other.

| Species | Species | Nearest distance |
|---|---|---|
| Neisseria gonorrhoeae | Neisseria meningitidis | 0.0376 |
| Streptococcus pneumoniae | Streptococcus pseudopneumoniae | 0.0413 |
| Neisseria lactamica | Neisseria meningitidis | 0.0498 |
| Neisseria gonorrhoeae | Neisseria lactamica | 0.0544 |
| Streptococcus mitis | Streptococcus pseudopneumoniae | 0.0577 |
| Streptococcus mitis | Streptococcus pneumoniae | 0.0663 |
| Acinetobacter baumannii | Acinetobacter nosocomialis | 0.0706 |
| Streptococcus dysgalactiae | Streptococcus pyogenes | 0.0723 |
| Campylobacter coli | Campylobacter jejuni | 0.0763 |
| Staphylococcus argenteus | Staphylococcus aureus | 0.0848 |
| Acinetobacter baumannii | Acinetobacter pittii | 0.0888 |
| Acinetobacter nosocomialis | Acinetobacter pittii | 0.0915 |
| Aeromonas caviae | Aeromonas hydrophila | 0.0915 |
| Streptococcus mitis | Streptococcus oralis | 0.0962 |
| Burkholderia cenocepacia | Burkholderia multivorans | 0.0968 |

## Every validation genome

| Species | Accession | Level | Named | Distance | Next species | Its distance | Outcome |
|---|---|---|---|---|---|---|---|
| Achromobacter xylosoxidans | GCF_001299115.1 | Scaffold | Achromobacter xylosoxidans | 0.0091 | Bordetella pertussis | 0.1709 | correct, strong |
| Achromobacter xylosoxidans | GCF_001299265.1 | Scaffold | Achromobacter xylosoxidans | 0.0109 | Bordetella pertussis | 0.1709 | correct, strong |
| Achromobacter xylosoxidans | GCF_022325165.1 | Scaffold | Achromobacter xylosoxidans | 0.0139 | Bordetella pertussis | 0.1709 | correct, strong |
| Achromobacter xylosoxidans | GCF_022524875.1 | Scaffold | Achromobacter xylosoxidans | 0.0089 | Bordetella pertussis | 0.1709 | correct, strong |
| Achromobacter xylosoxidans | GCF_034424905.1 | Scaffold | Achromobacter xylosoxidans | 0.0001 | Bordetella pertussis | 0.1782 | correct, strong |
| Acinetobacter baumannii | GCF_000759395.1 | Contig | Acinetobacter baumannii | 0.0180 | Acinetobacter nosocomialis | 0.0716 | correct, strong |
| Acinetobacter baumannii | GCF_001672535.1 | Scaffold | Acinetobacter baumannii | 0.0034 | Acinetobacter nosocomialis | 0.0727 | correct, strong |
| Acinetobacter baumannii | GCF_001721385.1 | Scaffold | Acinetobacter baumannii | 0.0008 | Acinetobacter nosocomialis | 0.0752 | correct, strong |
| Acinetobacter baumannii | GCF_001874915.1 | Contig | Acinetobacter baumannii | 0.0024 | Acinetobacter nosocomialis | 0.0730 | correct, strong |
| Acinetobacter baumannii | GCF_964290255.1 | Contig | Acinetobacter baumannii | 0.0216 | Acinetobacter nosocomialis | 0.0723 | correct, good |
| Acinetobacter nosocomialis | GCF_006367385.1 | Contig | Acinetobacter nosocomialis | 0.0196 | Acinetobacter baumannii | 0.0741 | correct, strong |
| Acinetobacter nosocomialis | GCF_007680215.1 | Scaffold | Acinetobacter nosocomialis | 0.0000 | Acinetobacter baumannii | 0.0748 | correct, strong |
| Acinetobacter nosocomialis | GCF_018139285.1 | Contig | Acinetobacter nosocomialis | 0.0043 | Acinetobacter baumannii | 0.0710 | correct, strong |
| Acinetobacter nosocomialis | GCF_030137345.1 | Scaffold | Acinetobacter nosocomialis | 0.0048 | Acinetobacter baumannii | 0.0710 | correct, strong |
| Acinetobacter nosocomialis | GCF_046488565.1 | Contig | Acinetobacter nosocomialis | 0.0043 | Acinetobacter baumannii | 0.0741 | correct, strong |
| Acinetobacter pittii | GCF_003948075.1 | Contig | Acinetobacter pittii | 0.0103 | Acinetobacter baumannii | 0.0932 | correct, strong |
| Acinetobacter pittii | GCF_004211795.1 | Scaffold | Acinetobacter pittii | 0.0104 | Acinetobacter baumannii | 0.0888 | correct, strong |
| Acinetobacter pittii | GCF_022937775.1 | Scaffold | Acinetobacter pittii | 0.0101 | Acinetobacter baumannii | 0.0883 | correct, strong |
| Acinetobacter pittii | GCF_026622515.1 | Scaffold | Acinetobacter pittii | 0.0095 | Acinetobacter baumannii | 0.0893 | correct, strong |
| Acinetobacter pittii | GCF_037028385.1 | Contig | Acinetobacter pittii | 0.0200 | Acinetobacter baumannii | 0.0858 | correct, good |
| Aeromonas caviae | GCF_019971635.1 | Contig | Aeromonas caviae | 0.0217 | Aeromonas hydrophila | 0.0975 | correct, good |
| Aeromonas caviae | GCF_019971975.1 | Contig | Aeromonas caviae | 0.0217 | Aeromonas hydrophila | 0.0975 | correct, good |
| Aeromonas caviae | GCF_033902845.1 | Scaffold | Aeromonas caviae | 0.0186 | Aeromonas hydrophila | 0.0938 | correct, strong |
| Aeromonas caviae | GCF_037116965.1 | Contig | Aeromonas caviae | 0.0195 | Aeromonas hydrophila | 0.0915 | correct, strong |
| Aeromonas caviae | GCF_053375015.1 | Contig | Aeromonas caviae | 0.0172 | Aeromonas hydrophila | 0.0909 | correct, strong |
| Aeromonas hydrophila | GCF_001604855.1 | Contig | Aeromonas hydrophila | 0.0012 | Aeromonas caviae | 0.0968 | correct, strong |
| Aeromonas hydrophila | GCF_001756345.1 | Contig | Aeromonas hydrophila | 0.0280 | Aeromonas caviae | 0.0962 | correct, good |
| Aeromonas hydrophila | GCF_046088865.1 | Contig | Aeromonas hydrophila | 0.0243 | Aeromonas caviae | 0.0950 | correct, good |
| Aeromonas hydrophila | GCF_051662565.1 | Contig | Aeromonas hydrophila | 0.0260 | Aeromonas caviae | 0.0920 | correct, good |
| Aeromonas hydrophila | GCF_057958575.1 | Contig | Aeromonas hydrophila | 0.0043 | Aeromonas caviae | 0.0968 | correct, strong |
| Bacteroides fragilis | GCF_029872695.1 | Contig | Bacteroides fragilis | 0.0090 | Cronobacter dublinensis | 0.2960 | correct, strong |
| Bacteroides fragilis | GCF_039761675.1 | Scaffold | Bacteroides fragilis | 0.0129 | Cronobacter dublinensis | 0.2960 | correct, strong |
| Bacteroides fragilis | GCF_040243425.1 | Contig | Bacteroides fragilis | 0.0030 | Cronobacter dublinensis | 0.2960 | correct, strong |
| Bacteroides fragilis | GCF_040913245.1 | Scaffold | Bacteroides fragilis | 0.0147 | Cronobacter dublinensis | 0.2960 | correct, strong |
| Bacteroides fragilis | GCF_054299205.1 | Contig | Bacteroides fragilis | 0.0112 | Cronobacter dublinensis | 0.2960 | correct, strong |
| Bordetella pertussis | GCF_001332175.1 | Scaffold | Bordetella pertussis | 0.0003 | Achromobacter xylosoxidans | 0.1677 | correct, strong |
| Bordetella pertussis | GCF_004102005.1 | Contig | Bordetella pertussis | 0.0002 | Achromobacter xylosoxidans | 0.1677 | correct, strong |
| Bordetella pertussis | GCF_039678625.1 | Contig | Bordetella pertussis | 0.0002 | Achromobacter xylosoxidans | 0.1677 | correct, strong |
| Bordetella pertussis | GCF_042610745.1 | Contig | Bordetella pertussis | 0.0004 | Achromobacter xylosoxidans | 0.1677 | correct, strong |
| Bordetella pertussis | GCF_058895405.1 | Contig | Bordetella pertussis | 0.0002 | Achromobacter xylosoxidans | 0.1677 | correct, strong |
| Burkholderia cenocepacia | GCF_003854475.1 | Contig | Burkholderia cenocepacia | 0.0087 | Burkholderia multivorans | 0.1016 | correct, strong |
| Burkholderia cenocepacia | GCF_024145675.1 | Contig | Burkholderia cenocepacia | 0.0006 | Burkholderia multivorans | 0.1023 | correct, strong |
| Burkholderia cenocepacia | GCF_024146155.1 | Contig | Burkholderia cenocepacia | 0.0002 | Burkholderia multivorans | 0.1030 | correct, strong |
| Burkholderia cenocepacia | GCF_035064625.1 | Contig | Burkholderia cenocepacia | 0.0107 | Burkholderia multivorans | 0.1023 | correct, strong |
| Burkholderia cenocepacia | GCF_040088835.1 | Contig | Burkholderia cenocepacia | 0.0007 | Burkholderia multivorans | 0.1016 | correct, strong |
| Burkholderia multivorans | GCF_002981075.1 | Contig | Burkholderia multivorans | 0.0189 | Burkholderia cenocepacia | 0.0988 | correct, strong |
| Burkholderia multivorans | GCF_902832855.1 | Scaffold | Burkholderia multivorans | 0.0179 | Burkholderia cenocepacia | 0.1016 | correct, strong |
| Burkholderia multivorans | GCF_904850285.1 | Contig | Burkholderia multivorans | 0.0170 | Burkholderia cenocepacia | 0.1016 | correct, strong |
| Burkholderia multivorans | GCF_904853595.1 | Contig | Burkholderia multivorans | 0.0006 | Burkholderia cenocepacia | 0.1037 | correct, strong |
| Burkholderia multivorans | GCF_947090805.1 | Contig | Burkholderia multivorans | 0.0101 | Burkholderia cenocepacia | 0.1068 | correct, strong |
| Burkholderia pseudomallei | GCF_001205935.1 | Scaffold | Burkholderia pseudomallei | 0.0042 | Burkholderia cenocepacia | 0.1296 | correct, strong |
| Burkholderia pseudomallei | GCF_001207035.1 | Scaffold | Burkholderia pseudomallei | 0.0046 | Burkholderia cenocepacia | 0.1296 | correct, strong |
| Burkholderia pseudomallei | GCF_028878445.1 | Contig | Burkholderia pseudomallei | 0.0051 | Burkholderia cenocepacia | 0.1296 | correct, strong |
| Burkholderia pseudomallei | GCF_900592235.1 | Scaffold | Burkholderia pseudomallei | 0.0055 | Burkholderia cenocepacia | 0.1296 | correct, strong |
| Burkholderia pseudomallei | GCF_900598515.1 | Scaffold | Burkholderia pseudomallei | 0.0048 | Burkholderia cenocepacia | 0.1296 | correct, strong |
| Campylobacter coli | GCF_001226885.1 | Contig | Campylobacter coli | 0.0067 | Campylobacter jejuni | 0.0988 | correct, strong |
| Campylobacter coli | GCF_001496115.1 | Contig | Campylobacter coli | 0.0061 | Campylobacter jejuni | 0.0932 | correct, strong |
| Campylobacter coli | GCF_006349495.1 | Scaffold | Campylobacter coli | 0.0074 | Campylobacter jejuni | 0.0981 | correct, strong |
| Campylobacter coli | GCF_036889385.1 | Scaffold | Campylobacter coli | 0.0045 | Campylobacter jejuni | 0.0932 | correct, strong |
| Campylobacter coli | GCF_051944685.1 | Scaffold | Campylobacter coli | 0.0056 | Campylobacter jejuni | 0.0962 | correct, strong |
| Campylobacter jejuni | GCF_002178135.1 | Scaffold | Campylobacter jejuni | 0.0034 | Campylobacter coli | 0.0867 | correct, strong |
| Campylobacter jejuni | GCF_028570555.1 | Contig | Campylobacter jejuni | 0.0121 | Campylobacter coli | 0.0741 | correct, strong |
| Campylobacter jejuni | GCF_030757235.1 | Scaffold | Campylobacter jejuni | 0.0096 | Campylobacter coli | 0.0904 | correct, strong |
| Campylobacter jejuni | GCF_032462605.1 | Scaffold | Campylobacter jejuni | 0.0170 | Campylobacter coli | 0.0843 | correct, strong |
| Campylobacter jejuni | GCF_036864755.1 | Scaffold | Campylobacter jejuni | 0.0113 | Campylobacter coli | 0.0807 | correct, strong |
| Clostridioides difficile | GCF_053818845.1 | Contig | Clostridioides difficile | 0.0040 | Serratia marcescens | 0.2630 | correct, strong |
| Clostridioides difficile | GCF_900164805.1 | Scaffold | Clostridioides difficile | 0.0055 | Serratia marcescens | 0.2630 | correct, strong |
| Clostridioides difficile | GCF_900165045.1 | Scaffold | Clostridioides difficile | 0.0059 | Enterococcus faecalis | 0.2438 | correct, strong |
| Clostridioides difficile | GCF_900165675.1 | Scaffold | Clostridioides difficile | 0.0021 | Serratia marcescens | 0.2630 | correct, strong |
| Clostridioides difficile | GCF_901004895.1 | Contig | Clostridioides difficile | 0.0020 | Serratia marcescens | 0.2630 | correct, strong |
| Clostridium perfringens | GCF_043950765.1 | Contig | Clostridium perfringens | 0.0123 | Clostridioides difficile | 0.2195 | correct, strong |
| Clostridium perfringens | GCF_051847355.1 | Scaffold | Clostridium perfringens | 0.0177 | Streptococcus oralis | 0.2630 | correct, strong |
| Clostridium perfringens | GCF_053202545.1 | Scaffold | Clostridium perfringens | 0.0085 | Streptococcus agalactiae | 0.1973 | correct, strong |
| Clostridium perfringens | GCF_062073877.1 | Contig | Clostridium perfringens | 0.0117 | Staphylococcus capitis | 0.2630 | correct, strong |
| Clostridium perfringens | GCF_900461035.1 | Contig | Clostridium perfringens | 0.0080 | Streptococcus oralis | 0.2630 | correct, strong |
| Corynebacterium diphtheriae | GCF_003003405.1 | Scaffold | Corynebacterium diphtheriae | 0.0002 | Corynebacterium striatum | 0.2195 | correct, strong |
| Corynebacterium diphtheriae | GCF_059691075.1 | Scaffold | Corynebacterium diphtheriae | 0.0121 | Corynebacterium striatum | 0.1868 | correct, strong |
| Corynebacterium diphtheriae | GCF_059691185.1 | Scaffold | Corynebacterium diphtheriae | 0.0106 | Corynebacterium striatum | 0.1917 | correct, strong |
| Corynebacterium diphtheriae | GCF_060436225.1 | Contig | Corynebacterium diphtheriae | 0.0137 | Corynebacterium striatum | 0.2438 | correct, strong |
| Corynebacterium diphtheriae | GCF_903986485.1 | Contig | Corynebacterium diphtheriae | 0.0124 | Corynebacterium striatum | 0.1973 | correct, strong |
| Corynebacterium striatum | GCF_048823575.1 | Contig | Corynebacterium striatum | 0.0096 | Corynebacterium diphtheriae | 0.2301 | correct, strong |
| Corynebacterium striatum | GCF_050849005.1 | Contig | Corynebacterium striatum | 0.0079 | Corynebacterium diphtheriae | 0.1868 | correct, strong |
| Corynebacterium striatum | GCF_062026450.1 | Contig | Corynebacterium striatum | 0.0075 | Corynebacterium diphtheriae | 0.2109 | correct, strong |
| Corynebacterium striatum | GCF_062026499.1 | Contig | Corynebacterium striatum | 0.0076 | Corynebacterium diphtheriae | 0.1868 | correct, strong |
| Corynebacterium striatum | GCF_900447675.1 | Contig | Corynebacterium striatum | 0.0000 | Corynebacterium diphtheriae | 0.2036 | correct, strong |
| Cutibacterium acnes | GCF_000144465.1 | Scaffold | Cutibacterium acnes | 0.0200 | Nissabacter sp. | 0.2960 | correct, strong |
| Cutibacterium acnes | GCF_002775735.1 | Contig | Cutibacterium acnes | 0.0005 | Pantoea septica | 0.2960 | correct, strong |
| Cutibacterium acnes | GCF_005774215.1 | Contig | Cutibacterium acnes | 0.0047 | Nissabacter sp. | 0.2960 | correct, strong |
| Cutibacterium acnes | GCF_030239645.1 | Contig | Cutibacterium acnes | 0.0002 | Pantoea septica | 0.2960 | correct, strong |
| Cutibacterium acnes | GCF_982704805.1 | Contig | Cutibacterium acnes | 0.0017 | Nissabacter sp. | 0.2960 | correct, strong |
| Elizabethkingia anophelis | GCF_002995685.1 | Contig | Elizabethkingia anophelis | 0.0097 | Buchnera aphidicola | 0.2960 | correct, strong |
| Elizabethkingia anophelis | GCF_009865685.1 | Contig | Elizabethkingia anophelis | 0.0102 | Ewingella americana | 0.2960 | correct, strong |
| Elizabethkingia anophelis | GCF_014219695.1 | Scaffold | Elizabethkingia anophelis | 0.0126 | Ewingella americana | 0.2960 | correct, strong |
| Elizabethkingia anophelis | GCF_023336435.1 | Scaffold | Elizabethkingia anophelis | 0.0136 | Ewingella americana | 0.2960 | correct, strong |
| Elizabethkingia anophelis | GCF_045762725.1 | Contig | Elizabethkingia anophelis | 0.0104 | Ewingella americana | 0.2960 | correct, strong |
| Enterococcus casseliflavus | GCF_019734095.1 | Scaffold | Enterococcus casseliflavus | 0.0175 | Enterococcus gallinarum | 0.1709 | correct, strong |
| Enterococcus casseliflavus | GCF_031931585.1 | Scaffold | Enterococcus casseliflavus | 0.0144 | Enterococcus gallinarum | 0.1438 | correct, strong |
| Enterococcus casseliflavus | GCF_047260065.1 | Contig | Enterococcus casseliflavus | 0.0063 | Enterococcus gallinarum | 0.1566 | correct, strong |
| Enterococcus casseliflavus | GCF_050351115.1 | Scaffold | Enterococcus casseliflavus | 0.0094 | Enterococcus gallinarum | 0.1591 | correct, strong |
| Enterococcus casseliflavus | GCF_051844175.1 | Contig | Enterococcus casseliflavus | 0.0177 | Enterococcus gallinarum | 0.1782 | correct, strong |
| Enterococcus faecalis | GCF_003056045.1 | Scaffold | Enterococcus faecalis | 0.0118 | Klebsiella aerogenes | 0.2438 | correct, strong |
| Enterococcus faecalis | GCF_040532225.1 | Scaffold | Enterococcus faecalis | 0.0076 | Enterococcus casseliflavus | 0.1973 | correct, strong |
| Enterococcus faecalis | GCF_054391455.1 | Scaffold | Enterococcus faecalis | 0.0117 | Enterococcus faecium | 0.2438 | correct, strong |
| Enterococcus faecalis | GCF_900447895.1 | Contig | Enterococcus faecalis | 0.0110 | Enterococcus faecium | 0.1917 | correct, strong |
| Enterococcus faecalis | GCF_902165185.1 | Scaffold | Enterococcus faecalis | 0.0067 | Enterococcus faecium | 0.1917 | correct, strong |
| Enterococcus faecium | GCF_002141125.1 | Scaffold | Enterococcus faecium | 0.0145 | Enterococcus casseliflavus | 0.2036 | correct, strong |
| Enterococcus faecium | GCF_003320485.1 | Scaffold | Enterococcus faecium | 0.0028 | Enterococcus casseliflavus | 0.1823 | correct, strong |
| Enterococcus faecium | GCF_028890505.1 | Contig | Enterococcus faecium | 0.0086 | Enterococcus faecalis | 0.1823 | correct, strong |
| Enterococcus faecium | GCF_031924865.1 | Scaffold | Enterococcus faecium | 0.0056 | Enterococcus casseliflavus | 0.1823 | correct, strong |
| Enterococcus faecium | GCF_042135555.1 | Contig | Enterococcus faecium | 0.0078 | Enterococcus faecalis | 0.1868 | correct, strong |
| Enterococcus gallinarum | GCF_062019970.1 | Scaffold | Enterococcus gallinarum | 0.0005 | Enterococcus casseliflavus | 0.1498 | correct, strong |
| Haemophilus influenzae | GCF_003414475.2 | Contig | Haemophilus influenzae | 0.0000 | Haemophilus parainfluenzae | 0.1744 | correct, strong |
| Haemophilus influenzae | GCF_003493375.1 | Contig | Haemophilus influenzae | 0.0144 | Haemophilus parainfluenzae | 0.1591 | correct, strong |
| Haemophilus influenzae | GCF_007897045.1 | Contig | Haemophilus influenzae | 0.0116 | Haemophilus parainfluenzae | 0.1618 | correct, strong |
| Haemophilus influenzae | GCF_030554825.1 | Contig | Haemophilus influenzae | 0.0208 | Haemophilus parainfluenzae | 0.1709 | correct, good |
| Haemophilus influenzae | GCF_041450875.1 | Contig | Haemophilus influenzae | 0.0149 | Haemophilus parainfluenzae | 0.1647 | correct, strong |
| Haemophilus parainfluenzae | GCF_000191405.1 | Scaffold | Haemophilus parainfluenzae | 0.0000 | Haemophilus influenzae | 0.1591 | correct, strong |
| Helicobacter pylori | GCF_014497725.1 | Contig | Helicobacter pylori | 0.0383 | Enterobacter mori | 0.2960 | correct, good |
| Helicobacter pylori | GCF_014498405.1 | Scaffold | Helicobacter pylori | 0.0326 | Neisseria meningitidis | 0.2960 | correct, good |
| Helicobacter pylori | GCF_018329225.1 | Scaffold | Helicobacter pylori | 0.0254 | Neisseria meningitidis | 0.2960 | correct, good |
| Helicobacter pylori | GCF_023024765.1 | Contig | Helicobacter pylori | 0.0262 | Pantoea dispersa | 0.2960 | correct, good |
| Helicobacter pylori | GCF_062071345.1 | Contig | Helicobacter pylori | 0.0320 | Escherichia albertii | 0.2960 | correct, good |
| Kingella kingae | GCF_000469825.1 | Scaffold | Kingella kingae | 0.0042 | Neisseria meningitidis | 0.2301 | correct, strong |
| Kingella kingae | GCF_000477275.1 | Scaffold | Kingella kingae | 0.0062 | Neisseria meningitidis | 0.2109 | correct, strong |
| Kingella kingae | GCF_001408935.1 | Scaffold | Kingella kingae | 0.0033 | Neisseria meningitidis | 0.2195 | correct, strong |
| Kingella kingae | GCF_030181425.1 | Contig | Kingella kingae | 0.0033 | Neisseria meningitidis | 0.2301 | correct, strong |
| Kingella kingae | GCF_030182225.1 | Contig | Kingella kingae | 0.0031 | Neisseria meningitidis | 0.2109 | correct, strong |
| Legionella pneumophila | GCF_000586175.1 | Scaffold | Legionella pneumophila | 0.0014 | Buchnera aphidicola | 0.2960 | correct, strong |
| Legionella pneumophila | GCF_001582625.1 | Scaffold | Legionella pneumophila | 0.0044 | Buchnera aphidicola | 0.2960 | correct, strong |
| Legionella pneumophila | GCF_027273075.1 | Scaffold | Legionella pneumophila | 0.0046 | Arsenophonus sp. | 0.2960 | correct, strong |
| Legionella pneumophila | GCF_054086125.1 | Scaffold | Legionella pneumophila | 0.0055 | Dickeya dadantii | 0.2960 | correct, strong |
| Legionella pneumophila | GCF_964277555.1 | Scaffold | Legionella pneumophila | 0.0225 | Arsenophonus sp. | 0.2960 | correct, good |
| Listeria monocytogenes | GCF_003002595.1 | Scaffold | Listeria monocytogenes | 0.0085 | Streptococcus oralis | 0.2438 | correct, strong |
| Listeria monocytogenes | GCF_039668665.1 | Contig | Listeria monocytogenes | 0.0077 | Streptococcus oralis | 0.2438 | correct, strong |
| Listeria monocytogenes | GCF_039668965.1 | Contig | Listeria monocytogenes | 0.0077 | Streptococcus oralis | 0.2438 | correct, strong |
| Listeria monocytogenes | GCF_040906245.1 | Contig | Listeria monocytogenes | 0.0071 | Streptococcus oralis | 0.2438 | correct, strong |
| Listeria monocytogenes | GCF_048155565.1 | Scaffold | Listeria monocytogenes | 0.0016 | Streptococcus oralis | 0.2438 | correct, strong |
| Moraxella catarrhalis | GCF_003625735.1 | Contig | Moraxella catarrhalis | 0.0059 | Neisseria meningitidis | 0.2301 | correct, strong |
| Moraxella catarrhalis | GCF_003626295.1 | Contig | Moraxella catarrhalis | 0.0052 | Neisseria meningitidis | 0.2301 | correct, strong |
| Moraxella catarrhalis | GCF_009378595.1 | Contig | Moraxella catarrhalis | 0.0030 | Neisseria meningitidis | 0.2438 | correct, strong |
| Moraxella catarrhalis | GCF_009379155.1 | Contig | Moraxella catarrhalis | 0.0052 | Neisseria meningitidis | 0.2301 | correct, strong |
| Moraxella catarrhalis | GCF_010604025.1 | Scaffold | Moraxella catarrhalis | 0.0059 | Neisseria meningitidis | 0.2301 | correct, strong |
| Neisseria gonorrhoeae | GCF_001135185.1 | Scaffold | Neisseria gonorrhoeae | 0.0024 | Neisseria meningitidis | 0.0382 | correct, strong |
| Neisseria gonorrhoeae | GCF_001162805.1 | Contig | Neisseria gonorrhoeae | 0.0025 | Neisseria meningitidis | 0.0381 | correct, strong |
| Neisseria gonorrhoeae | GCF_003789895.1 | Scaffold | Neisseria gonorrhoeae | 0.0022 | Neisseria meningitidis | 0.0372 | correct, strong |
| Neisseria gonorrhoeae | GCF_059888725.1 | Contig | Neisseria gonorrhoeae | 0.0040 | Neisseria meningitidis | 0.0391 | correct, strong |
| Neisseria gonorrhoeae | GCF_061313155.1 | Scaffold | Neisseria gonorrhoeae | 0.0034 | Neisseria meningitidis | 0.0383 | correct, strong |
| Neisseria lactamica | GCF_003492465.1 | Contig | Neisseria lactamica | 0.0098 | Neisseria meningitidis | 0.0491 | correct, strong |
| Neisseria lactamica | GCF_003492765.1 | Contig | Neisseria lactamica | 0.0040 | Neisseria meningitidis | 0.0511 | correct, strong |
| Neisseria lactamica | GCF_003493045.1 | Contig | Neisseria lactamica | 0.0174 | Neisseria meningitidis | 0.0521 | correct, strong |
| Neisseria lactamica | GCF_963394895.1 | Contig | Neisseria lactamica | 0.0156 | Neisseria meningitidis | 0.0521 | correct, strong |
| Neisseria lactamica | GCF_977036265.1 | Contig | Neisseria lactamica | 0.0069 | Neisseria meningitidis | 0.0517 | correct, strong |
| Neisseria meningitidis | GCF_018135915.1 | Contig | Neisseria meningitidis | 0.0148 | Neisseria gonorrhoeae | 0.0381 | correct, strong |
| Neisseria meningitidis | GCF_025801735.1 | Contig | Neisseria meningitidis | 0.0156 | Neisseria gonorrhoeae | 0.0402 | correct, strong |
| Neisseria meningitidis | GCF_900024345.1 | Scaffold | Neisseria meningitidis | 0.0153 | Neisseria gonorrhoeae | 0.0399 | correct, strong |
| Neisseria meningitidis | GCF_900033185.1 | Scaffold | Neisseria meningitidis | 0.0155 | Neisseria gonorrhoeae | 0.0399 | correct, strong |
| Neisseria meningitidis | GCF_982552545.1 | Contig | Neisseria meningitidis | 0.0164 | Neisseria gonorrhoeae | 0.0399 | correct, strong |
| Pasteurella multocida | GCF_001929985.1 | Scaffold | Pasteurella multocida | 0.0029 | Haemophilus influenzae | 0.2036 | correct, strong |
| Pasteurella multocida | GCF_015070975.1 | Contig | Pasteurella multocida | 0.0018 | Haemophilus influenzae | 0.1917 | correct, strong |
| Pasteurella multocida | GCF_023556015.1 | Contig | Pasteurella multocida | 0.0279 | Haemophilus influenzae | 0.2195 | correct, good |
| Pasteurella multocida | GCF_023556185.1 | Contig | Pasteurella multocida | 0.0018 | Haemophilus influenzae | 0.2109 | correct, strong |
| Pasteurella multocida | GCF_047397285.1 | Contig | Pasteurella multocida | 0.0021 | Haemophilus influenzae | 0.2036 | correct, strong |
| Proteus mirabilis | GCF_002936215.2 | Contig | Proteus mirabilis | 0.0076 | Proteus vulgaris | 0.1188 | correct, strong |
| Proteus mirabilis | GCF_030334765.1 | Scaffold | Proteus mirabilis | 0.0083 | Proteus genomosp-6 | 0.1188 | correct, strong |
| Proteus mirabilis | GCF_030335765.1 | Scaffold | Proteus mirabilis | 0.0031 | Proteus sp. | 0.1245 | correct, strong |
| Proteus mirabilis | GCF_030336205.1 | Scaffold | Proteus mirabilis | 0.0071 | Proteus genomosp-6 | 0.1188 | correct, strong |
| Proteus mirabilis | GCF_046557375.1 | Scaffold | Proteus mirabilis | 0.0032 | Proteus sp. | 0.1245 | correct, strong |
| Providencia stuartii | GCF_029075585.1 | Contig | Providencia stuartii | 0.0001 | Providencia vermicola | 0.1138 | correct, strong |
| Providencia stuartii | GCF_031854165.1 | Contig | Providencia stuartii | 0.0038 | Providencia vermicola | 0.1296 | correct, strong |
| Providencia stuartii | GCF_031921645.1 | Scaffold | Providencia stuartii | 0.0073 | Providencia vermicola | 0.1178 | correct, strong |
| Providencia stuartii | GCF_041024695.1 | Contig | Providencia stuartii | 0.0032 | Providencia vermicola | 0.1168 | correct, strong |
| Providencia stuartii | GCF_059412165.1 | Scaffold | Providencia stuartii | 0.0090 | Providencia vermicola | 0.1310 | correct, strong |
| Pseudomonas aeruginosa | GCF_004370295.1 | Scaffold | Pseudomonas aeruginosa | 0.0088 | Stenotrophomonas maltophilia | 0.2036 | correct, strong |
| Pseudomonas aeruginosa | GCF_028367665.1 | Contig | Pseudomonas aeruginosa | 0.0096 | Serratia marcescens | 0.1709 | correct, strong |
| Pseudomonas aeruginosa | GCF_037996985.1 | Contig | Pseudomonas aeruginosa | 0.0102 | Serratia marcescens | 0.1744 | correct, strong |
| Pseudomonas aeruginosa | GCF_052048255.1 | Contig | Pseudomonas aeruginosa | 0.0041 | Burkholderia cenocepacia | 0.2036 | correct, strong |
| Pseudomonas aeruginosa | GCF_059838745.1 | Contig | Pseudomonas aeruginosa | 0.0040 | Achromobacter xylosoxidans | 0.1744 | correct, strong |
| Staphylococcus argenteus | GCF_014878035.1 | Contig | Staphylococcus argenteus | 0.0012 | Staphylococcus aureus | 0.0904 | correct, strong |
| Staphylococcus argenteus | GCF_022834125.1 | Contig | Staphylococcus argenteus | 0.0096 | Staphylococcus aureus | 0.0932 | correct, strong |
| Staphylococcus argenteus | GCF_049226005.1 | Contig | Staphylococcus argenteus | 0.0021 | Staphylococcus aureus | 0.0867 | correct, strong |
| Staphylococcus argenteus | GCF_052591335.1 | Contig | Staphylococcus argenteus | 0.0012 | Staphylococcus aureus | 0.0898 | correct, strong |
| Staphylococcus argenteus | GCF_900183745.1 | Scaffold | Staphylococcus argenteus | 0.0027 | Staphylococcus aureus | 0.0825 | correct, strong |
| Staphylococcus aureus | GCF_028680555.1 | Contig | Staphylococcus aureus | 0.0094 | Staphylococcus argenteus | 0.0915 | correct, strong |
| Staphylococcus aureus | GCF_051161475.1 | Contig | Staphylococcus aureus | 0.0115 | Staphylococcus argenteus | 0.0920 | correct, strong |
| Staphylococcus aureus | GCF_051452105.1 | Contig | Staphylococcus aureus | 0.0014 | Staphylococcus argenteus | 0.0867 | correct, strong |
| Staphylococcus aureus | GCF_900125985.1 | Scaffold | Staphylococcus aureus | 0.0077 | Staphylococcus argenteus | 0.0915 | correct, strong |
| Staphylococcus aureus | GCF_964290065.1 | Contig | Staphylococcus aureus | 0.0027 | Staphylococcus argenteus | 0.0853 | correct, strong |
| Staphylococcus capitis | GCF_007667995.1 | Scaffold | Staphylococcus capitis | 0.0035 | Staphylococcus aureus | 0.1618 | correct, strong |
| Staphylococcus capitis | GCF_012926635.1 | Contig | Staphylococcus capitis | 0.0018 | Staphylococcus aureus | 0.1566 | correct, strong |
| Staphylococcus capitis | GCF_020740145.1 | Contig | Staphylococcus capitis | 0.0118 | Staphylococcus epidermidis | 0.1709 | correct, strong |
| Staphylococcus capitis | GCF_050044135.1 | Contig | Staphylococcus capitis | 0.0044 | Staphylococcus epidermidis | 0.1257 | correct, strong |
| Staphylococcus capitis | GCF_053625315.1 | Contig | Staphylococcus capitis | 0.0042 | Staphylococcus epidermidis | 0.1677 | correct, strong |
| Staphylococcus epidermidis | GCF_007665715.1 | Scaffold | Staphylococcus epidermidis | 0.0121 | Staphylococcus capitis | 0.1744 | correct, strong |
| Staphylococcus epidermidis | GCF_007672405.1 | Scaffold | Staphylococcus epidermidis | 0.0074 | Staphylococcus capitis | 0.1542 | correct, strong |
| Staphylococcus epidermidis | GCF_051450945.1 | Contig | Staphylococcus epidermidis | 0.0055 | Staphylococcus capitis | 0.1618 | correct, strong |
| Staphylococcus epidermidis | GCF_054342795.1 | Contig | Staphylococcus epidermidis | 0.0019 | Staphylococcus argenteus | 0.1782 | correct, strong |
| Staphylococcus epidermidis | GCF_059813785.1 | Contig | Staphylococcus epidermidis | 0.0087 | Staphylococcus capitis | 0.1744 | correct, strong |
| Staphylococcus haemolyticus | GCF_022486205.1 | Scaffold | Staphylococcus haemolyticus | 0.0026 | Staphylococcus capitis | 0.1709 | correct, strong |
| Staphylococcus haemolyticus | GCF_023147655.1 | Scaffold | Staphylococcus haemolyticus | 0.0069 | Staphylococcus epidermidis | 0.1868 | correct, strong |
| Staphylococcus haemolyticus | GCF_057408745.1 | Contig | Staphylococcus haemolyticus | 0.0039 | Staphylococcus capitis | 0.1823 | correct, strong |
| Staphylococcus haemolyticus | GCF_057415345.1 | Contig | Staphylococcus haemolyticus | 0.0058 | Staphylococcus hominis | 0.1744 | correct, strong |
| Staphylococcus haemolyticus | GCF_964276415.1 | Contig | Staphylococcus haemolyticus | 0.0049 | Staphylococcus hominis | 0.1823 | correct, strong |
| Staphylococcus hominis | GCF_000183685.1 | Scaffold | Staphylococcus hominis | 0.0072 | Staphylococcus haemolyticus | 0.1566 | correct, strong |
| Staphylococcus hominis | GCF_020740045.1 | Contig | Staphylococcus hominis | 0.0068 | Staphylococcus epidermidis | 0.1647 | correct, strong |
| Staphylococcus hominis | GCF_022689645.1 | Contig | Staphylococcus hominis | 0.0079 | Staphylococcus haemolyticus | 0.1591 | correct, strong |
| Staphylococcus hominis | GCF_031727055.1 | Contig | Staphylococcus hominis | 0.0102 | Staphylococcus epidermidis | 0.1709 | correct, strong |
| Staphylococcus hominis | GCF_053620395.1 | Contig | Staphylococcus hominis | 0.0000 | Staphylococcus haemolyticus | 0.1868 | correct, strong |
| Staphylococcus lugdunensis | GCF_000185485.1 | Scaffold | Staphylococcus lugdunensis | 0.0060 | Staphylococcus haemolyticus | 0.2109 | correct, strong |
| Staphylococcus lugdunensis | GCF_022569245.1 | Contig | Staphylococcus lugdunensis | 0.0005 | Staphylococcus epidermidis | 0.1917 | correct, strong |
| Staphylococcus lugdunensis | GCF_058241305.1 | Scaffold | Staphylococcus lugdunensis | 0.0062 | Staphylococcus epidermidis | 0.2109 | correct, strong |
| Staphylococcus lugdunensis | GCF_058242565.1 | Scaffold | Staphylococcus lugdunensis | 0.0053 | Staphylococcus haemolyticus | 0.2036 | correct, strong |
| Staphylococcus lugdunensis | GCF_964211005.1 | Contig | Staphylococcus lugdunensis | 0.0002 | Staphylococcus epidermidis | 0.2036 | correct, strong |
| Staphylococcus pseudintermedius | GCF_001623005.1 | Scaffold | Staphylococcus pseudintermedius | 0.0059 | Streptococcus agalactiae | 0.1917 | correct, strong |
| Staphylococcus pseudintermedius | GCF_002366375.1 | Scaffold | Staphylococcus pseudintermedius | 0.0074 | Staphylococcus hominis | 0.1973 | correct, strong |
| Staphylococcus pseudintermedius | GCF_004320065.1 | Scaffold | Staphylococcus pseudintermedius | 0.0066 | Staphylococcus hominis | 0.2036 | correct, strong |
| Staphylococcus pseudintermedius | GCF_901542585.1 | Contig | Staphylococcus pseudintermedius | 0.0071 | Staphylococcus hominis | 0.2036 | correct, strong |
| Staphylococcus pseudintermedius | GCF_964379225.1 | Scaffold | Staphylococcus pseudintermedius | 0.0041 | Staphylococcus hominis | 0.1973 | correct, strong |
| Staphylococcus saprophyticus | GCF_041025795.1 | Contig | Staphylococcus saprophyticus | 0.0046 | Staphylococcus epidermidis | 0.1973 | correct, strong |
| Staphylococcus saprophyticus | GCF_050274555.1 | Scaffold | Staphylococcus saprophyticus | 0.0047 | Staphylococcus haemolyticus | 0.1973 | correct, strong |
| Staphylococcus saprophyticus | GCF_056892475.1 | Contig | Staphylococcus saprophyticus | 0.0039 | Staphylococcus epidermidis | 0.1973 | correct, strong |
| Staphylococcus saprophyticus | GCF_056892595.1 | Contig | Staphylococcus saprophyticus | 0.0041 | Staphylococcus haemolyticus | 0.1917 | correct, strong |
| Staphylococcus saprophyticus | GCF_056892935.1 | Contig | Staphylococcus saprophyticus | 0.0044 | Staphylococcus haemolyticus | 0.1744 | correct, strong |
| Stenotrophomonas maltophilia | GCF_022750975.1 | Scaffold | Stenotrophomonas maltophilia | 0.0145 | Cronobacter sakazakii | 0.2630 | correct, strong |
| Stenotrophomonas maltophilia | GCF_041076355.1 | Contig | Stenotrophomonas maltophilia | 0.0135 | Cronobacter sakazakii | 0.2630 | correct, strong |
| Stenotrophomonas maltophilia | GCF_047497885.2 | Scaffold | Stenotrophomonas maltophilia | 0.0037 | Jejubacter sp. | 0.2438 | correct, strong |
| Stenotrophomonas maltophilia | GCF_054108135.1 | Contig | Stenotrophomonas maltophilia | 0.0125 | Achromobacter xylosoxidans | 0.2438 | correct, strong |
| Stenotrophomonas maltophilia | GCF_061613805.1 | Contig | Stenotrophomonas maltophilia | 0.0136 | Jejubacter sp. | 0.2438 | correct, strong |
| Streptococcus agalactiae | GCF_001348915.1 | Scaffold | Streptococcus agalactiae | 0.0032 | Streptococcus pyogenes | 0.1647 | correct, strong |
| Streptococcus agalactiae | GCF_008709775.1 | Contig | Streptococcus agalactiae | 0.0035 | Streptococcus pyogenes | 0.1647 | correct, strong |
| Streptococcus agalactiae | GCF_033802995.1 | Scaffold | Streptococcus agalactiae | 0.0067 | Streptococcus dysgalactiae | 0.1542 | correct, strong |
| Streptococcus agalactiae | GCF_052256115.1 | Scaffold | Streptococcus agalactiae | 0.0003 | Streptococcus pyogenes | 0.1647 | correct, strong |
| Streptococcus agalactiae | GCF_062071334.1 | Contig | Streptococcus agalactiae | 0.0048 | Streptococcus pyogenes | 0.1542 | correct, strong |
| Streptococcus anginosus | GCF_000474115.1 | Contig | Streptococcus anginosus | 0.0039 | Streptococcus oralis | 0.1744 | correct, strong |
| Streptococcus anginosus | GCF_008726835.1 | Contig | Streptococcus anginosus | 0.0052 | Streptococcus mitis | 0.1519 | correct, strong |
| Streptococcus anginosus | GCF_023109445.1 | Scaffold | Streptococcus anginosus | 0.0062 | Streptococcus mitis | 0.1782 | correct, strong |
| Streptococcus anginosus | GCF_033803465.1 | Contig | Streptococcus anginosus | 0.0055 | Stenotrophomonas maltophilia | 0.1709 | correct, strong |
| Streptococcus anginosus | GCF_040913935.1 | Scaffold | Streptococcus anginosus | 0.0194 | Streptococcus oralis | 0.1868 | correct, strong |
| Streptococcus dysgalactiae | GCF_050497105.1 | Contig | Streptococcus dysgalactiae | 0.0021 | Streptococcus pyogenes | 0.0759 | correct, strong |
| Streptococcus dysgalactiae | GCF_051775165.1 | Contig | Streptococcus dysgalactiae | 0.0047 | Streptococcus pyogenes | 0.0803 | correct, strong |
| Streptococcus dysgalactiae | GCF_052315475.1 | Contig | Streptococcus dysgalactiae | 0.0063 | Streptococcus pyogenes | 0.0763 | correct, strong |
| Streptococcus dysgalactiae | GCF_052315715.1 | Contig | Streptococcus dysgalactiae | 0.0105 | Streptococcus pyogenes | 0.0727 | correct, strong |
| Streptococcus dysgalactiae | GCF_053206765.1 | Contig | Streptococcus dysgalactiae | 0.0083 | Streptococcus pyogenes | 0.0767 | correct, strong |
| Streptococcus gallolyticus | GCF_021474745.2 | Contig | Streptococcus gallolyticus | 0.0099 | Streptococcus suis | 0.1917 | correct, strong |
| Streptococcus gallolyticus | GCF_023109635.1 | Scaffold | Streptococcus gallolyticus | 0.0016 | Streptococcus anginosus | 0.1973 | correct, strong |
| Streptococcus gallolyticus | GCF_026783265.1 | Scaffold | Streptococcus gallolyticus | 0.0039 | Streptococcus oralis | 0.1782 | correct, strong |
| Streptococcus gallolyticus | GCF_026783485.1 | Contig | Streptococcus gallolyticus | 0.0000 | Streptococcus anginosus | 0.2109 | correct, strong |
| Streptococcus gallolyticus | GCF_026783565.1 | Scaffold | Streptococcus gallolyticus | 0.0000 | Streptococcus anginosus | 0.2036 | correct, strong |
| Streptococcus mitis | GCF_003943555.1 | Contig | Streptococcus mitis | 0.0396 | Streptococcus pseudopneumoniae | 0.0696 | correct, good |
| Streptococcus mitis | GCF_023109075.1 | Scaffold | Streptococcus mitis | 0.0450 | Streptococcus pseudopneumoniae | 0.0675 | correct, good |
| Streptococcus mitis | GCF_027497935.1 | Contig | Streptococcus mitis | 0.0411 | Streptococcus pseudopneumoniae | 0.0651 | correct, good |
| Streptococcus mitis | GCF_047464435.1 | Contig | Streptococcus mitis | 0.0442 | Streptococcus pneumoniae | 0.0693 | correct, good |
| Streptococcus mitis | GCF_946190335.1 | Contig | Streptococcus mitis | 0.0454 | Streptococcus pseudopneumoniae | 0.0660 | correct, good |
| Streptococcus oralis | GCF_002096595.1 | Scaffold | Streptococcus oralis | 0.0435 | Streptococcus mitis | 0.1002 | correct, good |
| Streptococcus oralis | GCF_003944395.1 | Contig | Streptococcus oralis | 0.0366 | Streptococcus mitis | 0.0962 | correct, good |
| Streptococcus oralis | GCF_017154185.1 | Scaffold | Streptococcus oralis | 0.0402 | Streptococcus mitis | 0.1016 | correct, good |
| Streptococcus oralis | GCF_023110325.1 | Scaffold | Streptococcus oralis | 0.0337 | Streptococcus mitis | 0.1008 | correct, good |
| Streptococcus oralis | GCF_026782285.1 | Scaffold | - | 0.0681 | Streptococcus mitis | 0.0975 | not named (falls back to MLST) |
| Streptococcus pneumoniae | GCF_053143635.1 | Scaffold | Streptococcus pneumoniae | 0.0079 | Streptococcus pseudopneumoniae | 0.0433 | correct, strong |
| Streptococcus pneumoniae | GCF_900025325.1 | Scaffold | Streptococcus pneumoniae | 0.0113 | Streptococcus pseudopneumoniae | 0.0427 | correct, strong |
| Streptococcus pneumoniae | GCF_900035045.1 | Scaffold | Streptococcus pneumoniae | 0.0110 | Streptococcus pseudopneumoniae | 0.0420 | correct, strong |
| Streptococcus pneumoniae | GCF_900063245.1 | Contig | Streptococcus pneumoniae | 0.0109 | Streptococcus pseudopneumoniae | 0.0438 | correct, strong |
| Streptococcus pneumoniae | GCF_900065645.1 | Contig | Streptococcus pneumoniae | 0.0109 | Streptococcus pseudopneumoniae | 0.0438 | correct, strong |
| Streptococcus pseudopneumoniae | GCF_011714685.1 | Scaffold | Streptococcus pseudopneumoniae | 0.0097 | Streptococcus pneumoniae | 0.0427 | correct, strong |
| Streptococcus pseudopneumoniae | GCF_011714745.1 | Scaffold | Streptococcus pseudopneumoniae | 0.0128 | Streptococcus pneumoniae | 0.0447 | correct, strong |
| Streptococcus pseudopneumoniae | GCF_015700195.1 | Contig | Streptococcus pseudopneumoniae | 0.0095 | Streptococcus pneumoniae | 0.0441 | correct, strong |
| Streptococcus pseudopneumoniae | GCF_053101215.1 | Scaffold | Streptococcus pseudopneumoniae | 0.0184 | Streptococcus pneumoniae | 0.0442 | correct, strong |
| Streptococcus pseudopneumoniae | GCF_055522115.1 | Scaffold | Streptococcus pseudopneumoniae | 0.0138 | Streptococcus pneumoniae | 0.0449 | correct, strong |
| Streptococcus pyogenes | GCF_041901165.1 | Scaffold | Streptococcus pyogenes | 0.0016 | Streptococcus dysgalactiae | 0.0744 | correct, strong |
| Streptococcus pyogenes | GCF_056157585.1 | Scaffold | Streptococcus pyogenes | 0.0021 | Streptococcus dysgalactiae | 0.0783 | correct, strong |
| Streptococcus pyogenes | GCF_900983555.1 | Scaffold | Streptococcus pyogenes | 0.0095 | Streptococcus dysgalactiae | 0.0759 | correct, strong |
| Streptococcus pyogenes | GCF_900985035.1 | Scaffold | Streptococcus pyogenes | 0.0009 | Streptococcus dysgalactiae | 0.0771 | correct, strong |
| Streptococcus pyogenes | GCF_900994415.1 | Contig | Streptococcus pyogenes | 0.0110 | Streptococcus dysgalactiae | 0.0734 | correct, strong |
| Streptococcus suis | GCF_018419945.1 | Scaffold | Streptococcus suis | 0.0018 | Streptococcus pneumoniae | 0.1823 | correct, strong |
| Streptococcus suis | GCF_030053535.1 | Scaffold | Streptococcus suis | 0.0182 | Streptococcus agalactiae | 0.1823 | correct, strong |
| Streptococcus suis | GCF_034317085.1 | Scaffold | Streptococcus suis | 0.0274 | Streptococcus pneumoniae | 0.1973 | correct, good |
| Streptococcus suis | GCF_051171475.2 | Scaffold | Streptococcus suis | 0.0285 | Streptococcus agalactiae | 0.1917 | correct, good |
| Streptococcus suis | GCF_900061425.1 | Scaffold | Streptococcus suis | 0.0014 | Streptococcus pneumoniae | 0.1868 | correct, strong |
| Vibrio cholerae | GCF_001402655.1 | Scaffold | Vibrio cholerae | 0.0163 | Klebsiella pneumoniae | 0.2036 | correct, strong |
| Vibrio cholerae | GCF_019092765.1 | Scaffold | Vibrio cholerae | 0.0316 | Vibrio vulnificus | 0.1868 | correct, good |
| Vibrio cholerae | GCF_032335195.1 | Contig | Vibrio cholerae | 0.0170 | Klebsiella pneumoniae | 0.1973 | correct, strong |
| Vibrio cholerae | GCF_032820295.1 | Contig | Vibrio cholerae | 0.0142 | Klebsiella pneumoniae | 0.1973 | correct, strong |
| Vibrio cholerae | GCF_056404155.1 | Scaffold | Vibrio cholerae | 0.0150 | Klebsiella pneumoniae | 0.1973 | correct, strong |
| Vibrio parahaemolyticus | GCF_008039245.1 | Contig | Vibrio parahaemolyticus | 0.0145 | Vibrio vulnificus | 0.1744 | correct, strong |
| Vibrio parahaemolyticus | GCF_019686015.1 | Scaffold | Vibrio parahaemolyticus | 0.0008 | Vibrio vulnificus | 0.1709 | correct, strong |
| Vibrio parahaemolyticus | GCF_037164525.1 | Scaffold | Vibrio parahaemolyticus | 0.0143 | Vibrio vulnificus | 0.1782 | correct, strong |
| Vibrio parahaemolyticus | GCF_048884205.1 | Scaffold | Vibrio parahaemolyticus | 0.0139 | Vibrio vulnificus | 0.1744 | correct, strong |
| Vibrio parahaemolyticus | GCF_059067825.1 | Scaffold | Vibrio parahaemolyticus | 0.0140 | Vibrio vulnificus | 0.1744 | correct, strong |
| Vibrio vulnificus | GCF_004215325.1 | Contig | Vibrio vulnificus | 0.0136 | Vibrio parahaemolyticus | 0.1709 | correct, strong |
| Vibrio vulnificus | GCF_020251945.1 | Contig | Vibrio vulnificus | 0.0160 | Vibrio parahaemolyticus | 0.1709 | correct, strong |
| Vibrio vulnificus | GCF_032335235.1 | Contig | Vibrio vulnificus | 0.0088 | Vibrio parahaemolyticus | 0.1782 | correct, strong |
| Vibrio vulnificus | GCF_052823945.1 | Contig | Vibrio vulnificus | 0.0164 | Vibrio parahaemolyticus | 0.1647 | correct, strong |
| Vibrio vulnificus | GCF_052824925.1 | Contig | Vibrio vulnificus | 0.0169 | Vibrio parahaemolyticus | 0.1647 | correct, strong |
