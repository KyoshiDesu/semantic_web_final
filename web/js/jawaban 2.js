// Jawaban: one graded answer: score and SPARQL check, ledger, graphs, reasoning, RDF, SPARQL, OWL, and its review.
import { api, url } from "./api.js";
import { dot, network } from "./graph.js";
import { lang, t } from "./i18n.js";
import { sparqlConsole } from "./query.js";
import { button, code, dl, el, fail, fill, fmt, href, iri, ledgerChip, panel, param, records, requireReviewer,
  score, select, start, stat, statusChip, table, tabs, toast } from "./ui.js";

const enc = encodeURIComponent;
const LEDGER_STATUSES = ["MATCHED", "PARTIAL", "MISSING", "CONTRADICTED"];

const statusOf = r => (r.stale ? "usang" : r.reviewed ? "ditinjau" : "dinilai");

function sparqlCheck(r) {
  const c = r.recompute;
  return el("details", { class: "panel" },
    el("summary", {}, el("span", { class: c.ok ? "check-ok" : "check-bad" }, c.ok ? "✓ " : "✗ "),
      t("jawaban.check", { python: score(c.python), sparql: score(c.sparql) })),
    el("p", { class: "small muted" }, t("jawaban.check_graphs"), " ", c.graphs.map(g => [iri(g), " "])),
    code(c.query),
    table({ columns: ["answer", "raw"], rows: c.rows.map(x => [x.answer, x.raw]) }));
}

function header(r, run, answer) {
  const sc = r.score;
  return el("section", { class: "panel" },
    el("div", { class: "row" }, el("h1", {}, iri(`ans:${answer}`)), el("span", { id: "answer-status" }, statusChip(statusOf(r)))),
    el("p", { class: "muted" }, t("jawaban.meta", { question: r.question_id, run, graded: r.graded || "—" }), " · ",
      el("a", { href: href("soal.html", { id: r.question_id }) }, t("jawaban.open_question")),
      r.reviewed_by ? ` · ${t("jawaban.reviewed_by", { by: r.reviewed_by })}` : ""),
    el("div", { class: "row" },
      el("div", {}, el("div", { class: "score-big" }, score(sc.score)), el("div", { class: "small muted" }, t("jawaban.system_score"))),
      r.score_corrected ? el("div", {}, el("div", { class: "score-big" }, score(r.score_corrected.score)),
        el("div", { class: "small muted" }, t("jawaban.corrected_score"))) : null,
      el("div", { class: "stats" }, stat("Σ w·m", fmt(sc.sum_weighted_credit)), stat(t("jawaban.penalty"), fmt(sc.sum_penalty)),
        stat("Σ w", fmt(sc.sum_weights)))),
    sparqlCheck(r),
    el("div", { class: "actions" }, dl(url("/export/owl", { run, answer }), t("jawaban.owl"))));
}

function ledgerTable(entries, sentences, controls = null) {
  const text = Object.fromEntries(sentences);
  const byRef = Object.fromEntries(entries.map(e => [e.reference_id, e]));
  const columns = ["ref", "reference", "criterion", "weight", "status", "credit", "sigma", "evidence", "override"];
  if (controls) columns.push("correct_to", "reason");
  const rows = entries.map(e => columns.map(c => ({
    ref: e.reference_id, reference: e.reference ?? t("jawaban.not_in_key"), criterion: e.criterion, weight: e.weight,
    status: e.status, credit: e.credit, sigma: e.sigma,
    evidence: e.sentence_ids.map(s => text[s]).filter(Boolean).join(" ") || null,
    override: e.override ? `${e.override.by}: ${e.override.reason}` : null, correct_to: null, reason: null,
  })[c]));
  return table({ columns, rows }, { cell: (c, v, row) => {
    const e = byRef[row[0]];
    if (c === "ref") return el("code", {}, v);
    if (c === "status") return [ledgerChip(v), e.needs_review ? " ⚑" : ""];
    if (c === "correct_to") return controls[e.reference_id].select;
    if (c === "reason") return controls[e.reference_id].reason;
    return undefined;
  } });
}

