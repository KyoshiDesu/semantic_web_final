// Beranda: the hero naming each Semantic Web piece, quick demos, and the answer search with one card per answer.
import { api } from "./api.js";
import { lang, t } from "./i18n.js";
import { $, debounced, el, href, iri, report, score, showError, start, STATUS, statusChip, statusClass, triple } from "./ui.js";

const FILTERS = ["contradiction", "flagged", "corrected", "ungraded"];

function hero(firstQuestion) {
  const pieces = [["piece_rdf", "graf.html", "ns-key"], ["piece_owl", "ontologi.html", "ns-ag"],
    ["piece_swrl", "ontologi.html#rules", "ns-swrl"],
    ["piece_skos", firstQuestion ? `${href("soal.html", { id: firstQuestion })}#kunci` : "soal.html", "ns-skos"],
    ["piece_prov", "graf.html", "ns-prov"], ["piece_sparql", "sparql.html", "ns-other"]];
  return el("section", { class: "panel hero" },
    el("div", { class: "prefixes" }, t("home.prefixes")),
    el("h1", {}, t("home.title")),
    el("p", { class: "lead" }, t("home.lead")),
    el("nav", { class: "chips", "aria-label": t("home.pieces") },
      pieces.map(([key, link, cls]) => el("a", { href: link, class: cls, id: key.replace("piece_", "piece-") },
        t(`home.${key}`)))));
}

function card(a) {
  const graded = a.status !== STATUS.ungraded;
  return el("article", { class: `card ${statusClass(a.status)}${a.contradictions ? " contradiction" : ""}` },
    el("header", {}, iri(`ans:${a.answer_id}`), el("span", { class: "score" }, score(a.final))),
    el("p", { class: "small muted" }, `${a.question_id} · ${a.name || a.external_id}`),
    a.triple ? triple(a.triple) : el("p", { class: "small" }, a.text.length > 140 ? `${a.text.slice(0, 140)}…` : a.text),
    el("p", {}, statusChip(a.status)),
    graded ? el("a", { href: href("jawaban.html", { run: a.run_id, answer: a.answer_id }) }, t("search.explore"))
      : el("a", { href: href("penilaian.html", { id: a.assessment_id }) }, t("search.to_grading")));
}

start("index.html", "nav.home", async main => {
  const [questions, templates] = await Promise.all([api.get("/questions"),
    api.get("/sparql/templates", { scope: "kg", lang: lang() })]);
  const input = el("input", { type: "search", placeholder: t("search.placeholder"), "aria-label": t("search.label") });
  const results = el("div", { "aria-live": "polite" });
  let filter = null;
  const search = debounced(250, async current => {
    try {
      const rows = await api.get("/answers", { q: input.value, filter });
      if (!current()) return;  // a newer search already answered
      results.replaceChildren(rows.length ? el("div", { class: "cards" }, rows.map(card)) : el("p", { class: "muted" }, t("search.none")),
        el("p", { class: "small muted" }, t("search.count", { n: rows.length })));
      const first = rows.find(r => r.status !== STATUS.ungraded);
      if (first) $("#piece-prov").href = `${href("jawaban.html", { run: first.run_id, answer: first.answer_id })}#ledger`;
    } catch (e) {
      if (current()) showError(results, e);
      else report(e);
    }
  });
  const chips = FILTERS.map(f => el("button", { type: "button", "aria-pressed": "false", onclick: () => {
    filter = filter === f ? null : f;
    chips.forEach((c, i) => c.setAttribute("aria-pressed", String(FILTERS[i] === filter)));
    search.now();
  } }, t(`search.filter_${f}`)));
  input.addEventListener("input", search.later);
  const demos = Object.keys(templates).slice(0, 2).map(name => el("a", { href: href("sparql.html", { template: name }) }, name));
  main.replaceChildren(hero(questions[0]?.id),
    el("section", {}, el("h2", {}, t("search.title")),
      el("div", { class: "chips" }, chips, el("span", { class: "small muted" }, t("search.templates")), demos),
      input, results));
  await search.now();
});
