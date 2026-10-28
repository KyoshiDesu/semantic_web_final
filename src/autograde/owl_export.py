"""One run (or one answer) as a self-contained OWL file for Protégé: browse it, run the reasoner, query it.

The file holds the ontology with its SWRL rules, the gold graph of every question involved, each answer's graph and
its effective ledger. The app's own ag:contradicts inferences are left out so the reasoner in Protégé derives them
again. Labels and declarations are added here only; the knowledge graph itself is unchanged.
"""
from urllib.parse import quote

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SKOS

from autograde import db, gold, io, kg, rdfviz
from autograde.feedback import triple_label
from autograde.io import AG, ANS
from autograde.models import LedgerEntry, StudentTriple

ONTOLOGY_IRI = URIRef("http://example.org/autograde/ontology")
EXPORT_BASE = "http://example.org/autograde/export/"
# Used by the gold graphs but not declared in autograde.owl; undeclared, Protégé guesses their type or refuses OWL DL.
DECLARATIONS = [(SKOS.Concept, RDF.type, OWL.Class), (SKOS.broader, RDF.type, OWL.ObjectProperty)]


def export_iri(run_id, answer_id=None):
    return URIRef(EXPORT_BASE + quote(run_id) + (f"/{quote(answer_id)}" if answer_id else ""))


def _results(run_id, answer_id):
    if db.run(run_id) is None:
        raise LookupError(f"unknown run {run_id}")
    results = db.results(run_id)
    if answer_id is not None:
        if answer_id not in results:
            raise LookupError(f"{answer_id} is not graded in run {run_id}")
        results = {answer_id: results[answer_id]}
    if not results:
        raise LookupError(f"run {run_id} has no graded answers")
    return results


def build(run_id, answer_id=None):
    results = _results(run_id, answer_id)
    g = io.bind_namespaces(Graph())
    for t in io.ontology_graph():  # embedded, not owl:imports: Protégé would try to fetch the ontology IRI
        if t[0] != ONTOLOGY_IRI:
            g.add(t)
    iri = export_iri(run_id, answer_id)
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, RDFS.comment, Literal(f"AutoGrade-RDF run {run_id}: {', '.join(sorted(results))}. ag:contradicts is "
                                      "left out; start the reasoner to infer it.")))
    for t in DECLARATIONS:
        g.add(t)
    abox = Graph()
    for qid in sorted({r["question_id"] for r in results.values()}):
        abox += kg.get_graph(kg.gold_graph_name(qid))
        for ref in gold.load(qid)[2]:
            g.add((gold.ref_iri(qid, ref.id), RDFS.label, Literal(triple_label(ref))))
    for aid, r in sorted(results.items()):
        # the corrected ledger when there is one: both share entry IRIs and ag:status is functional
        kind = "ledger_corrected" if r["ledger_corrected"] else "ledger"
        abox += kg.get_graph(kg.answer_graph_name(run_id, aid, "answer"), kg.answer_graph_name(run_id, aid, kind))
        for t in map(StudentTriple.model_validate, r["students"]):
            g.add((ANS[t.id], RDFS.label, Literal(rdfviz.triple_text(t))))
        for e in map(LedgerEntry.model_validate, r["ledger_corrected"] or r["ledger"]):
            g.add((ANS[e.entry_id], RDFS.label, Literal(f"{e.reference_id} · {e.status} · {e.credit:g}")))
    abox.remove((None, AG.contradicts, None))
    for s in set(abox.subjects(RDF.type, None)):
        g.add((s, RDF.type, OWL.NamedIndividual))
    g += abox
    return g


def rdfxml(run_id, answer_id=None):
    return build(run_id, answer_id).serialize(format="xml", encoding="utf-8")
