// Konsol SPARQL: the console over the whole store, or over named graphs chosen here (one run's at a time).
import { api } from "./api.js";
import { t } from "./i18n.js";
import { sparqlConsole } from "./query.js";
import { el, field, href, param, select, start, ticked } from "./ui.js";

start("sparql.html", "nav.sparql", async main => {
  const graphs = await api.get("/graphs");
  const chosen = (param("graphs") || "").split(",").filter(Boolean);
  const boxes = graphs.map(g => el("label", { class: "small" },
    el("input", { type: "checkbox", value: g.name, checked: chosen.includes(g.name) }), " ", g.name));
  const runs = [...new Set(graphs.map(g => g.run).filter(Boolean))];
  const pickRun = select([["", t("sparql_page.none")], ...runs.map(r => [r, r])], "", { onchange: e => {
    for (const b of boxes) {  // one run: its answer and ledger graphs plus every question's key
      const g = graphs.find(x => x.name === b.firstChild.value);
      b.firstChild.checked = g.kind === "gold" || (g.run === e.target.value && g.kind !== "ledger_corrected");
    }
  } });
  const box = el("div");
  main.replaceChildren(el("h1", {}, t("sparql_page.title")), el("p", { class: "small muted" }, t("sparql_page.intro")),
    el("details", { class: "panel", open: chosen.length > 0 }, el("summary", {}, t("sparql_page.scope")),
      field(t("sparql_page.pick_run"), pickRun), el("div", { class: "graph-list" }, boxes),
      el("div", { class: "actions" },
        el("button", { type: "button", class: "btn secondary", onclick: () => location.assign(href("sparql.html", {
          graphs: ticked(boxes).join(",") })) }, t("sparql_page.use_graphs")),
        el("a", { class: "btn secondary", href: "sparql.html" }, t("sparql_page.whole_store")))),
    box);
  await sparqlConsole(box, { graphs: chosen.length ? chosen : null, scope: chosen.length ? "run" : "kg", template: param("template") });
});
