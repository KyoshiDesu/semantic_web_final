// The question editor: the key's tables as editable rows, a live preview (the errors or the gold graph), saving.
import { api } from "./api.js";
import { dot } from "./graph.js";
import { t } from "./i18n.js";
import { button, code, el, errorPanel, field, fill, iri, panel, report, select, toast } from "./ui.js";

export const EMPTY_DRAFT = { prompt: "", reference_answer: "", language: "id", validated_by: "",
  criteria: [{ id: "K1", description: "" }], concepts: [], triples: [] };

const split = value => value.split(",").map(s => s.trim()).filter(Boolean);

// One editable table over `items` (the draft's rows, edited in place). kind: text, list (comma-separated), number, select.
function rowsEditor(spec, items, onChange) {
  const body = el("tbody");
  const control = (s, item, i) => {
    const label = `${s.label} ${i + 1}`;
    if (s.kind === "select") {
      const options = s.options();
      if (item[s.key] && !options.some(([v]) => v === item[s.key])) {
        options.push([item[s.key], `${item[s.key]} (${t("editor.unknown")})`]);
      }
      return select([["", "—"], ...options], item[s.key] ?? "", { "aria-label": label,
        onchange: e => { item[s.key] = e.target.value; onChange(); } });
    }
    const value = s.kind === "list" ? (item[s.key] || []).join(", ") : item[s.key] ?? "";
    return el("input", { type: s.kind === "number" ? "number" : "text", step: s.kind === "number" ? "0.5" : null,
      min: s.kind === "number" ? "0.1" : null, list: s.datalist || null, value: String(value), "aria-label": label,
      oninput: e => {
        const v = e.target.value;
        item[s.key] = s.kind === "list" ? split(v) : s.kind === "number" ? (v === "" ? null : Number(v)) : v;
        onChange();
      } });
  };
  const render = () => body.replaceChildren(...items.map((item, i) => el("tr", {},
    spec.map(s => el("td", {}, control(s, item, i))),
    el("td", {}, el("button", { type: "button", class: "btn danger", "aria-label": t("editor.remove_row", { n: i + 1 }),
      onclick: () => { items.splice(i, 1); render(); onChange(); } }, "×")))));
  render();
  const element = el("div", {},
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, spec.map(s => el("th", {}, s.label)),
      el("th", {}))), body)),
    el("button", { type: "button", class: "btn secondary", onclick: () => { items.push({}); render(); onChange(); } },
      t("editor.add_row")));
  return { element, render };
}

