// Soal: the question list; one question's key with its graphs and Turtle, its answers, and grading one now.
import { api, url } from "./api.js";
import { dot } from "./graph.js";
import { t } from "./i18n.js";
import { button, code, dl, el, field, href, iri, loading, panel, param, records, score, select, start, stripComments,
  table, tabs, triple } from "./ui.js";

const enc = encodeURIComponent;

async function list(main) {
  const qs = await api.get("/questions");
  main.replaceChildren(el("div", { class: "row" }, el("h1", {}, t("soal.title"))),
    table(records(qs, ["id", "prompt", "language", "assessment_id", "answers", "results"]), { cell: (c, v) => {
      if (c === "id") return el("a", { href: href("soal.html", { id: v }) }, v);
      if (c === "prompt") {
        const s = stripComments(v);
        return s.length > 120 ? `${s.slice(0, 120)}…` : s;
      }
      return undefined;
    } }));
}

function notice(g) {
  if (g.drafted_by) return el("div", { class: "notice" }, t("soal.drafted", { by: g.drafted_by }));
  if (!g.validated_by) return el("div", { class: "notice" }, t("soal.not_validated"));
  return el("p", { class: "small muted" }, t("soal.validated", { by: g.validated_by }));
}

async function keyTab(p, qid, g) {
  const graph = el("div");
  const view = select([["concept", t("soal.concept_graph")], ["reified", t("soal.reified_graph")]], "concept");
  view.addEventListener("change", () => dot(graph, view.value === "concept" ? g.concept_dot : g.reified_dot));
  p.replaceChildren(
    el("div", { class: "grid2" }, panel(t("soal.prompt"), el("p", {}, stripComments(g.prompt))),
      panel(t("soal.reference"), el("p", {}, stripComments(g.reference_answer)))),
    panel(t("soal.criteria"), table(records(g.criteria, ["id", "description", "weight"]))),
    panel(t("soal.triples"), table(records(g.triples.map(r => ({ ...r, triple: r })), ["id", "triple", "criterion", "weight"]),
      { cell: (c, v) => (c === "triple" ? triple({ s: v.s.join(" / "), p: v.p, o: v.o, negated: false }) : undefined) })),
    panel(t("soal.concepts"), el("p", { class: "small muted" }, t("soal.concepts_help")),
      table(records(g.concepts, ["concept", "aliases", "broader"]), { cell: (c, v) => (c === "concept" ? iri(`key:${v}`) : undefined) })),
    panel(t("soal.graph"), el("p", { class: "small muted" }, t("soal.graph_help"), " ", iri(g.graph)),
      field(t("soal.graph_view"), view), graph),
    panel("Turtle", el("div", { class: "actions" }, dl(url("/graphs/turtle", { name: g.graph }), t("common.download")),
      dl(url(`/questions/${enc(qid)}/files.zip`), t("soal.zip"))), code(g.turtle)));
  await dot(graph, g.concept_dot);
}

function tryResult(res) {
  return panel(null,
    el("div", { class: "row" }, iri(`ans:${res.answer_id}`), el("span", { class: "score-big" }, score(res.score.score)),
      el("span", { class: res.recompute.ok ? "check-ok" : "check-bad" }, `${res.recompute.ok ? "✓" : "✗"} SPARQL ${score(res.score.sparql_score)}`),
      el("span", {}, t("soal.baseline", { score: score(res.baseline_b1) }))),
    el("a", { href: href("jawaban.html", { run: res.run_id, answer: res.answer_id }) }, t("soal.open_result")));
}

async function answersTab(p, qid) {
  const data = await api.get(`/questions/${enc(qid)}/answers`);
  const col = name => data.columns.indexOf(name);
  const llm = el("input", { type: "checkbox" });
  const result = el("div", { "aria-live": "polite" });
  const grade = body => async () => {
    result.replaceChildren(loading());
    try {
      result.replaceChildren(tryResult(await api.post(`/questions/${enc(qid)}/try`, { ...body, llm_feedback: llm.checked })));
    } catch (e) {
      result.replaceChildren();
      throw e;
    }
  };
  const pasted = el("textarea", { rows: 4 });
  const rows = { columns: [...data.columns, "try"], rows: data.rows.map(r => [...r, null]) };
  p.replaceChildren(
    el("p", { class: "small muted" }, t("soal.try_help")), el("label", {}, llm, " ", t("soal.llm_feedback")), result,
    table(rows, { cell: (c, v, row) => {
      if (c === "try") {
        return button(t("soal.try"), grade({ answer_id: row[col("answer_id")], mode: row[col("annotated")] ? "gold" : "llm" }),
          { slot: result });
      }
      if (c === "human") return score(v);
      return undefined;
    } }),
    panel(t("soal.paste_title"), field(t("soal.paste"), pasted),
      el("div", { class: "actions" }, button(t("soal.try_pasted"), () => grade({ text: pasted.value, mode: "llm" })(),
        { kind: "primary", slot: result }))));
}

async function question(main, qid) {
  const g = await api.get(`/questions/${enc(qid)}/gold`);
  const body = el("div");
  main.replaceChildren(
    el("div", { class: "row" }, el("h1", {}, qid), el("span", { class: "chip" }, g.language.toUpperCase()),
      el("a", { href: href("jelajah.html", { question: qid }) }, t("soal.explore"))),
    notice(g), body);
  await tabs(body, [
    { id: "kunci", label: t("soal.tab_key"), render: p => keyTab(p, qid, g) },
    { id: "jawaban", label: t("soal.tab_answers"), render: p => answersTab(p, qid) },
  ]);
}

start("soal.html", "soal.title", async main => {
  const qid = param("id");
  if (qid) await question(main, qid);
  else await list(main);
});
