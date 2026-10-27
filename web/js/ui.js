// Shared page building blocks: the DOM builder (text only, never HTML), nav, tables, tabs, chips, errors, start-up.
import { init, lang, setLang, t } from "./i18n.js";

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k === "style") Object.assign(n.style, v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (["value", "checked", "disabled", "hidden", "selected", "open"].includes(k)) n[k] = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c !== null && c !== undefined && c !== false) n.append(c instanceof Node ? c : String(c));
  }
  return n;
}

const kids = children => children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false);
// replaceChildren/append with el()'s rules: arrays flattened, null skipped (the native calls would print them)
export const fill = (node, ...children) => { node.replaceChildren(...kids(children)); return node; };
export const add = (node, ...children) => { node.append(...kids(children)); return node; };
export const $ = (selector, root = document) => root.querySelector(selector);
export const param = name => new URLSearchParams(location.search).get(name);
export const stripComments = text => (text || "").replace(/<!--[\s\S]*?-->/g, "").trim();
export const score = v => (v === null || v === undefined ? "—" : Number(v).toFixed(1));

export function href(file, params = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, v);
  }
  const s = q.toString();
  return s ? `${file}?${s}` : file;
}

export function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

export function table(data, { cell = null, translate = true, empty = null } = {}) {
  if (!data.rows.length) return el("p", { class: "muted" }, empty ?? t("common.empty"));
  const head = data.columns.map(c => el("th", { scope: "col" }, translate ? t(`col.${c}`, { fallback: c }) : c));
  const rows = data.rows.map(row => el("tr", {}, row.map((v, i) => {
    const custom = cell ? cell(data.columns[i], v, row) : undefined;
    return el("td", { class: typeof v === "number" ? "num" : null }, custom ?? fmt(v));
  })));
  return el("div", { class: "table-wrap" },
    el("table", {}, el("thead", {}, el("tr", {}, head)), el("tbody", {}, rows)));
}

export const records = (items, columns) => ({ columns, rows: items.map(o => columns.map(c => o[c])) });

export function loading() {
  return el("p", { class: "muted", role: "status" }, t("common.loading"));
}

export function fail(code, message) {
  return Object.assign(new Error(message), { code });
}

export function report(error) {
  if (!error.code) console.error(error);  // an unexpected error is a bug: keep it visible in the console
}

export function errorPanel(error, home = false) {
  const code = error.code || "internal";
  const hint = { busy: "error.busy_hint", offline: "error.offline_hint" }[code];
  return el("div", { class: "error", role: "alert" },
    el("strong", {}, t(`error.${code}`, { fallback: t("error.internal") })),
    el("p", {}, error.message),
    hint ? el("p", {}, t(hint)) : null,
    error.details?.length ? el("ul", {}, error.details.map(d => el("li", {}, d))) : null,
    home ? el("p", {}, el("a", { href: "index.html" }, t("common.home"))) : null);
}

export function toast(message) {
  const n = el("div", { class: "toast" }, message);
  $("#toasts").append(n);
  setTimeout(() => n.remove(), 6000);
}

