# Building and testing

Back to the [README](../README.md).

The Windows build runs on GitHub Actions (`.github/workflows/build.yml`) and goes
through these steps:

1. Unit tests
2. PyInstaller (`--onedir`, windowed)
3. BLAST+
4. Database build with the packaged exe
5. Zip
6. Smoke test of the packaged exe: first launch, then `--cli --cumulative` on three
   public NCBI genomes (*K. pneumoniae* HS11286, *E. coli* EC958 and *S. aureus* USA300
   FPR3757), with assertions on sheets, hits, coordinates and known genes, and the point
   mutations and disruptions AMRFinderPlus 4.2.7 reports for these genomes, under the
   same names. Every reported codon is then re-read from the FASTA by an independent
   script (`tools/verify_mutations.py`): it must encode the reported amino acid, and the
   reference codon must differ from it exactly as the reported base change says.
   The organism typing is asserted against the published types of those strains
   (USA300: spa `t008`, CC8, *agr* I, PVL positive, capsule serotype 5, immune evasion
   cluster type B; EC958: phylogroup B2, `fimH30`, ExPEC, no Shiga toxin), and every
   organism row must carry an organism, evidence and caveat text, and the two calls the
   reference tools make — HS11286's `pmrB_A21DfsTer16` (Kleborate's `pmrB:p.Gly20fs`)
   and EC958's `acrR_F180LfsTer3` — must be among them. Then a `--cli` run with custom
   thresholds and a folder of FASTQ files among the inputs, and **two** fresh unzips run
   `--offline`, each with its own database home and no network:
   * the *E. coli* genome: the thirteen bundled databases and the bundled organism
     typing data must produce real calls, including a sequence type and the ST131
     subclone call that reads it, while the *Shigella*/EIEC call (ShigEiFinder,
     GPL-3.0) must read *not determined* with its reason;
   * the *S. aureus* genome: its MLST clonal complex is **derived** from the sequence
     type, so `CC8` with no network is the proof that the bundled PubMLST schemes
     really do type an isolate — while its spa type (Ridom) must still read *not
     determined*.

   Both runs also check that the PubMLST snapshot in the zip holds every scheme an
   organism module needs, that its provenance file records a successful pre-2025
   verification, that nothing credential-shaped is in the database tree, that no
   module ships a second copy of a bundled allele set, and that the log shows the
   downloads being refused and not a single one happening
7. Window test on a 1366×768 screen: the packaged app is driven through its widgets
   (add genomes, settings, a FASTQ drop, **Run analysis**) until the table shows the
   results, then opens **Databases…**. The test checks the table, the workbooks (the same
   hits as the `--cli` run) and that the window and its log fit on the screen, and it
   saves the window screenshots shown in the README

A `v*` tag publishes the zip as a release.

To run from source (Linux, macOS or Windows), with BLAST+ on `PATH`:

```
pip install -r requirements.txt
python -m hydra_win             # window
python -m hydra_win --cli ...   # headless
python -m pytest -q
```

`tools/compare_upstream.py` checks a HYDRA-Win output folder against upstream
`hydra run --preset deep --format json` on the same genomes and databases. For custom
thresholds, give both the same `--min-identity` / `--min-coverage`.

`tools/compare_amrfinder.py` runs HYDRA-Win and NCBI's `amrfinder` (Linux) on the same genomes and database release and lists every call on which they differ (`docs/amrfinder_comparison.md`). `tools/build_species_sketch.py` rebuilds the clinical species sketch and writes its validation report (`docs/species_sketch_validation.md`).

`tools/render_screenshots.py` refreshes the README's screenshots from a green Windows
run: the window shots are the workflow's own, and the sheet views are rendered from that
run's workbooks with LibreOffice.
