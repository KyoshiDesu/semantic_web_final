"""Interactive knowledge-graph explorer ("Semantic Explorer") for the demo app.

Node ids are the RDF names (ag: schema, key: lecturer's data, ans: student data) and edge labels are the RDF/OWL property names, so the picture is the same graph stored in the knowledge graph (gold, answer and ledger named graphs plus the ontology). The API serves it as JSON; web/js/graph.js draws it with vis-network 9.1.9 (web/vendor/).
"""
from autograde import db, gold, io
from autograde.match import mu
from autograde.models import STATUS_IRI_NAME, LedgerEntry, StudentTriple

NODE_TYPES = {  # key: (legend label, colour, vis shape, shown by default); colours are the pages' namespace palette
    "answer": ("Jawaban", "#6d28d9", "ellipse", True),
    "student": ("Triple jawaban", "#8b5cf6", "dot", True),
    "reference": ("Triple acuan", "#1d4ed8", "box", True),
    "concept": ("Konsep", "#047857", "dot", True),
    "unknown": ("Konsep tak dikenal", "#9ca3af", "dot", True),
    "relation": ("Predikat (ag:Relation)", "#b45309", "diamond", True),
    "sentence": ("Kalimat (PROV-O)", "#0e7490", "box", False),
}
EDGE_TYPES = {  # key: (legend label, colour, dashed, width, shown by default)
    "asserted": ("Relasi eksplisit (RDF)", "#94a3b8", False, 1, True),
    "ontology": ("Relasi ontologi (OWL)", "#b45309", False, 2, True),
    "match": ("Cocok / Parsial (ledger)", "#2e7d32", True, 2, True),
    "inferred": ("Disimpulkan Pellet (SWRL)", "#c62828", True, 3, True),
    "aligned": ("Selaras (masukan reasoner)", "#8b5cf6", True, 1, False),
    "hierarchy": ("Hierarki konsep (skos:broader)", "#047857", True, 2, True),
}