export function button(label, onClick, { kind = "secondary", slot = null, disabled = false } = {}) {
  const b = el("button", { type: "button", class: `btn ${kind}`, disabled }, label);
  b.addEventListener("click", async () => {
    const where = slot || b.parentElement;
    where.querySelectorAll(":scope > .error").forEach(x => x.remove());
    b.disabled = true;
    try {
      await onClick(b);
    } catch (e) {
      where.append(errorPanel(e));
      report(e);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}

export const dl = (link, label) => el("a", { class: "btn secondary", href: link, download: true }, label);
export const code = text => el("pre", { class: "code" }, el("code", {}, text));
export const panel = (title, ...children) => el("section", { class: "panel" }, title ? el("h2", {}, title) : null, children);
export const field = (label, control) => el("label", { class: "field" }, el("span", {}, label), control);
export const stat = (label, value) => el("div", { class: "stat" }, el("b", {}, value), el("span", { class: "small" }, label));

export function select(options, value, attrs = {}) {
  return el("select", attrs, options.map(([v, label]) => el("option", { value: v, selected: v === value }, label)));
}

const NAMESPACES = ["key", "ans", "ag", "skos", "prov"];

export function iri(text) {
  const ns = String(text).split(":")[0];
  return el("code", { class: `iri ns-${NAMESPACES.includes(ns) ? ns : "other"}` }, text);
}

export const statusChip = status =>
  el("span", { class: `chip st-${status.replace(" ", "-")}` }, t(`status.${status}`, { fallback: status }));
export const ledgerChip = status =>
  el("span", { class: `chip ld-${status.toLowerCase()}` }, t(`ledger.${status}`, { fallback: status }));

export function triple(tr) {
  return el("div", { class: "triple" },
    el("span", { class: "node" }, tr.s), el("span", { class: "edge" }, `—${tr.negated ? "NOT " : ""}${tr.p}→`),
    el("span", { class: "node" }, tr.o),
    tr.contradicts ? el("div", { class: "contra" }, "⟂ ag:contradicts ", iri(tr.contradicts)) : null);
}

export function tabs(parent, specs) {
  const panels = specs.map(s => el("section", { role: "tabpanel", id: `panel-${s.id}`, "aria-labelledby": `tab-${s.id}`, hidden: true }));
  const rendered = new Set();
  const buttons = specs.map((s, i) => el("button", {
    type: "button", role: "tab", id: `tab-${s.id}`, "aria-controls": `panel-${s.id}`, "aria-selected": "false",
    tabindex: "-1", onclick: () => open(s.id, true),
    onkeydown: e => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      const next = (i + step + specs.length) % specs.length;
      open(specs[next].id, true);
      buttons[next].focus();
    },
  }, s.label));
  parent.append(el("div", { class: "tabs", role: "tablist" }, buttons), ...panels);

  async function open(id, remember) {
    const i = Math.max(0, specs.findIndex(s => s.id === id));
    if (remember) history.replaceState(null, "", `#${specs[i].id}`);
    buttons.forEach((b, j) => {
      b.setAttribute("aria-selected", String(j === i));
      b.tabIndex = j === i ? 0 : -1;
    });
    panels.forEach((p, j) => { p.hidden = j !== i; });
    if (rendered.has(i)) return;
    rendered.add(i);
    panels[i].replaceChildren(loading());
    try {
      await specs[i].render(panels[i]);
    } catch (e) {
      panels[i].replaceChildren(errorPanel(e));
      report(e);
    }
  }
  return open(location.hash.slice(1), false);
}

const REVIEWER = "autograde.reviewer";

export function reviewer() {
  try {
    return (localStorage.getItem(REVIEWER) || "").trim();
  } catch {
    return "";
  }
}

export function requireReviewer() {
  const input = $("#reviewer");
  const by = (input?.value || "").trim();
  if (!by) {
    input?.focus();
    throw fail("invalid", t("error.reviewer"));
  }
  return by;
}

const MAIN = [["index.html", "nav.home"], ["kelas.html", "nav.classes"], ["soal.html", "nav.questions"]];
const SEMANTIC = [["ontologi.html", "nav.ontology"], ["graf.html", "nav.kg"], ["jelajah.html", "nav.explorer"],
  ["sparql.html", "nav.sparql"]];

function nav(active) {
  const link = ([file, key]) => el("a", { href: file, class: file === active ? "active" : null,
    "aria-current": file === active ? "page" : null }, t(key));
  const menu = el("details", { class: SEMANTIC.some(([f]) => f === active) ? "menu active" : "menu" },
    el("summary", {}, t("nav.semantic")), el("div", { class: "menu-items" }, SEMANTIC.map(link)));
  document.addEventListener("click", e => { if (!menu.contains(e.target)) menu.open = false; });
  const who = el("input", { id: "reviewer", class: "mono reviewer-input", value: reviewer(),
    placeholder: t("nav.reviewer_placeholder"), onchange: e => {
      try {
        localStorage.setItem(REVIEWER, e.target.value.trim());
      } catch {
        // storage blocked: the name lasts until the page reloads
      }
    } });
  return el("nav", { class: "topnav", "aria-label": t("nav.label") },
    el("a", { href: "index.html", class: "brand" }, "ag:AutoGrade"), MAIN.map(link), menu,
    link(["evaluasi.html", "nav.evaluation"]), el("span", { class: "spacer" }),
    el("label", { for: "reviewer" }, t("nav.reviewer")), who,
    el("span", { class: "langs", role: "group", "aria-label": t("nav.language") },
      ["id", "en"].map(l => el("button", { type: "button", "aria-pressed": String(l === lang()),
        onclick: () => setLang(l) }, l.toUpperCase()))));
}

export async function start(active, titleKey, render) {
  await init();
  document.title = `${t(titleKey)} · AutoGrade-RDF`;
  document.body.prepend(nav(active));
  document.body.append(el("div", { id: "toasts", class: "toasts", "aria-live": "polite" }));
  const main = $("main");
  const refresh = async () => {
    main.replaceChildren(loading());
    try {
      await render(main, refresh);
    } catch (e) {
      main.replaceChildren(errorPanel(e, true));
      report(e);
    }
  };
  await refresh();
}