function reviewControls(entries) {
  return Object.fromEntries(entries.map(e => [e.reference_id, {
    entry: e,
    select: select(LEDGER_STATUSES.map(s => [s, t(`ledger.${s}`)]), e.status,
      { "aria-label": t("review.status_for", { ref: e.reference_id }) }),
    reason: el("input", { "aria-label": t("review.reason_for", { ref: e.reference_id }) }),
  }]));
}

async function nextToReview(assessmentId, current) {
  const st = await api.get(`/assessments/${assessmentId}/status`);
  const col = name => st.columns.indexOf(name);
  const pending = st.rows.filter(row => row[col("status")] === "dinilai" && row[col("answer_id")] !== current)
    .sort((a, b) => (b[col("flagged")] - a[col("flagged")]) || (b[col("contradictions")] - a[col("contradictions")]));
  return pending.length ? pending[0][col("answer_id")] : null;
}

async function reviewBlock(r, run, answer, refresh, controls) {
  if (!r.assessment_id) return null;
  if (r.stale) {
    return el("div", { class: "notice" }, t("review.stale"), " ",
      el("a", { href: href("penilaian.html", { id: r.assessment_id }) }, t("review.to_assessment")));
  }
  const next = await nextToReview(r.assessment_id, answer);
  const nextLink = next ? el("a", { href: href("jawaban.html", { run, answer: next }) }, t("review.next"))
    : el("span", { class: "muted" }, t("review.none_left"));
  if (r.reviewed) return el("div", { class: "actions" }, el("span", {}, t("review.done", { by: r.reviewed_by })), nextLink);
  const changed = () => Object.values(controls).filter(c => c.select.value !== c.entry.status);
  const slot = el("div");
  const save = button(t("review.save"), async () => {
    if (!changed().length) throw fail("invalid", t("review.nothing_changed"));
    const by = requireReviewer();
    const res = await api.post(`/results/${enc(run)}/${enc(answer)}/corrections`, { by,
      corrections: changed().map(c => ({ reference_id: c.entry.reference_id, status: c.select.value, reason: c.reason.value })) });
    toast(t("review.saved", { score: score(res.score.score), sparql: score(res.score.sparql_score) }));
    await refresh();
  }, { slot });
  const mark = button(t("review.mark"), async () => {
    if (changed().length) throw fail("invalid", t("review.save_first"));
    const by = requireReviewer();
    await api.post(`/results/${enc(run)}/${enc(answer)}/review`, { by });
    toast(t("review.marked", { answer }));
    await refresh();
  }, { kind: "primary", slot });
  return el("section", { class: "panel" }, el("h2", {}, t("review.title")), el("p", { class: "small muted" }, t("review.help")),
    el("div", { class: "actions" }, save, mark, nextLink), slot);
}

async function ledgerTab(p, r, run, answer, refresh) {
  const reviewable = Boolean(r.assessment_id) && !r.stale && !r.reviewed;
  const controls = reviewable ? reviewControls(r.ledger_corrected || r.ledger) : null;
  const fb = r.feedback;
  fill(p,
    await reviewBlock(r, run, answer, refresh, controls),
    el("h2", {}, t("jawaban.ledger")), ledgerTable(r.ledger, r.sentences, r.ledger_corrected ? null : controls),
    r.ledger_corrected ? [el("h2", {}, t("jawaban.ledger_corrected")), ledgerTable(r.ledger_corrected, r.sentences, controls)] : null,
    panel(t("jawaban.feedback"),
      el("ul", {}, fb.claims.map(c => el("li", {}, c.text, " ", el("small", { class: "muted" }, `(${c.ledger_entry_ids.join(", ")})`)))),
      el("p", {}, el("em", {}, fb.summary)),
      el("p", { class: "small muted" }, t(fb.source === "llm" ? "jawaban.feedback_llm" : "jawaban.feedback_template"))),
    panel(t("jawaban.sentences"), el("ol", {}, r.sentences.map(([id, s]) => el("li", {}, iri(`ans:${id}`), " ", s)))));
}

