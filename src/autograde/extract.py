"""Answer text -> StudentTriple[] (LLM mode with grounding check, or gold mode from hand annotations)."""
import unicodedata

from autograde import db, io, llm
from autograde.models import StudentTriple
from autograde.normalize import content_tokens

LANGUAGES = {"id": "Indonesian", "en": "English"}

SYSTEM = """You extract semantic triples from a student's short answer written in {language}.

Rules:
- Output only relations the student actually states. Never add knowledge the student did not write.
- subject and object must copy the student's own words from the cited sentences (you may drop articles).
- A short answer often leaves out what the question already names. Then take that one part, subject or object,
  from the question's words; the other part must still be the student's.
- predicate must be one of the listed predicate ids (its aliases show which verbs it covers). Use "other" when
  none fits.
- Rewrite passive voice as active: {passive_example}.
- Split coordinated statements into one triple each.
- negated is true only when the student denies the relation{negation_words}.
- sentence_ids lists every sentence needed to support the triple, e.g. when the subject is only named in an
  earlier sentence and later referred to with a pronoun."""

STYLE = {
    "id": {"passive_example": '"CO2 diserap oleh daun" -> subject "daun", predicate "menyerap", object "CO2"',
           "negation_words": " (tidak, bukan, tanpa)"},
    "en": {"passive_example": '"an IP address is assigned by the server" -> subject "server", predicate "assigns", '
                              'object "IP address"',
           "negation_words": ' ("not", "never"); prefer a positive predicate such as "lacks" over a negated "has"'},
}

EXAMPLES = {
    "id": """Example 1
S1: Karbon dioksida diserap oleh daun.
{"triples": [{"sentence_ids": ["S1"], "subject": "daun", "predicate": "menyerap", "object": "karbon dioksida", "negated": false}]}

Example 2
S1: Fotosintesis terjadi di kloroplas.
S2: Proses ini tidak menghasilkan karbon dioksida.
{"triples": [{"sentence_ids": ["S1", "S2"], "subject": "fotosintesis", "predicate": "menghasilkan", "object": "karbon dioksida", "negated": true}]}

Example 3 (question: Apa yang digunakan tumbuhan untuk fotosintesis?)
S1: cahaya matahari dan air
{"triples": [{"sentence_ids": ["S1"], "subject": "tumbuhan", "predicate": "menggunakan", "object": "cahaya matahari", "negated": false},
             {"sentence_ids": ["S1"], "subject": "tumbuhan", "predicate": "menggunakan", "object": "air", "negated": false}]}""",
    "en": """Example 1
S1: An acknowledgement is sent by the receiver.
{"triples": [{"sentence_ids": ["S1"], "subject": "receiver", "predicate": "transmits", "object": "acknowledgement", "negated": false}]}

Example 2
S1: UDP is a transport protocol.
S2: It has no flow control.
{"triples": [{"sentence_ids": ["S1"], "subject": "UDP", "predicate": "is_a", "object": "transport protocol", "negated": false},
             {"sentence_ids": ["S1", "S2"], "subject": "UDP", "predicate": "lacks", "object": "flow control", "negated": false}]}

Example 3 (question: What is a router?)
S1: a device that forwards packets between networks
{"triples": [{"sentence_ids": ["S1"], "subject": "router", "predicate": "is_a", "object": "device that forwards packets between networks", "negated": false}]}""",
}


def for_language(predicates, language):
    """Only the predicates offered for this language (plus language-independent ones such as `other`)."""
    return {"predicates": [p for p in predicates["predicates"] if p.get("lang", "any") in (language, "any")]}


def alias_map(predicates):
    return {v.lower(): p["id"] for p in predicates["predicates"] for v in [p["id"], *p.get("aliases", [])]}


def schema(labels, predicates):
    triple = {
        "type": "object",
        "properties": {
            "sentence_ids": {"type": "array", "items": {"type": "string", "enum": labels}},
            "subject": {"type": "string"},
            # ids only: Gemini 2.5 rejects the enum with every alias (104 for English) as too much branching
            "predicate": {"type": "string", "enum": [p["id"] for p in predicates["predicates"]]},
            "object": {"type": "string"},
            "negated": {"type": "boolean"},
        },
        "required": ["sentence_ids", "subject", "predicate", "object", "negated"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"triples": {"type": "array", "items": triple}},
            "required": ["triples"], "additionalProperties": False}