# The explorer's node details in each UI language; the web pages pass ?lang=.
TEXT = {
    "id": {
        "broader_partial": "{stud} lebih umum dari {key} (skos:broader) → kredit parsial",
        "narrower_same": "{stud} lebih khusus dari {key} (skos:broader) → dihitung sama",
        "answer_title": "Jawaban {aid}", "sentence_kind": "Kalimat (prov:Entity)", "text": "Teks",
        "answer": "Jawaban", "from_sentence": "Triple yang berasal dari kalimat ini",
        "unknown_title": "“{raw}” — tidak ada di tabel alias", "unknown_kind": "Konsep tak dikenal",
        "from_triple": "Dari triple", "role": "Peran", "why_grey": "Mengapa abu-abu?",
        "why_grey_text": "Kata ini tidak ada di tabel alias dosen, jadi dibandingkan dengan konsep kunci lewat "
                         "kemiripan embedding (0–1).",
        "rule1": "Aturan 1 (predikat inkompatibel)", "rule2": "Aturan 2 (predikat sama, dinegasi)",
        "rule3": "Aturan 3 (predikat setara, dinegasi)",
        "why_negated": "{tp} dinegasi, padahal kunci menyatakan {rp}",
        "why_incompatible": "{tp} incompatibleWith {rp}, tidak dinegasi",
        "contradiction": "{ref} · KONTRADIKSI — disimpulkan Pellet dengan {rule}: {why}; subjek dan objek selaras "
                         "(σ = {sig:.2f} ≥ τh {tau_h}) → ag:contradicts.",
        "matched": "Cocok", "partial": "Parsial",
        "band_full": "σ = {sig:.2f} ≥ τh {tau_h} → kredit 1",
        "band_partial": "τl {tau_l} ≤ σ = {sig:.2f} < τh {tau_h} → kredit δ {delta}, perlu ditinjau",
        "same_pred": "predikat sama", "equiv_pred": "predikat {tp} setara dengan {rp} (ontologi)",
        "match": "{ref} · {kind} — {same}; {band}{notes}. Dicatat di ledger sebagai bukti (ag:matchedBy).",
        "also_matches": "{ref} · juga cocok (σ = {sig:.2f}), tetapi triple lain dipilih sebagai bukti (aturan seri).",
        "aligned_only": "{ref} · selaras (σ = {sig:.2f}) tetapi predikat {tp} tidak setara dan tidak inkompatibel "
                        "dengan {rp} → tidak ada kredit, bukan kontradiksi.",
        "student_kind": "Triple jawaban (ag:StudentTriple)", "subject": "Subjek", "predicate": "Predikat",
        "object": "Objek", "alias_table": "(tabel alias)", "embedding": "? (embedding)", "negated": " — DINEGASI",
        "provenance": "Provenance (prov:wasDerivedFrom)", "reasoning": "Penalaran",
        "no_match": "Tidak cocok dengan triple acuan mana pun (σ < τl {tau_l} atau predikat lain).",
        "evidence": " (bukti {t})", "system_score": "Skor sistem", "sparql_recompute": "Hitung ulang SPARQL",
        "human_score": "Nilai manusia", "answer_kind": "Jawaban (ag:Answer)", "empty": "(kosong)",
        "ledger_heading": "Ledger (satu baris per triple acuan)", "relation_kind": "Predikat (ag:Relation)",
        "meaning": "Arti", "aliases_norm": "Alias (normalisasi)", "equivalent": "Setara (≡)",
        "incompatible": "Inkompatibel (⊥)", "from_owl": "Dari ontologi OWL",
        "owl_note": "≡ simetris dan transitif: dihitung cocok. ⊥ simetris: bahan aturan kontradiksi SWRL.",
        "by": " (oleh {t})", "reference_kind": "Triple acuan (ag:ReferenceTriple)",
        "accepted_subjects": "Subjek diterima", "criterion": "Kriteria", "weight": "Bobot",
        "status_in": "Status di {n} jawaban yang dimuat", "none_graded": "Belum ada jawaban dinilai.",
        "as_subject": "subjek", "as_object": "objek", "concept_kind": "Konsep (ag:Concept, skos:Concept)",
        "aliases_lecturer": "Alias (tabel dosen)", "broader": "Lebih umum (skos:broader+)",
        "narrower": "Lebih khusus", "used_by": "Dipakai oleh",
    },
    "en": {
        "broader_partial": "{stud} is broader than {key} (skos:broader) → partial credit",
        "narrower_same": "{stud} is narrower than {key} (skos:broader) → counts the same",
        "answer_title": "Answer {aid}", "sentence_kind": "Sentence (prov:Entity)", "text": "Text",
        "answer": "Answer", "from_sentence": "Triples derived from this sentence",
        "unknown_title": "“{raw}” — not in the alias table", "unknown_kind": "Unknown concept",
        "from_triple": "From triple", "role": "Role", "why_grey": "Why grey?",
        "why_grey_text": "This word is not in the lecturer's alias table, so it is compared with the key's concepts "
                         "by embedding similarity (0–1).",
        "rule1": "Rule 1 (incompatible predicate)", "rule2": "Rule 2 (same predicate, negated)",
        "rule3": "Rule 3 (equivalent predicate, negated)",
        "why_negated": "{tp} is negated, but the key states {rp}",
        "why_incompatible": "{tp} incompatibleWith {rp}, not negated",
        "contradiction": "{ref} · CONTRADICTION — inferred by Pellet with {rule}: {why}; subject and object aligned "
                         "(σ = {sig:.2f} ≥ τh {tau_h}) → ag:contradicts.",
        "matched": "Matched", "partial": "Partial",
        "band_full": "σ = {sig:.2f} ≥ τh {tau_h} → credit 1",
        "band_partial": "τl {tau_l} ≤ σ = {sig:.2f} < τh {tau_h} → credit δ {delta}, needs review",
        "same_pred": "same predicate", "equiv_pred": "predicate {tp} is equivalent to {rp} (ontology)",
        "match": "{ref} · {kind} — {same}; {band}{notes}. Recorded in the ledger as evidence (ag:matchedBy).",
        "also_matches": "{ref} · also matches (σ = {sig:.2f}), but another triple was chosen as evidence (tie rule).",
        "aligned_only": "{ref} · aligned (σ = {sig:.2f}) but predicate {tp} is neither equivalent nor incompatible "
                        "with {rp} → no credit, not a contradiction.",
        "student_kind": "Student triple (ag:StudentTriple)", "subject": "Subject", "predicate": "Predicate",
        "object": "Object", "alias_table": "(alias table)", "embedding": "? (embedding)", "negated": " — NEGATED",
        "provenance": "Provenance (prov:wasDerivedFrom)", "reasoning": "Reasoning",
        "no_match": "Matches no reference triple (σ < τl {tau_l} or another predicate).",
        "evidence": " (evidence {t})", "system_score": "System score", "sparql_recompute": "SPARQL recompute",
        "human_score": "Lecturer score", "answer_kind": "Answer (ag:Answer)", "empty": "(empty)",
        "ledger_heading": "Ledger (one row per reference triple)", "relation_kind": "Predicate (ag:Relation)",
        "meaning": "Meaning", "aliases_norm": "Aliases (normalisation)", "equivalent": "Equivalent (≡)",
        "incompatible": "Incompatible (⊥)", "from_owl": "From the OWL ontology",
        "owl_note": "≡ symmetric and transitive: counts as a match. ⊥ symmetric: input to the SWRL contradiction rules.",
        "by": " (by {t})", "reference_kind": "Reference triple (ag:ReferenceTriple)",
        "accepted_subjects": "Accepted subjects", "criterion": "Criterion", "weight": "Weight",
        "status_in": "Status in the {n} loaded answers", "none_graded": "No answers graded yet.",
        "as_subject": "subject", "as_object": "object", "concept_kind": "Concept (ag:Concept, skos:Concept)",
        "aliases_lecturer": "Aliases (lecturer's table)", "broader": "Broader (skos:broader+)",
        "narrower": "Narrower", "used_by": "Used by",
    },
}


