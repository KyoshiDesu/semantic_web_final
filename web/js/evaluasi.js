// Evaluasi: research runs (made by the CLI), their evaluation reports and figures. Read-only.
import { Marked } from "/vendor/marked.esm.js";
import { api, url } from "./api.js";
import { t } from "./i18n.js";
import { el, errorPanel, href, iri, param, records, report, start, table } from "./ui.js";

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
// Raw HTML inside the Markdown is shown as text: the report is the only HTML string this app renders.
const markdown = new Marked({ renderer: { html: ({ text }) => text.replace(/[&<>"']/g, c => ESCAPES[c]) } });

async function detail(box, id) {
  const r = await api.get(`/runs/${encodeURIComponent(id)}`);
  const doc = el("div", { class: "panel report" });
  if (r.evaluation_md) doc.innerHTML = markdown.parse(r.evaluation_md);
  else doc.append(el("p", { class: "muted" }, t("evaluasi.no_report", { run: id })));
  box.replaceChildren(el("h2", {}, iri(id)),
    el("h3", {}, t("evaluasi.params")),
    table(records(Object.entries(r.params).map(([parameter, value]) => ({ parameter, value })), ["parameter", "value"])),
    doc,
    el("div", { class: "grid2" }, r.figures.map(f => el("figure", {},
      el("img", { src: url(`/runs/${encodeURIComponent(id)}/figures/${encodeURIComponent(f)}`), alt: f, style: { maxWidth: "100%" } }),
      el("figcaption", { class: "small" }, f)))));
}

start("evaluasi.html", "nav.evaluation", async main => {
  const runs = await api.get("/runs");
  const id = param("run");
  const box = el("div");
  main.replaceChildren(el("h1", {}, t("evaluasi.title")), el("p", { class: "small muted" }, t("evaluasi.intro")),
    table(records(runs, ["run_id", "mode", "split", "question", "reasoner", "created", "finished", "results", "has_evaluation"]),
      { cell: (c, v) => (c === "run_id" ? el("a", { href: href("evaluasi.html", { run: v }) }, v) : undefined) }),
    box);
  if (!id) return;
  try {
    await detail(box, id);
  } catch (e) {
    box.replaceChildren(errorPanel(e));
    report(e);
  }
});