def user_prompt(sentences, predicates, language="id", question=""):
    preds = "\n".join(f"- {p['id']}: {p['description']}" + (f" (alias: {', '.join(p['aliases'])})" if p.get("aliases") else "")
                      for p in predicates["predicates"])
    numbered = "\n".join(f"S{i}: {text}" for i, (_, text) in enumerate(sentences, 1))
    context = f"Question (context only, never a source of triples by itself):\n{question}\n\n" if question else ""
    return f"Predicates:\n{preds}\n\n{EXAMPLES[language]}\n\n{context}Student answer:\n{numbered}"


def grounded(span, text, threshold):
    """Share of the span's content tokens that appear in the cited text."""
    tokens = content_tokens(span)
    have = set(content_tokens(text))
    return bool(tokens) and sum(t in have for t in tokens) / len(tokens) >= threshold


def parse(answer_id, sentences, data, predicates, threshold, question=""):
    """Contract checks on raw LLM triples -> (kept StudentTriples, log of dropped ones).
    Subject or object (never both) may come from the question: a fragment answer leaves out what it names."""
    by_label = {f"S{i}": (sid, text) for i, (sid, text) in enumerate(sentences, 1)}
    aliases = alias_map(predicates)
    kept, log = [], []
    for raw in data.get("triples", []):
        drop = lambda reason: log.append({"answer_id": answer_id, "reason": reason, "triple": raw})
        if not raw.get("sentence_ids") or any(l not in by_label for l in raw["sentence_ids"]):
            drop("bad_sentence_id")
            continue
        p = aliases.get(str(raw.get("predicate", "")).lower())
        if p is None:
            drop("unknown_predicate")
            continue
        if p == "other":
            drop("other_predicate")
            continue
        s, o = (unicodedata.normalize("NFKC", raw[k]).strip() for k in ("subject", "object"))
        cited = " ".join(by_label[l][1] for l in raw["sentence_ids"])
        s_ok, o_ok = grounded(s, cited, threshold), grounded(o, cited, threshold)
        if not (s_ok and o_ok) and not ((s_ok or o_ok) and grounded(o if s_ok else s, question, threshold)):
            drop("not_grounded")
            continue
        kept.append(StudentTriple(id=f"{answer_id}_t{len(kept) + 1}", answer_id=answer_id, s_text=s, p=p,
                                  o_text=o, negated=bool(raw["negated"]),
                                  sentence_ids=[by_label[l][0] for l in raw["sentence_ids"]]))
    return kept, log


def extract_llm(answer_id, sentences, *, backend=None, predicates=None, threshold=None, language="id", question=""):
    if not sentences:
        return [], []
    predicates = for_language(predicates or io.load_predicates(), language)
    threshold = threshold if threshold is not None else io.load_config()["grounding_threshold"]
    labels = [f"S{i}" for i in range(1, len(sentences) + 1)]
    system = SYSTEM.format(language=LANGUAGES[language], **STYLE[language])
    data = llm.complete_json(system, user_prompt(sentences, predicates, language, question),
                             schema(labels, predicates), backend=backend)
    return parse(answer_id, sentences, data, predicates, threshold, question)


def extract_gold(answer_id, annotation=None, predicates=None):
    """Hand-annotated triples {triples: [{s, p, o, negated, sentences: [1, 2]}]}; from the database by default."""
    if annotation is None:
        annotation = db.annotation(answer_id)
    if annotation is None:
        raise LookupError(f"no triple annotation for {answer_id}")
    aliases = alias_map(predicates or io.load_predicates())
    out = []
    for i, raw in enumerate(annotation.get("triples") or [], 1):
        p = aliases.get(raw["p"].lower())
        if p is None or p == "other":
            raise ValueError(f"{answer_id}: triple {i} has unusable predicate {raw['p']!r}")
        out.append(StudentTriple(id=f"{answer_id}_t{i}", answer_id=answer_id, s_text=raw["s"], p=p, o_text=raw["o"],
                                 negated=bool(raw.get("negated", False)),
                                 sentence_ids=[f"{answer_id}_s{n}" for n in raw["sentences"]]))
    return out