async function reasoningTab(p, r, base) {
  const v = await api.get(`${base}/views/reasoning`);
  const prm = v.params;
  const q = r.question_id;
  const before = el("div");
  const after = el("div");
  fill(p,
    el("h2", {}, t("jawaban.step_normalise")),
    el("p", { class: "small" }, t("jawaban.params", { tau_h: prm.tau_h, tau_l: prm.tau_l, delta: prm.delta, lam: prm.lambda })),
    table(records(v.students.map(s => ({ triple: s.id, subject: s.s_text, s_concept: s.s_concept ?? "? (embedding)", predicate: s.p,
      negated: s.negated, object: s.o_text, o_concept: s.o_concept ?? "? (embedding)", sentences: s.sentence_ids.join(", ") })),
    ["triple", "subject", "s_concept", "predicate", "negated", "object", "o_concept", "sentences"])),
    el("h2", {}, t("jawaban.step_sigma")),
    v.sigma ? table(v.sigma, { translate: false }) : el("p", { class: "muted" }, t("common.empty")),
    el("h2", {}, t("jawaban.step_aligned", { n: v.aligned.length })),
    v.aligned.length ? code(v.aligned.map(([s, ref]) =>
      `ans:${s} ag:alignedSubject key:${q}_${ref} ; ag:alignedObject key:${q}_${ref} .`).join("\n")) : null,
    el("h2", {}, t("jawaban.step_contradictions", { n: v.contradictions.length })),
    v.contradictions.length ? code(v.contradictions.map(([s, ref]) => `ans:${s} ag:contradicts key:${q}_${ref} .`).join("\n"))
      : el("p", { class: "muted" }, t("jawaban.no_contradictions")),
    el("h2", {}, t("jawaban.step_pellet")),
    v.pellet ? el("div", { class: "grid2" }, el("div", {}, el("p", { class: "small" }, t("jawaban.before")), before),
      el("div", {}, el("p", { class: "small" }, t("jawaban.after")), after)) : el("p", { class: "muted" }, t("jawaban.no_aligned")),
    v.extraction_log.length ? el("details", {}, el("summary", {}, t("jawaban.log", { n: v.extraction_log.length })),
      code(JSON.stringify(v.extraction_log, null, 2))) : null);
  if (v.pellet) await Promise.all([dot(before, v.pellet.before), dot(after, v.pellet.after)]);
}

async function rdfTab(p, r) {
  const names = [...r.graphs, ...(r.ledger_corrected ? [`${r.graphs[2]}_corrected`] : [])];
  const blocks = await Promise.all(names.map(async name => el("details", { open: name.endsWith(":ledger") },
    el("summary", {}, iri(name)),
    el("div", { class: "actions" }, dl(url("/graphs/turtle", { name }), t("common.download"))),
    code(await api.text("/graphs/turtle", { name })))));
  fill(p, el("p", { class: "small muted" }, t("jawaban.rdf_help")), blocks);
}

start("jawaban.html", "jawaban.title", async (main, refresh) => {
  const run = param("run");
  const answer = param("answer");
  if (!run || !answer) throw fail("not_found", t("jawaban.missing"));
  const base = `/results/${enc(run)}/${enc(answer)}`;
  const r = await api.get(base);
  const body = el("div");
  main.replaceChildren(header(r, run, answer), body);
  await tabs(body, [
    { id: "ledger", label: t("jawaban.tab_ledger"), render: p => ledgerTab(p, r, run, answer, refresh) },
    { id: "graph", label: t("jawaban.tab_graph"), render: async p => {
      const g = await api.get(`${base}/views/graph`, { lang: lang() });
      await network(p, g.graph, g.node_types, g.edge_types);
    } },
    { id: "alignment", label: t("jawaban.tab_alignment"), render: async p => {
      const a = await api.get(`${base}/views/alignment`);
      const box = el("div");
      p.replaceChildren(box, el("p", { class: "small muted" }, t("jawaban.alignment_help"), " ", iri(a.graph)));
      await dot(box, a.dot);
    } },
    { id: "reasoning", label: t("jawaban.tab_reasoning"), render: p => reasoningTab(p, r, base) },
    { id: "rdf", label: t("jawaban.tab_rdf"), render: p => rdfTab(p, r) },
    { id: "sparql", label: t("jawaban.tab_sparql"), render: p => sparqlConsole(p, { graphs: r.graphs, scope: "answer" }) },
  ]);
});
