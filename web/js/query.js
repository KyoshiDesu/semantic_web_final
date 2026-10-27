// The SPARQL console: a template picker, an editor (Ctrl+Enter runs it) and the result as a table or Turtle.
import { api } from "./api.js";
import { lang, t } from "./i18n.js";
import { button, code, el, field, iri, loading, select, table } from "./ui.js";

export async function sparqlConsole(container, { graphs = null, scope = "kg", template = null } = {}) {
  const templates = await api.get("/sparql/templates", { scope, lang: lang() });
  const names = Object.keys(templates);
  const first = template && templates[template] ? template : names[0];
  const picker = select(names.map(n => [n, n]), first);
  const editor = el("textarea", { class: "code", spellcheck: "false", "aria-label": t("sparql.query"),
    value: templates[first] ?? "" });
  picker.addEventListener("change", () => { editor.value = templates[picker.value]; });
  const out = el("div", { class: "results", "aria-live": "polite" });
  const run = button(t("sparql.run"), async () => {
    out.replaceChildren(loading());
    try {
      const res = await api.post("/sparql", { query: editor.value, graphs });
      out.replaceChildren(...(res.kind === "turtle"
        ? [code(res.turtle || t("sparql.empty_graph"))]
        : [table(res, { translate: false }), el("p", { class: "small muted" }, t("sparql.rows", { n: res.rows.length }))]));
    } catch (e) {
      out.replaceChildren();
      throw e;
    }
  }, { kind: "primary", slot: out });
  editor.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      run.click();
    }
  });
  container.replaceChildren(
    el("p", { class: "small muted" }, graphs ? [t("sparql.over_graphs"), " ", graphs.map(g => [iri(g), " "])] : t("sparql.over_store")),
    field(t("sparql.template"), picker), editor,
    el("div", { class: "actions" }, run, el("span", { class: "small muted" }, t("sparql.shortcut"))), out);
}
