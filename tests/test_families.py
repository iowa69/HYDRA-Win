"""AMRFinderPlus's curated cut-offs and family names (HYDRA-WIN PATCH 5).

AMRFinderPlus does not hold every protein to one identity: its family table
gives hundreds of gene families their own curated cut-off, and it names a hit
by the allele only when the match is exact. These tests pin Hydra's protein
search to the rule as amr_report.cpp implements it (BlastAlignment::finish and
getGeneSymbol), on rows modelled on the 2026-10-29.1 fam.tsv.
"""

from __future__ import annotations

from pathlib import Path

from hydra_amr.config import Config
from hydra_amr.db.manager import DatabaseStore
from hydra_amr.engines.blast import Hsp
from hydra_amr.engines.families import FamilyRules
from hydra_amr.engines.nucl import QueryBatch, QueryPiece
from hydra_amr.engines.protein import ProteinScreener
from hydra_amr.records import Hit
from hydra_amr.typing.lineage import resistance_score

FAM_HEADER = ("#node_id", "parent_node_id", "gene_symbol", "hmm_id", "hmm_tc1", "hmm_tc2",
              "blastrule_complete_ident", "blastrule_complete_wp_coverage",
              "blastrule_complete_br_coverage", "blastrule_partial_ident",
              "blastrule_partial_wp_coverage", "blastrule_partial_br_coverage", "reportable",
              "type", "subtype", "class", "subclass", "family_name")

#: node, parent, symbol, complete identity, partial identity, reportable, family name
FAMILIES = (
    ("AMR", "ALL", "-", 0, 0, 0, ""),
    ("bla-A", "AMR", "bla", 0, 0, 1, "class A beta-lactamase"),
    ("blaKPC", "bla-A", "blaKPC", 0, 0, 2, "carbapenem-hydrolyzing class A beta-lactamase KPC"),
    ("aac(3)-II", "AMR", "aac(3)-II", 0, 0, 2, "aminoglycoside N-acetyltransferase AAC(3)-II"),
    ("aac(3)-IIa", "aac(3)-II", "aac(3)-IIa", 98, 98, 2,
     "aminoglycoside N-acetyltransferase AAC(3)-IIa"),
    ("cfr", "AMR", "cfr", 85, 85, 2, "23S rRNA (adenine(2503)-C(8))-methyltransferase Cfr"),
    ("aac(6')_Salmo", "AMR", "aac(6')", 0, 0, 0, "chromosomal aminoglycoside acetyltransferase"),
    ("fosA5_fam", "AMR", "fosA", 0, 0, 2, "fosfomycin resistance glutathione transferase FosA5"),
    ("aac(6')-Ie", "AMR", "aac(6')-Ie", 0, 0, 2, "aminoglycoside N-acetyltransferase AAC(6')-Ie"),
    ("aph(2'')-Ia", "AMR", "aph(2'')-Ia", 0, 0, 2, "aminoglycoside phosphotransferase APH(2'')-Ia"),
)


def _prot_dir(root: Path) -> Path:
    prot = root / "prot" / "protein"
    prot.mkdir(parents=True)
    lines = ["\t".join(FAM_HEADER)]
    for node, parent, symbol, complete, partial, reportable, name in FAMILIES:
        lines.append("\t".join([node, parent, symbol, "-", "0", "0",
                                f"{complete:.2f}", "90.00" if complete else "0.00", "0.00",
                                f"{partial:.2f}", "90.00" if partial else "0.00", "0.00",
                                str(reportable), "AMR", "AMR", "", "", name]))
    (prot / "fam.tsv").write_text("\n".join(lines) + "\n")
    return prot


