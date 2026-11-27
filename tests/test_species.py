"""Species calls the clinical sketch makes possible, and what they must lead to.

A species name decides which AMRFinderPlus mutation catalogue and which
organism typing module a genome gets. These tests pin the three places where
a correct sketch name used to be lost on the way.
"""

from __future__ import annotations

import pytest

from hydra_amr.records import MlstCall, SpeciesCall
from hydra_amr.typing.organisms import registry
from hydra_amr.typing.species import SpeciesIdentifier, load_scheme_table


@pytest.fixture(scope="module")
def identifier() -> SpeciesIdentifier:
    ident = SpeciesIdentifier.__new__(SpeciesIdentifier)
    ident.store = None
    ident.scheme_table = load_scheme_table(None)
    ident.sketches = []
    return ident


def sketch_call(identifier, name: str, distance: float) -> SpeciesCall:
    genus, _, species = name.partition(" ")
    return SpeciesCall(name=name, genus=genus, species=species,
                       confidence="strong" if distance < 0.02 else "good",
                       evidence="Mash sketch x", distance=distance,
                       organism=identifier.organism_for_name(name))


@pytest.mark.parametrize("name, organism", [
    # Both share PubMLST's genus-level "neisseria" scheme, so the scheme table
    # cannot give them a catalogue; AMRFinderPlus has one for each.
    ("Neisseria gonorrhoeae", "Neisseria_gonorrhoeae"),
    ("Neisseria meningitidis", "Neisseria_meningitidis"),
    ("Neisseria lactamica", None),
    # AMRFinderPlus curates the B. cepacia complex as one taxgroup.
    ("Burkholderia cenocepacia", "Burkholderia_cepacia"),
    ("Burkholderia multivorans", "Burkholderia_cepacia"),
    ("Burkholderia pseudomallei", "Burkholderia_pseudomallei"),
    ("Burkholderia thailandensis", None),
])
def test_a_sketch_name_reaches_its_amrfinderplus_organism(identifier, name, organism):
    assert identifier.organism_for_name(name) == organism


def test_a_genus_level_scheme_takes_the_species_from_the_sketch(identifier):
    # The "neisseria" scheme names a genus. A sketch inside that genus names
    # the species, even at a distance that would not override a species call.
    mlst = MlstCall(scheme="neisseria", sequence_type="1901", loci_found=7, loci_total=7)
    call = identifier.identify("g", mlst, sketch=sketch_call(identifier,
                                                             "Neisseria gonorrhoeae", 0.03))
    assert call.name == "Neisseria gonorrhoeae"
    assert call.organism == "Neisseria_gonorrhoeae"
    assert "MLST scheme neisseria" in call.evidence


def test_a_species_level_scheme_still_needs_a_strong_sketch_to_change(identifier):
    # Upstream's rule inside one genus stands: S. pneumoniae from its own
    # scheme is replaced only by a sketch closer than 0.02.
    mlst = MlstCall(scheme="spneumoniae", sequence_type="320", loci_found=7, loci_total=7)
    call = identifier.identify("g", mlst, sketch=sketch_call(
        identifier, "Streptococcus pseudopneumoniae", 0.03))
    assert call.name == "Streptococcus pneumoniae"


def test_a_named_species_is_not_typed_by_its_neighbours_module():
    # A gonococcus typed by the shared "neisseria" scheme must not get the
    # meningococcal module (capsule, BAST, MenDeVAR) because of the scheme.
    gonococcus = SpeciesCall(name="Neisseria gonorrhoeae", genus="Neisseria",
                             species="gonorrhoeae", confidence="strong")
    neisseria = MlstCall(scheme="neisseria", sequence_type="1901")
    assert [m.key for m in registry.select(gonococcus, neisseria)] == []
    meningococcus = SpeciesCall(name="Neisseria meningitidis", genus="Neisseria",
                                species="meningitidis", confidence="strong")
    assert [m.key for m in registry.select(meningococcus, neisseria)] == ["nmeningitidis"]


def test_without_a_species_name_the_scheme_still_chooses_the_module():
    # No sketch (or no match): the genus-level call from the scheme keeps
    # selecting the meningococcal module, as before.
    genus_only = SpeciesCall(name="Neisseria sp.", genus="Neisseria", species="",
                             confidence="strong")
    neisseria = MlstCall(scheme="neisseria", sequence_type="11")
    assert [m.key for m in registry.select(genus_only, neisseria)] == ["nmeningitidis"]
    assert [m.key for m in registry.select(SpeciesCall(), neisseria)] == ["nmeningitidis"]


@pytest.mark.parametrize("label", ["cryptic-clade-1", "unknown", "sp.", "genomosp-4"])
def test_a_provisional_sketch_label_keeps_the_scheme_module(label):
    # Kleborate's sketch names some genomes by clade, not species. Those are
    # not a species call, so the E. coli scheme still brings the E. coli module.
    clade = SpeciesCall(name=f"Escherichia {label}", genus="Escherichia", species=label)
    achtman = MlstCall(scheme="ecoli_achtman_4", sequence_type="131")
    assert not registry.names_a_species(clade)
    assert [m.key for m in registry.select(clade, achtman)] == ["ecoli"]
