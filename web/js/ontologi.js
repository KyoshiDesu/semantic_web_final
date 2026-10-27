// Ontologi: the ag: OWL ontology: class hierarchy, properties, predicates and their relations, SWRL rules, the file.
import { api } from "./api.js";
import { dot } from "./graph.js";
import { t } from "./i18n.js";
import { code, el, errorPanel, field, iri, records, report, select, start, stat, table, tabs } from "./ui.js";

async function relations(p, o) {
  const graph = el("div");
  const list = el("div");
  const filter = select([["all", t("ontologi.lang_all")], ["id", t("ontologi.lang_id")], ["en", t("ontologi.lang_en")]], "all");
  const show = async data => {
    list.replaceChildren(table(records(data.predicates.map(x => ({ ...x, aliases: x.aliases || [] })),
      ["id", "lang", "aliases", "description"])));
    await dot(graph, data.relations_dot);
  };
  filter.addEventListener("change", async () => {
    try {
      await show(filter.value === "all" ? o : await api.get("/ontology", { lang: filter.value }));
    } catch (e) {
      list.replaceChildren(errorPanel(e));
      report(e);
    }
  });
  p.replaceChildren(field(t("ontologi.lang_filter"), filter), graph,
    el("p", { class: "small muted" }, t("ontologi.relations_help")), list);
  await show(o);
}

function rules(items) {
  return el("div", {}, el("p", {}, t("ontologi.rules_intro")),
    items.map(r => [el("h3", {}, r.title), code(r.rule.replaceAll(" ^ ", " ^\n  ").replace(" -> ", "\n  -> "))]),
    el("p", { class: "small muted" }, t("ontologi.rules_legend")));
}

function owlFile(owl) {
  const file = URL.createObjectURL(new Blob([owl], { type: "application/rdf+xml" }));
  return el("div", {}, el("div", { class: "actions" },
    el("a", { class: "btn secondary", href: file, download: "autograde.owl" }, t("ontologi.download"))),
  code(owl.length > 6000 ? `${owl.slice(0, 6000)}\n…` : owl));
}

start("ontologi.html", "nav.ontology", async main => {
  const o = await api.get("/ontology");
  const body = el("div");
  main.replaceChildren(el("h1", {}, t("ontologi.title")),
    el("p", { class: "small muted" }, t("ontologi.intro"), " ", iri(o.graph)),
    el("div", { class: "stats" }, Object.entries(o.counts).map(([k, v]) => stat(t(`ontologi.count_${k}`), v))),
    body);
  await tabs(body, [
    { id: "classes", label: t("ontologi.tab_classes"), render: async p => {
      const g = el("div");
      p.replaceChildren(g, el("p", { class: "small muted" }, t("ontologi.classes_help")));
      await dot(g, o.classes_dot);
    } },
    { id: "properties", label: t("ontologi.tab_properties"), render: async p => p.replaceChildren(table(o.properties)) },
    { id: "relations", label: t("ontologi.tab_relations"), render: p => relations(p, o) },
    { id: "rules", label: t("ontologi.tab_rules"), render: async p => p.replaceChildren(rules(o.rules)) },
    { id: "owl", label: t("ontologi.tab_owl"), render: async p => p.replaceChildren(owlFile(o.owl)) },
  ]);
});
