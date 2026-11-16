"""Path handling that the Windows build depends on, tested on any platform."""

from __future__ import annotations

from pathlib import Path

from hydra_win import core, winsafe


def test_rewrite_makes_blast_paths_relative(tmp_path):
    home = tmp_path / "home"
    cmd = ["blastn", "-query", str(home / "work" / "run-1" / "query.fna"),
           "-db", str(home / "db" / "nucl" / "card" / "sequences.fna"),
           "-out", str(home / "work" / "run-1" / "card.tsv"), "-num_threads", "4"]
    out = winsafe.rewrite(cmd, base=home)
    assert out[2] == str(Path("work/run-1/query.fna"))
    assert out[4] == str(Path("db/nucl/card/sequences.fna"))
    assert out[6] == str(Path("work/run-1/card.tsv"))
    assert out[-1] == "4"


def test_rewrite_quotes_unsafe_db_outside_home(tmp_path):
    outside = tmp_path / "with space" / "db.fna"
    out = winsafe.rewrite(["blastn", "-db", str(outside)], base=tmp_path / "home")
    assert out[2] == f'"{outside}"' or winsafe.is_safe(out[2])


def test_blast_alias():
    assert winsafe.blast_alias("/opt/hydra") == Path("/opt/hydra")
    # Spaces/non-ASCII have no alias off Windows (no 8.3 names).
    if winsafe.short_path(Path(".")) is None:
        assert winsafe.blast_alias("/opt/with space") is None


def test_genome_names_are_safe_and_unique(tmp_path):
    files = [tmp_path / "a" / "K. pneumoniae: isolate.fasta.gz", tmp_path / "b" / "CON.fa",
             tmp_path / "c" / "sample.fna", tmp_path / "d" / "sample.fas"]
    names = core.name_genomes(files)
    assert list(names) == ["K. pneumoniae_ isolate", "_CON", "sample", "sample_2"]


def test_expand_inputs(tmp_path):
    (tmp_path / "x").mkdir()
    for name in ("a.fasta", "b.fa.gz", "c.fna", "d.fas", "notes.txt", "reads.fastq.gz"):
        (tmp_path / "x" / name).write_text(">s\nACGT\n")
    found = sorted(p.name for p in core.expand_inputs([tmp_path / "x"]))
    assert found == ["a.fasta", "b.fa.gz", "c.fna", "d.fas"]
