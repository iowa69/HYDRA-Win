"""Pieces of a gene are not joined across inserted sequence (HYDRA-WIN PATCH 6).

Upstream merged every HSP of one reference within about twice its length plus
5 kb, so the two halves of a blaZ split by a 5.5 kb insertion became one
"complete" blaZ, and the aac(6')-Ie/aph(2'')-Ia gene that *was* the insertion
fell inside it and was filed as a duplicate of it. AMRFinderPlus never joins
them: it reports the larger piece as partial.
"""

from __future__ import annotations

from hydra_amr.engines.blast import MAX_HSP_GAP, Hsp, merge_hsps


def _hsp(qstart, qend, sstart, send, slen=846):
    length = send - sstart + 1
    return Hsp(qseqid="contig_1", sseqid="blaZ", pident=100.0, length=length, mismatch=0,
               gapopen=0, qstart=qstart, qend=qend, sstart=sstart, send=send, evalue=1e-100,
               bitscore=2.0 * length, slen=slen, qlen=100_000, gaps=0, nident=length,
               strand="+")


def test_pieces_split_by_an_insertion_stay_apart():
    # As AMRFinderPlus reports it: the larger piece, as a partial gene.
    merged = merge_hsps([_hsp(7691, 8089, 1, 399), _hsp(13656, 14102, 400, 846)])
    assert [(m.query_start, round(m.coverage_pct)) for m in merged] == [(13656, 53)]


def test_pieces_that_touch_are_one_gene():
    # blastx splits a frameshifted gene into two adjacent HSPs; that is one locus.
    merged = merge_hsps([_hsp(1000, 1398, 1, 399), _hsp(1400, 1846, 400, 846)])
    assert [round(m.coverage_pct) for m in merged] == [100]


def test_the_gap_allowed_is_small():
    assert MAX_HSP_GAP <= 60
