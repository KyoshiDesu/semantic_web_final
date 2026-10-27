"""OWL export for Protégé: self-contained and declared, without the app's inferences, so the reasoner re-derives them."""
import pytest
from rdflib import OWL, RDF, RDFS, Graph, Namespace

from autograde import db, gold, importer, io, owl_export, pipeline
from autograde.io import AG, ANS
from test_pipeline import STUB

SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
DECLARED = (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
RUN = "owl-export-test"


@pytest.fixture
def run(fresh_db):
    importer.import_files()
    ctx = pipeline.Context.load("Q1", reasoner="sparql", cosine=STUB)
    db.create_run(RUN, "gold", "all", "Q1", ctx.params, False, "sparql", True)
    texts = db.answers(include_synthetic=True).set_index("answer_id").text
    for aid in ("Q1_A07", "Q1_A08"):
        pipeline.run_answer(ctx, aid, texts[aid], "gold", RUN, use_llm_feedback=False)
    return RUN


def test_self_contained_without_the_apps_inferences(run):
    g = Graph().parse(data=owl_export.rdfxml(run), format="xml")
    assert set(g.subjects(RDF.type, OWL.Ontology)) == {owl_export.export_iri(run)}
    rules = len(set(io.ontology_graph().subjects(RDF.type, SWRL.Imp)))
    assert rules > 0 and len(set(g.subjects(RDF.type, SWRL.Imp))) == rules
    assert db.result(run, "Q1_A08")["trace"]["contradictions"]  # the app found one, so leaving it out matters
    assert list(g.triples((None, AG.contradicts, None))) == []
    assert (ANS["Q1_A07"], RDF.type, OWL.NamedIndividual) in g


def test_every_term_an_individual_uses_is_declared(run):
    g = owl_export.build(run)
    individuals = set(g.subjects(RDF.type, OWL.NamedIndividual))
    used = {p for s in individuals for p in g.predicates(s)} - {RDF.type, RDFS.label, RDFS.comment}
    assert {p for p in used if not any((p, RDF.type, k) in g for k in DECLARED)} == set()
    classes = {o for s in individuals for o in g.objects(s, RDF.type)} - {OWL.NamedIndividual}
    assert {c for c in classes if (c, RDF.type, OWL.Class) not in g} == set()


def test_labels_one_answer_and_the_corrected_ledger(run):
    db.add_overrides([{"answer_id": "Q1_A07", "reference_id": "R3", "status": "MATCHED", "by": "DS",
                       "date": "2026-10-27", "reason": "air disebut"}])
    pipeline.apply_corrections(run, "Q1_A07")
    g = owl_export.build(run, "Q1_A07")
    entry = ANS["L_Q1_A07_R3"]
    assert list(g.objects(entry, AG.status)) == [AG.Cocok]  # the corrected status, and only that one
    assert str(g.value(entry, RDFS.label)).startswith("R3 · MATCHED")
    assert g.value(gold.ref_iri("Q1", "R1"), RDFS.label) is not None
    assert g.value(ANS["Q1_A07_t1"], RDFS.label) is not None
    assert list(g.triples((ANS["Q1_A08"], None, None))) == []  # one-answer scope


def test_unknown_run_or_answer(run):
    with pytest.raises(LookupError):
        owl_export.build("no-such-run")
    with pytest.raises(LookupError):
        owl_export.build(run, "Q1_A01")


@pytest.mark.pellet
@pytest.mark.parametrize("reasoner", ["pellet", "hermit"])
def test_the_reasoner_rederives_the_apps_contradictions(run, tmp_path, reasoner):
    import owlready2
    owlready2.JAVA_EXE = io.java_exe()
    path = tmp_path / "export.owl"
    path.write_bytes(owl_export.rdfxml(run))
    world = owlready2.World()
    world.get_ontology(path.as_uri()).load()
    if reasoner == "pellet":
        owlready2.sync_reasoner_pellet(world, infer_property_values=True, infer_data_property_values=True, debug=0)
    else:
        owlready2.sync_reasoner_hermit(world, infer_property_values=True, debug=0)
    got = {(s.name, o.name) for s, o in world.search_one(iri=str(AG.contradicts)).get_relations()}
    want = {(t, io.local_name(gold.ref_iri("Q1", r)))
            for aid in ("Q1_A07", "Q1_A08") for t, r in db.result(run, aid)["trace"]["contradictions"]}
    assert want and got == want
