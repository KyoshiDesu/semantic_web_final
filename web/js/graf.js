// Graf Pengetahuan: every named graph of the Oxigraph store; one graph as Turtle, an interactive view and a table.
import { api, url } from "./api.js";
import { network } from "./graph.js";
import { t } from "./i18n.js";
import { code, dl, el, fail, href, iri, param, records, start, stat, table, tabs } from "./ui.js";

start("graf.html", "nav.kg", async main => {
  const graphs = await api.get("/graphs");
  const name = param("name");
  const body = el("div");
  main.replaceChildren(el("h1", {}, t("graf.title")), el("p", { class: "small muted" }, t("graf.intro")),
    el("div", { class: "stats" }, stat(t("graf.named_graphs"), graphs.length),
      stat(t("graf.triples"), graphs.reduce((n, g) => n + g.triples, 0)),
      stat(t("graf.runs"), new Set(graphs.map(g => g.run).filter(Boolean)).size)),
    el("div", { class: "actions" }, el("a", { class: "btn secondary", href: "sparql.html" }, t("graf.query_all"))),
    table(records(graphs, ["name", "kind", "question", "run", "answer", "triples"]),
      { cell: (c, v) => (c === "name" ? el("a", { href: href("graf.html", { name: v }) }, v) : undefined) }),
    body);
  if (!name) return;
  if (!graphs.some(g => g.name === name)) throw fail("not_found", t("graf.unknown", { name }));
  body.replaceChildren(el("h2", {}, iri(name)));
  await tabs(body, [
    { id: "turtle", label: "Turtle", render: async p => p.replaceChildren(
      el("div", { class: "actions" }, dl(url("/graphs/turtle", { name }), t("common.download"))),
      code(await api.text("/graphs/turtle", { name }))) },
    { id: "view", label: t("graf.tab_view"), render: async p => {
      const v = await api.get("/graphs/view", { name });
      await network(p, v.graph, v.node_types, v.edge_types);
    } },
    { id: "triples", label: t("graf.tab_triples"), render: async p => {
      // the name comes from the store's own list (checked above), so it is safe inside the query
      const r = await api.post("/sparql", { query: `SELECT ?s ?p ?o WHERE { GRAPH <${name}> { ?s ?p ?o } } ORDER BY ?s ?p ?o` });
      p.replaceChildren(table({ columns: ["subject", "predicate", "object"], rows: r.rows }));
    } },
  ]);
});