# ------------------------------------------------------------------ the rule
def test_an_exact_allele_match_keeps_the_allele_name(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    call = rules.assign("blaKPC-2", "blaKPC", 100.0, 100.0, exact=True)
    assert (call.symbol, call.allele, call.required_identity) == ("blaKPC-2", True, 90.0)


def test_a_near_match_to_an_allele_is_named_by_its_family(tmp_path):
    # AMRFinderPlus reports a 99.7% KPC as blaKPC: one residue can be a new
    # allele with another phenotype (KPC-33 is KPC-2 plus D179Y).
    rules = FamilyRules.load(_prot_dir(tmp_path))
    call = rules.assign("blaKPC-2", "blaKPC", 99.7, 100.0, exact=False)
    assert (call.symbol, call.allele) == ("blaKPC", False)
    assert call.name == "carbapenem-hydrolyzing class A beta-lactamase KPC"


def test_a_node_id_is_never_shown_as_the_gene_name(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    assert rules.assign("fosA5_fam", "fosA5_fam", 99.3, 100.0, exact=False).symbol == "fosA"


def test_below_a_curated_cutoff_the_hit_falls_back_to_the_parent_family(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    below = rules.assign("aac(3)-IIa", "aac(3)-IIa", 95.0, 100.0, exact=False)
    assert (below.family, below.symbol, below.required_identity) == \
        ("aac(3)-II", "aac(3)-II", 90.0)
    above = rules.assign("aac(3)-IIa", "aac(3)-IIa", 98.5, 100.0, exact=False)
    assert (above.family, above.symbol, above.required_identity) == \
        ("aac(3)-IIa", "aac(3)-IIa", 98.0)


def test_a_curated_cutoff_below_90_admits_what_a_flat_90_drops(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    call = rules.assign("cfr", "cfr", 87.0, 100.0, exact=False)
    assert (call.symbol, call.required_identity) == ("cfr", 85.0)
    assert rules.assign("cfr", "cfr", 84.0, 100.0, exact=False) is None


def test_a_family_without_a_curated_rule_needs_90_percent(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    assert rules.assign("blaKPC-2", "blaKPC", 89.0, 100.0, exact=False) is None


def test_a_partial_hit_uses_the_partial_rule_and_half_the_reference(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    call = rules.assign("aac(3)-IIa", "aac(3)-IIa", 99.0, 70.0, exact=False)
    assert call.partial and call.family == "aac(3)-IIa"
    assert rules.assign("aac(3)-IIa", "aac(3)-IIa", 99.0, 40.0, exact=False) is None


def test_a_family_ncbi_marks_non_reportable_is_not_reported(tmp_path):
    # Salmonella's chromosomal aac(6')-Iy: AMRFinderPlus never reports it.
    rules = FamilyRules.load(_prot_dir(tmp_path))
    assert not rules.assign("aac(6')-Iy", "aac(6')_Salmo", 99.0, 100.0, exact=False).reportable
    # ... unless the reference itself is reportable and matched exactly.
    assert rules.assign("aac(6')-Iy", "aac(6')_Salmo", 100.0, 100.0, exact=True,
                        reference_reportable=2).reportable


def test_an_identity_set_by_the_user_replaces_every_curated_cutoff(tmp_path):
    # As amrfinder -i does: "will override curated similarity cutoffs".
    rules = FamilyRules.load(_prot_dir(tmp_path), identity=80.0)
    assert rules.assign("cfr", "cfr", 82.0, 100.0, exact=False).required_identity == 80.0
    assert rules.assign("aac(3)-IIa", "aac(3)-IIa", 95.0, 100.0, exact=False).family == \
        "aac(3)-IIa"


def test_a_reference_outside_the_hierarchy_keeps_the_default_rule(tmp_path):
    rules = FamilyRules.load(_prot_dir(tmp_path))
    assert rules.assign("mystery", "mystery", 95.0, 100.0, exact=False).symbol == "mystery"
    assert rules.assign("mystery", "mystery", 85.0, 100.0, exact=False) is None


def test_without_a_family_table_there_are_no_rules(tmp_path):
    assert FamilyRules.load(tmp_path / "nowhere") is None


# ------------------------------------------------------------------ the engine
class _Handle:
    """The two things the protein search reads from a database handle."""

    def __init__(self, meta: dict[str, dict]):
        self.meta = meta

    def meta_for(self, sseqid):
        return self.meta.get(sseqid)


def _reference(gene, fam_id, product, subclass="CARBAPENEM", reportable="2"):
    return {"gene": gene, "fam_id": fam_id, "accession": f"WP_{gene}", "product": product,
            "class": "BETA-LACTAM", "subclass": subclass, "element_type": "AMR",
            "element_subtype": "AMR", "reportable": reportable, "part_of_gene": "hydrolase"}


def _hsp(sseqid, identity, qstart=1, aa=293, qseq="", sseq="", strand="+", send=None):
    nident = round(aa * identity / 100)
    qend = qstart + 3 * aa - 1
    if strand == "-":                     # blastx writes a minus-frame hit high to low
        qstart, qend = qend, qstart
    return Hsp(qseqid="q1", sseqid=sseqid, pident=identity, length=aa, mismatch=aa - nident,
               gapopen=0, qstart=qstart, qend=qend, sstart=1, send=send or aa,
               evalue=1e-150, bitscore=550.0, slen=aa, qlen=50_000, gaps=0, nident=nident,
               strand=strand, qseq=qseq, sseq=sseq)


def _call(tmp_path, meta, hsps, contig=""):
    _prot_dir(tmp_path)
    config = Config(db_dir=tmp_path)
    screener = ProteinScreener(DatabaseStore(tmp_path), config)
    (tmp_path / "q.fna").write_text(f">q1\n{contig}\n")
    batch = QueryBatch(path=tmp_path / "q.fna", id_map={"q1": QueryPiece("s1", "contig_1")},
                       lengths={"q1": 50_000}, n_samples=1, n_contigs=1, total_bases=50_000)
    return screener._call_genes(batch, hsps, _Handle(meta), {}, config.thresholds).get("s1", [])


def test_the_protein_search_names_a_near_match_by_family_and_keeps_the_allele(tmp_path):
    meta = {"afp_1": _reference("blaKPC-2", "blaKPC",
                                "carbapenem-hydrolyzing class A beta-lactamase KPC-2")}
    [hit] = _call(tmp_path, meta, [_hsp("afp_1", 99.7)])
    assert (hit.gene, hit.closest, hit.method) == ("blaKPC", "blaKPC-2", "BLASTX")
    assert hit.product == "carbapenem-hydrolyzing class A beta-lactamase KPC"
    assert hit.rule_identity == 90.0
    assert "closest reference blaKPC-2" in hit.note


def test_the_protein_search_keeps_an_exact_allele_name(tmp_path):
    meta = {"afp_1": _reference("blaKPC-2", "blaKPC",
                                "carbapenem-hydrolyzing class A beta-lactamase KPC-2")}
    [hit] = _call(tmp_path, meta, [_hsp("afp_1", 100.0)])
    assert (hit.gene, hit.closest, hit.method) == ("blaKPC-2", "", "EXACTX")


def test_the_protein_search_applies_a_curated_cutoff_below_90(tmp_path):
    meta = {"afp_1": _reference("cfr", "cfr", "Cfr", subclass="OXAZOLIDINONE")}
    [hit] = _call(tmp_path, meta, [_hsp("afp_1", 87.0)])
    assert (hit.gene, hit.rule_identity) == ("cfr", 85.0)


def test_the_protein_search_drops_what_no_family_rule_admits(tmp_path):
    meta = {"afp_1": _reference("blaKPC-2", "blaKPC", "KPC-2")}
    assert _call(tmp_path, meta, [_hsp("afp_1", 89.0)]) == []


def test_the_protein_search_names_a_hit_below_a_curated_cutoff_by_its_parent(tmp_path):
    meta = {"afp_1": _reference("aac(3)-IIa", "aac(3)-IIa", "AAC(3)-IIa",
                                subclass="GENTAMICIN")}
    [hit] = _call(tmp_path, meta, [_hsp("afp_1", 95.0)])
    assert (hit.gene, hit.rule_identity) == ("aac(3)-II", 90.0)
    assert "below the 98% identity NCBI requires for aac(3)-IIa" in hit.note


# ------------------------------------------------------------------ downstream
def test_the_esbl_score_still_reads_the_closest_allele():
    # Renaming a 99.8% CTX-M-15 to blaCTX-M must not stop it scoring as an ESBL.
    hit = Hit(sample="s1", database="protein", gene="blaCTX-M", closest="blaCTX-M-15",
              drug_class="BETA-LACTAM", subclass="CEPHALOSPORIN", method="BLASTX")
    score, flags = resistance_score([hit], known_esbl=frozenset({"ctx-m-15"}))
    assert flags["esbl"] and score == 1


# ------------------------------------------------------------------ start codons
_KPC = {"afp_1": _reference("blaKPC-2", "blaKPC",
                            "carbapenem-hydrolyzing class A beta-lactamase KPC-2")}


def _one_mismatch_at_the_start(first, strand="+"):
    """A 293-residue alignment whose only mismatch is residue 1 (isolate L/V, reference M)."""
    aa = 293
    gene = first + "GCA" * (aa - 1)
    if strand == "-":
        gene = gene[::-1].translate(str.maketrans("ACGT", "TGCA"))
    contig = "C" * 100 + gene + "C" * 100
    qseq = ("V" if first == "GTG" or first == "GTA" else "L") + "A" * (aa - 1)
    return contig, _hsp("afp_1", 100.0 * (aa - 1) / aa, qstart=101, aa=aa, strand=strand,
                        qseq=qseq, sseq="M" + "A" * (aa - 1))


def test_an_alternative_start_codon_reads_as_methionine(tmp_path):
    # AMRFinderPlus calls a TTG-initiated dfrA17 or GTG-initiated tet(A) EXACT;
    # blastx translates the first codon as L or V and would score it 99.4%.
    contig, hsp = _one_mismatch_at_the_start("TTG")
    [hit] = _call(tmp_path, _KPC, [hsp], contig)
    assert (hit.gene, hit.method, hit.identity_pct) == ("blaKPC-2", "EXACTX", 100.0)


def test_an_alternative_start_codon_on_the_minus_strand_reads_as_methionine(tmp_path):
    contig, hsp = _one_mismatch_at_the_start("GTG", strand="-")
    [hit] = _call(tmp_path, _KPC, [hsp], contig)
    assert (hit.gene, hit.method) == ("blaKPC-2", "EXACTX")


def test_a_codon_that_is_not_a_start_stays_a_mismatch(tmp_path):
    contig, hsp = _one_mismatch_at_the_start("GTA")      # valine, never a start
    [hit] = _call(tmp_path, _KPC, [hsp], contig)
    assert (hit.gene, hit.method) == ("blaKPC", "BLASTX")


# ------------------------------------------------------------------ internal stops
def test_an_internal_stop_codon_is_not_a_complete_gene(tmp_path):
    # AMRFinderPlus reports such a blaTEM as INTERNAL_STOP; counting it as a
    # complete gene would make it a confident call.
    qseq = "M" + "A" * 150 + "*" + "A" * 141
    [hit] = _call(tmp_path, _KPC, [_hsp("afp_1", 99.7, qseq=qseq, sseq="M" + "A" * 292)])
    assert (hit.method, hit.resolution) == ("INTERNAL_STOP", "INTERNAL_STOP")


# ------------------------------------------------------------------ fusions
_FUSION = {
    "afp_1": {**_reference("aac(6')-Ie", "aac(6')-Ie", "bifunctional AAC(6')-Ie/APH(2'')-Ia",
                           subclass="GENTAMICIN"), "accession": "WP_001028144.1",
              "fusion_part": "1", "fusion_total": "2"},
    "afp_2": {**_reference("aph(2'')-Ia", "aph(2'')-Ia", "bifunctional AAC(6')-Ie/APH(2'')-Ia",
                           subclass="GENTAMICIN"), "accession": "WP_001028144.1",
              "fusion_part": "2", "fusion_total": "2"},
}


def test_a_fusion_gene_is_named_by_all_its_parts(tmp_path):
    hits = _call(tmp_path, _FUSION, [_hsp("afp_1", 100.0, aa=479), _hsp("afp_2", 100.0, aa=479)])
    assert [h.gene for h in hits] == ["aac(6')-Ie/aph(2'')-Ia"]


def test_a_partial_hit_to_a_fusion_reference_is_not_reported(tmp_path):
    # amr_report.cpp drops it (PD-1032): half a fusion protein is not the fusion.
    hsps = [_hsp("afp_1", 99.0, aa=479, send=280), _hsp("afp_2", 99.0, aa=479, send=280)]
    assert _call(tmp_path, _FUSION, hsps) == []


def test_the_genes_own_stop_codon_is_not_an_internal_stop(tmp_path):
    # Every AMRProt reference ends with its stop ('*'), so blastx aligns the
    # isolate's stop codon to it: that is the end of the gene, not a lesion.
    [hit] = _call(tmp_path, _KPC, [_hsp("afp_1", 100.0, aa=294, qseq="M" + "A" * 292 + "*",
                                        sseq="M" + "A" * 292 + "*")])
    assert (hit.method, hit.resolution) == ("EXACTX", "COMPLETE")
