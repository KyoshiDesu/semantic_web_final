"""Load/save YAML, CSV, JSON and RDF; resolve project paths and parameters."""
import glob
import json
import os
import shutil
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml
from rdflib import RDF, Graph, Namespace

ROOT = Path(os.environ.get("AUTOGRADE_ROOT", Path(__file__).resolve().parents[2]))
AG = Namespace("http://example.org/autograde#")
PROV = Namespace("http://www.w3.org/ns/prov#")
PARAM_KEYS = ("tau_h", "tau_l", "delta", "lambda")


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(obj, path):
    text = yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)  # serialize first: no half-written files
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def save_json(obj, path):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config():
    return load_yaml(ROOT / "config" / "config.yaml")


def frozen_path():
    return ROOT / "config" / "frozen.yaml"


def load_params():
    """Frozen params if calibration has run, else the initial ones from config.yaml."""
    src = frozen_path() if frozen_path().exists() else ROOT / "config" / "config.yaml"
    params = load_yaml(src)["params"]
    return {k: float(params[k]) for k in PARAM_KEYS}


def load_predicates():
    return load_yaml(ROOT / "config" / "predicates.yaml")


def question_dir(qid):
    return ROOT / "data" / "questions" / qid


def question_ids():
    return sorted(p.name for p in (ROOT / "data" / "questions").iterdir() if (p / "gold.yaml").exists())


def load_answers(include_synthetic=False):
    """answer_id, question_id, text, split, synthetic. Synthetic rows only on request (Agent Rule 4)."""
    frames = []
    real = ROOT / "data" / "answers" / "answers.csv"
    if real.exists():
        frames.append(pd.read_csv(real, dtype=str).assign(synthetic=False))
    synth = ROOT / "data" / "synthetic" / "answers.csv"
    if include_synthetic and synth.exists():
        frames.append(pd.read_csv(synth, dtype=str).assign(synthetic=True))
    if not frames:
        return pd.DataFrame(columns=["answer_id", "question_id", "text", "split", "synthetic"])
    df = pd.concat(frames, ignore_index=True)
    dupes = df["answer_id"][df["answer_id"].duplicated()]
    if len(dupes):
        raise ValueError(f"answer_id must be globally unique; duplicates: {sorted(set(dupes))}")
    return df


def load_scores(path=None):
    """Per-criterion human scores: answer_id, rater_id, criterion, score_0_100."""
    path = path or ROOT / "data" / "human" / "scores.csv"
    if not Path(path).exists():
        return pd.DataFrame(columns=["answer_id", "rater_id", "criterion", "score_0_100"])
    df = pd.read_csv(path, dtype={"answer_id": str, "rater_id": str, "criterion": str})
    df["score_0_100"] = df["score_0_100"].astype(float)
    return df


def annotation_path(answer_id):
    for base in (ROOT / "data" / "annotations", ROOT / "data" / "synthetic" / "annotations"):
        if (base / f"{answer_id}.yaml").exists():
            return base / f"{answer_id}.yaml"
    return None


def ontology_path():
    return ROOT / "ontology" / "autograde.owl"


@lru_cache(maxsize=1)
def ontology_graph():
    g = Graph()
    g.parse(ontology_path(), format="xml")
    return g


def ontology_relations():
    """Relation ids, equivalence closure (symmetric+transitive) and incompatible pairs, from the ontology only."""
    g = ontology_graph()
    name = lambda iri: str(iri).split("#")[-1]
    rels = {name(s) for s in g.subjects(RDF.type, AG.Relation)}
    adj = {r: set() for r in rels}
    for a, b in g.subject_objects(AG.equivalentPredicate):
        adj.setdefault(name(a), set()).add(name(b))
        adj.setdefault(name(b), set()).add(name(a))
    eq = {}
    for r in adj:  # connected components = closure
        seen, stack = {r}, [r]
        while stack:
            for n in adj[stack.pop()] - seen:
                seen.add(n)
                stack.append(n)
        eq[r] = seen
    inc = {frozenset((name(a), name(b))) for a, b in g.subject_objects(AG.incompatibleWith)}
    return rels, eq, inc


def java_exe():
    """Java 25+ is needed by Owlready2's bundled Pellet."""
    if os.environ.get("JAVA_EXE"):
        return os.environ["JAVA_EXE"]
    if os.environ.get("JAVA_HOME"):
        return str(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    local = sorted(glob.glob(str(Path.home() / ".local/share/jdk/*/Contents/Home/bin/java")))
    return local[-1] if local else shutil.which("java")
