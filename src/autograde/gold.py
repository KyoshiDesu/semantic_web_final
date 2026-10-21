"""gold.yaml -> validated ReferenceTriples -> gold.ttl (reified ag:ReferenceTriple individuals)."""
from collections import defaultdict

from pydantic import ValidationError
from rdflib import RDF, RDFS, XSD, Graph, Literal

from autograde import io
from autograde.io import AG
from autograde.models import ReferenceTriple


class GoldError(ValueError):
    pass


def ref_iri(qid, ref_id):
    return AG[f"{qid}_{ref_id}"]


def check_predicates(predicates, relations):
    ids = [p["id"] for p in predicates["predicates"]]
    missing = [p for p in ids if p != "other" and p not in relations]
    if missing:
        raise GoldError(f"predicates.yaml ids missing from the ontology: {missing}")
    aliases = [a for p in predicates["predicates"] for a in p.get("aliases", [])]
    clash = sorted(set(aliases) & set(ids))
    if clash:
        raise GoldError(f"aliases that are also predicate ids: {clash}")
    dup = sorted({a for a in aliases if aliases.count(a) > 1})
    if dup:
        raise GoldError(f"aliases listed under several predicates: {dup}")


def validate(gold, rubric, relations):
    if gold.get("question_id") != rubric.get("question_id"):
        raise GoldError("gold.yaml and rubric.yaml disagree on question_id")
    criteria = {c["id"] for c in rubric["criteria"]}
    concepts = set(gold.get("concepts") or {})
    refs, errors = [], []
    for raw in gold.get("triples") or []:
        try:
            ref = ReferenceTriple(**raw)
        except ValidationError as e:
            errors.append(f"{raw.get('id')}: {e.errors()[0]['msg']}")
            continue
        if ref.p not in relations:
            errors.append(f"{ref.id}: unknown predicate {ref.p!r}")
        if ref.criterion not in criteria:
            errors.append(f"{ref.id}: unknown criterion {ref.criterion!r}")
        for c in [*ref.s, ref.o]:
            if c not in concepts:
                errors.append(f"{ref.id}: undeclared concept {c!r}")
        refs.append(ref)
    ids = [r.id for r in refs]
    if len(ids) != len(set(ids)):
        errors.append("duplicate reference triple ids")
    for c in sorted(criteria - {r.criterion for r in refs}):
        errors.append(f"criterion {c} has no reference triple")
    if errors:
        raise GoldError("; ".join(errors))
    return refs


def load(qid):
    """Validated (gold_raw, rubric, refs) for a question."""
    d = io.question_dir(qid)
    gold, rubric = io.load_yaml(d / "gold.yaml"), io.load_yaml(d / "rubric.yaml")
    relations, _, _ = io.ontology_relations()
    check_predicates(io.load_predicates(), relations)
    return gold, rubric, validate(gold, rubric, relations)


def criterion_weights(refs):
    w = defaultdict(float)
    for r in refs:
        w[r.criterion] += r.weight
    return dict(w)


def to_graph(qid, refs, rubric):
    g = Graph()
    g.bind("ag", AG)
    for c in rubric["criteria"]:
        g.add((AG[c["id"]], RDF.type, AG.Criterion))
        g.add((AG[c["id"]], RDFS.comment, Literal(c["description"], lang="id")))
    for r in refs:
        node = ref_iri(qid, r.id)
        g.add((node, RDF.type, AG.ReferenceTriple))
        for s in r.s:
            g.add((node, AG.hasSubject, AG[s]))
            g.add((AG[s], RDF.type, AG.Concept))
        g.add((node, AG.hasPredicate, AG[r.p]))
        g.add((node, AG.hasObject, AG[r.o]))
        g.add((AG[r.o], RDF.type, AG.Concept))
        g.add((node, AG.criterion, AG[r.criterion]))
        g.add((node, AG.weight, Literal(str(r.weight), datatype=XSD.decimal)))
    return g


def review_md(qid, gold, rubric, refs):
    desc = {c["id"]: c["description"] for c in rubric["criteria"]}
    lines = [f"# Gold triples for {qid} — lecturer review", "",
             f"Validated by: {gold.get('validated_by') or '________'}  ",
             f"Date: {gold.get('validated_on') or '________'}", "",
             "| ID | Subjek (diterima) | Predikat | Objek | Kriteria | Bobot | OK? |",
             "|---|---|---|---|---|---|---|"]
    for r in refs:
        lines.append(f"| {r.id} | {' / '.join(r.s)} | {r.p} | {r.o} | {r.criterion} ({desc[r.criterion]}) "
                     f"| {r.weight:g} | ☐ |")
    lines += ["", "## Konsep dan alias", ""]
    for c, v in (gold.get("concepts") or {}).items():
        lines.append(f"- **{c}**: {', '.join((v or {}).get('aliases', [])) or '—'}")
    return "\n".join(lines) + "\n"


def build(qid):
    gold, rubric, refs = load(qid)
    out = io.question_dir(qid) / "gold.ttl"
    to_graph(qid, refs, rubric).serialize(out, format="turtle")
    (io.ROOT / "docs").mkdir(exist_ok=True)
    (io.ROOT / "docs" / f"gold_{qid}_review.md").write_text(review_md(qid, gold, rubric, refs), encoding="utf-8")
    return out, refs