export async function editor(container, { qid = null, draft, baseId = null, assessments = null, onSaved }) {
  const d = structuredClone(draft);
  let predicates = await api.get("/predicates", { lang: d.language });
  const concepts = () => d.concepts.map(c => (c.concept || "").trim()).filter(Boolean);
  const criteria = () => d.criteria.map(c => (c.id || "").trim()).filter(Boolean);
  const datalist = el("datalist", { id: "concepts-list" });
  const status = el("p", { class: "small muted", "aria-live": "polite" });
  const preview = el("div");
  const newId = qid ? null : el("input", { placeholder: "Q2" });
  const target = assessments ? select(assessments.map(a => [String(a.id), a.label]), String(assessments[0].id)) : null;
  let seq = 0;
  let timer = null;

  const save = button(t("editor.save"), async () => {
    if (qid) {
      const r = await api.put(`/questions/${encodeURIComponent(qid)}`, d);
      toast(t("editor.saved", { id: qid, n: r.stale_results }));
      await onSaved(qid);
    } else {
      const r = await api.post("/questions", { id: newId.value.trim(), assessment_id: Number(target.value), draft: d });
      await onSaved(r.id);
    }
  }, { kind: "primary", disabled: true });

  async function check() {
    const mine = ++seq;
    save.disabled = true;
    status.textContent = t("editor.checking");
    let res;
    try {
      res = await api.post("/questions/preview", { id: qid || newId.value.trim() || "Q_NEW", draft: d, base_id: baseId });
    } catch (e) {
      if (mine === seq) {
        status.textContent = "";
        preview.replaceChildren(errorPanel(e));
        report(e);
      }
      return;
    }
    if (mine !== seq) return;  // a newer edit is already being checked
    save.disabled = !res.valid;
    status.textContent = t(res.valid ? "editor.valid" : "editor.invalid");
    if (!res.valid) {
      preview.replaceChildren(el("div", { class: "error", role: "alert" }, el("strong", {}, t("editor.not_valid")),
        el("ul", {}, res.errors.map(x => el("li", {}, x)))));
      return;
    }
    const graph = el("div");
    const view = select([["concept", t("soal.concept_graph")], ["reified", t("soal.reified_graph")], ["turtle", "Turtle"],
      ["yaml", "YAML"]], "concept");
    const show = async () => {
      if (view.value === "turtle") graph.replaceChildren(code(res.turtle));
      else if (view.value === "yaml") graph.replaceChildren(code(res.yaml));
      else await dot(graph, view.value === "concept" ? res.concept_dot : res.reified_dot);
    };
    view.addEventListener("change", show);
    preview.replaceChildren(el("p", { class: "small muted" }, t("editor.graph_after"), " ", iri(res.graph)),
      field(t("editor.preview_view"), view), graph);
    await show();
  }

  const syncConcepts = () => datalist.replaceChildren(...concepts().map(c => el("option", { value: c })));
  const changed = () => {
    syncConcepts();
    clearTimeout(timer);
    timer = setTimeout(check, 500);
  };
  const triples = rowsEditor([
    { key: "id", label: t("col.id"), kind: "text" },
    { key: "s", label: t("col.subject"), kind: "list", datalist: "concepts-list" },
    { key: "p", label: t("col.predicate"), kind: "select", options: () => predicates.map(p => [p.id, p.id]) },
    { key: "o", label: t("col.object"), kind: "select", options: () => concepts().map(c => [c, c]) },
    { key: "criterion", label: t("col.criterion"), kind: "select", options: () => criteria().map(c => [c, c]) },
    { key: "weight", label: t("col.weight"), kind: "number" },
  ], d.triples, changed);
  const linked = () => {  // the triples' dropdowns list the concepts and criteria
    triples.render();
    changed();
  };
  const criteriaRows = rowsEditor([{ key: "id", label: t("col.id"), kind: "text" },
    { key: "description", label: t("col.description"), kind: "text" }], d.criteria, linked);
  const conceptRows = rowsEditor([{ key: "concept", label: t("col.concept"), kind: "text" },
    { key: "aliases", label: t("col.aliases"), kind: "list" },
    { key: "broader", label: t("col.broader"), kind: "list", datalist: "concepts-list" }], d.concepts, linked);
  const text = key => el("textarea", { rows: 4, value: d[key], oninput: e => { d[key] = e.target.value; changed(); } });
  const language = select([["id", t("editor.lang_id")], ["en", t("editor.lang_en")]], d.language, {
    onchange: async e => {
      d.language = e.target.value;
      predicates = await api.get("/predicates", { lang: d.language });
      triples.render();
      changed();
    } });
  const validated = el("input", { value: d.validated_by || "", oninput: e => { d.validated_by = e.target.value; changed(); } });
  if (newId) newId.addEventListener("input", changed);
  fill(container, datalist,
    newId ? panel(null, el("div", { class: "row" }, field(t("editor.new_id"), newId), field(t("editor.assessment"), target))) : null,
    el("div", { class: "grid2" }, field(t("soal.prompt"), text("prompt")), field(t("soal.reference"), text("reference_answer"))),
    el("div", { class: "row" }, field(t("editor.language"), language), field(t("editor.validated_by"), validated)),
    panel(t("soal.criteria"), criteriaRows.element),
    panel(t("soal.concepts"), el("p", { class: "small muted" }, t("soal.concepts_help")), conceptRows.element),
    panel(t("soal.triples"), el("p", { class: "small muted" }, t("editor.triples_help")), triples.element),
    panel(t("editor.preview"), status, preview),
    el("div", { class: "actions" }, save));
  syncConcepts();
  await check();
}
