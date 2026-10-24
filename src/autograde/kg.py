"""Oxigraph triple store with one named graph per document: the ontology, each question's gold key, and each
graded answer's answer / ledger / corrected-ledger graphs.

RocksDB holds a process lock while any reference to the store (or to a query result) is alive. Every function
here opens the store, finishes its work, and returns plain Python or rdflib objects, so nothing keeps the lock.
"""
import hashlib
import re
import shutil
import time

import pandas as pd
import pyoxigraph as ox
from rdflib import Graph

from autograde import db, io

ONTOLOGY = "urn:ag:ontology"
GOLD_PREFIX = "urn:ag:gold:"
RUN_PREFIX = "urn:ag:run:"
KINDS = ("answer", "ledger", "ledger_corrected")
LOCK_WAIT_SECONDS = 2.0


class KGBusyError(RuntimeError):
    pass


def kg_path():
    return db.db_dir() / "kg"


def gold_graph_name(qid):
    return f"{GOLD_PREFIX}{qid}"


def answer_graph_name(run_id, answer_id, kind):
    if kind not in KINDS:
        raise ValueError(f"unknown graph kind {kind!r}")
    return f"{RUN_PREFIX}{run_id}:{answer_id}:{kind}"


def parse_name(name):
    out = {"name": name, "kind": "other", "question": None, "run": None, "answer": None}
    if name == ONTOLOGY:
        out["kind"] = "ontology"
    elif name.startswith(GOLD_PREFIX):
        out.update(kind="gold", question=name[len(GOLD_PREFIX):])
    elif name.startswith(RUN_PREFIX):
        run_id, answer_id, kind = name[len(RUN_PREFIX):].rsplit(":", 2)
        out.update(kind=kind, run=run_id, answer=answer_id)
    return out


def _open():
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return ox.Store(str(kg_path()))
        except OSError as e:
            if "lock" not in str(e).lower():
                raise
            if time.monotonic() >= deadline:
                raise KGBusyError("the knowledge graph store is in use by another process (app or CLI); "
                                  "close it and retry") from e
            time.sleep(0.1)


def put_graph(name, graph):
    """Replace the named graph's contents with an rdflib graph."""
    data = graph.serialize(format="nt", encoding="utf-8")
    store = _open()
    node = ox.NamedNode(name)
    store.remove_graph(node)
    store.load(data, format=ox.RdfFormat.N_TRIPLES, to_graph=node)
    store.flush()


def get_graph(*names):
    """Union of the named graphs as one rdflib graph; a name that is not in the store adds nothing."""
    store = _open()
    data = b"".join(store.dump(format=ox.RdfFormat.N_TRIPLES, from_graph=ox.NamedNode(n)) for n in names)
    g = io.bind_namespaces(Graph())
    g.parse(data=data.decode("utf-8"), format="nt")
    return g


def has_graph(name):
    return _open().contains_named_graph(ox.NamedNode(name))


def graphs():
    """Every non-empty named graph with its triple count, sorted by name."""
    store = _open()
    rows = [(s["g"].value, int(s["n"].value))
            for s in store.query("SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")]
    return [{**parse_name(g), "triples": n} for g, n in sorted(rows)]


def query(sparql):
    """Read-only SPARQL over the whole dataset (default graph = union of all named graphs).

    SELECT/ASK -> DataFrame of strings, CONSTRUCT/DESCRIBE -> Turtle text. SERVICE is refused, and updates
    fail to parse (Store.query only accepts queries)."""
    if re.search(r"\bSERVICE\b", sparql, re.I):
        raise ValueError("SERVICE (federated queries to remote endpoints) is disabled")
    store = _open()
    try:
        result = store.query(sparql, use_default_graph_as_union=True)
    finally:
        del store  # a parse error's traceback must not keep the store (and its lock) alive
    if isinstance(result, ox.QueryBoolean):
        return pd.DataFrame({"ASK": [bool(result)]})
    if isinstance(result, ox.QueryTriples):
        g = io.bind_namespaces(Graph())
        g.parse(data=result.serialize(format=ox.RdfFormat.N_TRIPLES).decode("utf-8"), format="nt")
        return g.serialize(format="turtle")
    columns = [v.value for v in result.variables]
    rows = [[None if t is None else t.value for t in row] for row in result]
    return pd.DataFrame(rows, columns=columns)


def sync_ontology():
    """Reload urn:ag:ontology when autograde.owl changed (SHA-256 kept in the meta table). True if reloaded."""
    digest = hashlib.sha256(io.ontology_path().read_bytes()).hexdigest()
    if db.get_meta("ontology_sha256") == digest and has_graph(ONTOLOGY):
        return False
    put_graph(ONTOLOGY, Graph().parse(io.ontology_path(), format="xml"))
    db.set_meta("ontology_sha256", digest)
    return True


def remove():
    """Delete the store directory; refuses (KGBusyError) while another process holds it."""
    if kg_path().exists():
        _open()  # the returned store is dropped at once, releasing the lock
        shutil.rmtree(kg_path())
