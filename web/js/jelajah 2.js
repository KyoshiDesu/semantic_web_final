// Penjelajah Graf: one question's knowledge graph with the chosen graded answers, drawn with vis-network.
import { api } from "./api.js";
import { network } from "./graph.js";
import { lang, t } from "./i18n.js";
import { el, fail, field, fill, href, param, select, start } from "./ui.js";

start("jelajah.html", "nav.explorer", async main => {
  const questions = await api.get("/questions");
  if (!questions.length) throw fail("not_found", t("jelajah.no_questions"));
  const qid = param("question") || questions[0].id;
  const run = param("run") || "";
  const chosen = (param("answers") || "").split(",").filter(Boolean);
  const data = await api.get(`/questions/${encodeURIComponent(qid)}/explorer`,
    { run, answers: chosen.join(","), lang: lang() });
  const source = data.sources.find(s => s.run_id === run);
  const shown = new Set(chosen.length ? chosen : (source?.answers || []).slice(0, 12));
  const boxes = (source?.answers || []).map(a => el("label", {}, el("input", { type: "checkbox", value: a, checked: shown.has(a) }), " ", a));
  const go = params => location.assign(href("jelajah.html", params));
  const questionPick = select(questions.map(q => [q.id, q.id]), qid, { onchange: e => go({ question: e.target.value }) });
  const runPick = select([["", t("jelajah.key_only")], ...data.sources.map(s => [s.run_id, t("jelajah.source", { run: s.run_id, n: s.answers.length })])],
    run, { onchange: e => go({ question: qid, run: e.target.value }) });
  const graph = el("div");
  fill(main, el("h1", {}, t("jelajah.title")), el("p", { class: "small muted" }, t("jelajah.intro")),
    el("div", { class: "row" }, field(t("jelajah.question"), questionPick), field(t("jelajah.run"), runPick)),
    source ? el("fieldset", {}, el("legend", {}, t("jelajah.answers")), el("div", { class: "row" }, boxes),
      el("button", { type: "button", class: "btn secondary", onclick: () => go({ question: qid, run,
        answers: boxes.map(b => b.firstChild).filter(i => i.checked).map(i => i.value).join(",") }) }, t("jelajah.show")))
      : data.sources.length ? null : el("p", { class: "muted" }, t("jelajah.none_graded")),
    graph);
  await network(graph, data.graph, data.node_types, data.edge_types, { height: 640 });
});