def short_answer(qid, answer_id):
    return answer_id[len(qid) + 1:] if answer_id.startswith(qid + "_") else answer_id


def load_answer(run_id, answer_id):
    """One graded answer as stored by pipeline.run_answer."""
    r = db.result(run_id, answer_id)
    if r is None:
        raise LookupError(f"{answer_id} is not in run {run_id}")
    return {"answer_id": answer_id,
            "students": [StudentTriple(**t) for t in r["students"]],
            "entries": [LedgerEntry(**e) for e in r["ledger"]],
            "sentences": [tuple(s) for s in r["sentences"]],
            "score": r["score"],
            "sigmas": {(t, ref): s for t, ref, s in r["trace"]["sigmas"]},
            "aligned": {tuple(x) for x in r["trace"]["aligned"]},
            "contradictions": {tuple(x) for x in r["trace"]["contradictions"]}}


def build(ctx, answers, params, human=None, predicates=None, lang="id"):
    """{nodes, edges, details} for one question and any number of graded answers; details in `lang` (id or en)."""
    T = TEXT[lang]
    qid, human = ctx.qid, human or {}
    preds = {p["id"]: p for p in (predicates or io.load_predicates())["predicates"]}
    criteria = {c["id"]: c["description"] for c in ctx.rubric["criteria"]}
    nodes, edges, details = {}, [], {}

    def node(nid, kind, label, title):
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "title": title})

    def edge(src, dst, kind, label, title=None):
        edges.append({"from": src, "to": dst, "kind": kind, "label": label, "title": title or label})

    # --- the lecturer's key (gold graph) ---
    ref_status = {r.id: [] for r in ctx.refs}
    for r in ctx.refs:
        rid = f"key:{qid}_{r.id}"
        node(rid, "reference", r.id, f"{r.id}: {' / '.join(r.s)} {r.p} {r.o}")
        for s in r.s:
            edge(rid, f"key:{s}", "asserted", "hasSubject")
        edge(rid, f"ag:{r.p}", "asserted", "hasPredicate")
        edge(rid, f"key:{r.o}", "asserted", "hasObject")
    concepts = ctx.gold_raw["concepts"]
    above = gold.ancestors(concepts)
    for c, spec in concepts.items():
        node(f"key:{c}", "concept", c, c)
        for b in (spec or {}).get("broader") or []:
            edge(f"key:{c}", f"key:{b}", "hierarchy", "skos:broader")

    def hierarchy_note(key_c, stud_c):
        if key_c and stud_c and key_c != stud_c:
            if stud_c in above.get(key_c, ()):
                return T["broader_partial"].format(stud=stud_c, key=key_c)
            if key_c in above.get(stud_c, ()):
                return T["narrower_same"].format(stud=stud_c, key=key_c)
        return None

    # --- the graded answers (answer + ledger graphs) ---
    used_preds = {r.p for r in ctx.refs}
    by_triple = {}
    for a in answers:
        aid, short = a["answer_id"], short_answer(qid, a["answer_id"])
        node(f"ans:{aid}", "answer", f"{short} · {a['score']['score']:.0f}", T["answer_title"].format(aid=aid))
        text = dict(a["sentences"])
        matched = {(e.matched_by, e.reference_id): e for e in a["entries"] if e.matched_by}
        for e in a["entries"]:
            ref_status[e.reference_id].append((short, e))
        for sid, sent in a["sentences"]:
            node(f"ans:{sid}", "sentence", sid.rsplit("_", 1)[1], sent)
            details[f"ans:{sid}"] = {"kind": T["sentence_kind"], "title": f"ans:{sid}",
                                    "fields": [[T["text"], sent], [T["answer"], aid]],
                                    "sections": [{"heading": T["from_sentence"],
                                                  "items": [t.id for t in a["students"] if sid in t.sentence_ids] or ["—"]}]}
        for t in a["students"]:
            tid, tn = f"ans:{t.id}", t.id.rsplit("_", 1)[1]
            by_triple[t.id] = t
            used_preds.add(t.p)
            neg = "NOT " if t.negated else ""
            node(tid, "student", f"{short}·{tn}", f"{t.s_text} —{neg}{t.p}→ {t.o_text}")
            edge(tid, f"ans:{aid}", "asserted", "inAnswer")
            edge(tid, f"ag:{t.p}", "asserted", "hasPredicate")
            for role, concept, raw in (("hasSubject", t.s_concept, t.s_text), ("hasObject", t.o_concept, t.o_text)):
                if concept:
                    edge(tid, f"key:{concept}", "asserted", role)
                else:
                    cid = f"ans:{t.id}_{'s' if role == 'hasSubject' else 'o'}"
                    node(cid, "unknown", raw, T["unknown_title"].format(raw=raw))
                    details[cid] = {"kind": T["unknown_kind"], "title": raw,
                                    "fields": [[T["from_triple"], t.id], [T["role"], role]],
                                    "sections": [{"heading": T["why_grey"], "items": [T["why_grey_text"]]}]}
                    edge(tid, cid, "asserted", role)
            for sid in t.sentence_ids:
                edge(tid, f"ans:{sid}", "asserted", "prov:wasDerivedFrom")
            reasoning = []
            for r in ctx.refs:
                sig = a["sigmas"].get((t.id, r.id), 0.0)
                rid, e = f"key:{qid}_{r.id}", matched.get((t.id, r.id))
                if (t.id, r.id) in a["contradictions"]:
                    if t.negated:
                        rule = T["rule2"] if t.p == r.p else T["rule3"]
                        why = T["why_negated"].format(tp=t.p, rp=r.p)
                    else:
                        rule, why = T["rule1"], T["why_incompatible"].format(tp=t.p, rp=r.p)
                    edge(tid, rid, "inferred", "contradicts", f"{rule}: {why}")
                    reasoning.append(T["contradiction"].format(ref=r.id, rule=rule, why=why, sig=sig,
                                                               tau_h=params["tau_h"]))
                elif e:
                    kind = T["matched"] if e.status == "MATCHED" else T["partial"]
                    edge(tid, rid, "match", f"{kind} σ={sig:.2f}", f"ledger: {e.entry_id} ag:matchedBy {t.id}")
                    band = (T["band_full"] if e.status == "MATCHED" else T["band_partial"]).format(
                        sig=sig, tau_h=params["tau_h"], tau_l=params["tau_l"], delta=params["delta"])
                    same = T["same_pred"] if t.p == r.p else T["equiv_pred"].format(tp=t.p, rp=r.p)
                    notes = [n for n in (hierarchy_note(r.o, t.o_concept),
                                         *(hierarchy_note(k, t.s_concept) for k in r.s)) if n]
                    reasoning.append(T["match"].format(ref=r.id, kind=kind.upper(), same=same, band=band,
                                                       notes=f" ({'; '.join(notes)})" if notes else ""))
                elif mu(r, t, sig, params, ctx.rel) > 0:
                    reasoning.append(T["also_matches"].format(ref=r.id, sig=sig))
                elif (t.id, r.id) in a["aligned"]:
                    edge(tid, rid, "aligned", "aligned", f"alignedSubject + alignedObject (σ = {sig:.2f})")
                    reasoning.append(T["aligned_only"].format(ref=r.id, sig=sig, tp=t.p, rp=r.p))
            details[tid] = {
                "kind": T["student_kind"], "title": f"{t.s_text} —{neg}{t.p}→ {t.o_text}",
                "fields": [["IRI", tid], [T["answer"], aid],
                           [T["subject"], f"“{t.s_text}” → " + (f"key:{t.s_concept} {T['alias_table']}" if t.s_concept
                                                              else T["embedding"])],
                           [T["predicate"], f"ag:{t.p}" + (T["negated"] if t.negated else "")],
                           [T["object"], f"“{t.o_text}” → " + (f"key:{t.o_concept} {T['alias_table']}" if t.o_concept
                                                             else T["embedding"])]],
                "sections": [{"heading": T["provenance"],
                              "items": [f"{s.rsplit('_', 1)[1]}: “{text.get(s, '')}”" for s in t.sentence_ids]},
                             {"heading": T["reasoning"],
                              "items": reasoning or [T["no_match"].format(tau_l=params["tau_l"])]}]}
        status_line = lambda e: (f"{e.reference_id} · {STATUS_IRI_NAME[e.status]} · {e.credit:g} × {e.weight:g}"
                                 + (T["evidence"].format(t=e.matched_by or e.contradicted_by)
                                    if e.matched_by or e.contradicted_by else ""))
        sc = a["score"]
        fields = [[T["system_score"], f"{sc['score']:.1f}"], [T["sparql_recompute"], f"{sc['sparql_score']:.1f}"]]
        if aid in human:
            fields.append([T["human_score"], f"{human[aid]:.1f}"])
        details[f"ans:{aid}"] = {"kind": T["answer_kind"], "title": f"ans:{aid}", "fields": fields,
                                "sections": [{"heading": T["text"], "items": [s for _, s in a["sentences"]] or [T["empty"]]},
                                             {"heading": T["ledger_heading"],
                                              "items": [status_line(e) for e in a["entries"]]}]}

    # --- the ontology's predicate vocabulary (OWL) ---
    _, eq, inc = io.ontology_relations()
    for p in sorted(used_preds):
        node(f"ag:{p}", "relation", p, preds.get(p, {}).get("description", p))
    for p in sorted(used_preds):
        for q in sorted(eq.get(p, {p}) - {p}):
            node(f"ag:{q}", "relation", q, preds.get(q, {}).get("description", q))
        for pair in inc:
            if p in pair:
                q = next(iter(pair - {p}))
                node(f"ag:{q}", "relation", q, preds.get(q, {}).get("description", q))
    shown_rel = {n["label"] for n in nodes.values() if n["kind"] == "relation"}
    seen = set()
    for a, b_set in eq.items():
        for b in b_set - {a}:
            if a in shown_rel and b in shown_rel and frozenset((a, b)) not in seen:
                seen.add(frozenset((a, b)))
                edge(f"ag:{a}", f"ag:{b}", "ontology", "≡ equivalentPredicate")
    for pair in inc:
        a, b = sorted(pair)
        if a in shown_rel and b in shown_rel:
            edge(f"ag:{a}", f"ag:{b}", "ontology", "⊥ incompatibleWith")
    for p in shown_rel:
        details[f"ag:{p}"] = {"kind": T["relation_kind"], "title": f"ag:{p}",
                              "fields": [[T["meaning"], preds.get(p, {}).get("description", "—")],
                                         [T["aliases_norm"], ", ".join(preds.get(p, {}).get("aliases", [])) or "—"],
                                         [T["equivalent"], ", ".join(sorted(eq.get(p, {p}) - {p})) or "—"],
                                         [T["incompatible"],
                                          ", ".join(sorted(next(iter(x - {p})) for x in inc if p in x)) or "—"]],
                              "sections": [{"heading": T["from_owl"], "items": [T["owl_note"]]}]}

    # --- details for key facts and concepts ---
    for r in ctx.refs:
        lines = [f"{s} · {STATUS_IRI_NAME[e.status]}"
                 + (T["by"].format(t=(e.matched_by or e.contradicted_by).rsplit("_", 1)[1])
                    if e.matched_by or e.contradicted_by else "")
                 for s, e in ref_status[r.id]]
        details[f"key:{qid}_{r.id}"] = {
            "kind": T["reference_kind"], "title": f"{r.id}: {' / '.join(r.s)} {r.p} {r.o}",
            "fields": [["IRI", f"key:{qid}_{r.id}"], [T["accepted_subjects"], ", ".join(r.s)],
                       [T["predicate"], r.p], [T["object"], r.o],
                       [T["criterion"], f"{r.criterion} — {criteria[r.criterion]}"], [T["weight"], f"{r.weight:g}"]],
            "sections": [{"heading": T["status_in"].format(n=len(lines)), "items": lines or [T["none_graded"]]}]}
    for c, spec in concepts.items():
        users = [f"{r.id} ({T['as_subject'] if c in r.s else T['as_object']})" for r in ctx.refs if c in r.s or c == r.o]
        users += [t.id.rsplit("_", 2)[-2] + "·" + t.id.rsplit("_", 1)[1] for t in by_triple.values()
                  if c in (t.s_concept, t.o_concept)]
        narrower = sorted(x for x, ups in above.items() if c in ups)
        details[f"key:{c}"] = {"kind": T["concept_kind"], "title": f"key:{c}",
                              "fields": [[T["aliases_lecturer"], ", ".join((spec or {}).get("aliases", [])) or "—"],
                                         [T["broader"], ", ".join(sorted(above.get(c, ()))) or "—"],
                                         [T["narrower"], ", ".join(narrower) or "—"]],
                              "sections": [{"heading": T["used_by"], "items": users or ["—"]}]}
    return {"nodes": list(nodes.values()), "edges": edges, "details": details}
