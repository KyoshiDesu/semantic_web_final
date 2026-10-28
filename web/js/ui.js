// Shared page building blocks: the DOM builder (text only, never HTML), nav, tables, tabs, chips, errors, start-up.
import { query } from "./api.js";
import { init, lang, setLang, t } from "./i18n.js";

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
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
export const href = (file, params = {}) => `${file}${query(params)}`;
export const stripComments = text => (text || "").replace(/<!--[\s\S]*?-->/g, "").trim();
export const score = v => (v === null || v === undefined ? "—" : Number(v).toFixed(1));

export function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

export function table(data, { cell = null, translate = true } = {}) {
  if (!data.rows.length) return el("p", { class: "muted" }, t("common.empty"));
  const head = data.columns.map(c => el("th", { scope: "col" }, translate ? t(`col.${c}`, { fallback: c }) : c));
  const rows = data.rows.map(row => el("tr", {}, row.map((v, i) => {
    const custom = cell ? cell(data.columns[i], v, row) : undefined;
    return el("td", { class: typeof v === "number" ? "num" : null }, custom ?? fmt(v));
  })));
  return el("div", { class: "table-wrap" },
    el("table", {}, el("thead", {}, el("tr", {}, head)), el("tbody", {}, rows)));
}

export const records = (items, columns) => ({ columns, rows: items.map(o => columns.map(c => o[c])) });
// a reader for one column of an API table: column(data, "status")(row)
export const column = (data, name) => {
  const i = data.columns.indexOf(name);
  return row => row[i];
};
// the values of the ticked boxes among labels built as <label><input type=checkbox value=…> text</label>
export const ticked = labels => labels.map(l => l.firstChild).filter(i => i.checked).map(i => i.value);

export function loading() {
  return el("p", { class: "muted", role: "status" }, t("common.loading"));
}

// Shows "loading" in box while job runs, then its result; on failure empties box and rethrows (for button()).
export async function into(box, job) {
  box.replaceChildren(loading());
  try {
    fill(box, await job());
  } catch (e) {
    box.replaceChildren();
    throw e;
  }
}

// run(current) is called ms after the last later(), or at once with now(); current() is false once a newer call
// started, so a slow response never overwrites a newer one (search boxes, the editor preview).
export function debounced(ms, run) {
  let timer = null;
  let seq = 0;
  const now = () => {
    const mine = ++seq;
    return run(() => mine === seq);
  };
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(now, ms);
  };
  return { now, later };
}

export function fail(code, message) {
  return Object.assign(new Error(message), { error: code });
}

export function report(error) {
  if (!error.error) console.error(error);  // an unexpected error is a bug: keep it visible in the console
}

function errorPanel(error, home = false) {
  const code = error.error || "internal";
  const hint = { busy: "error.busy_hint", offline: "error.offline_hint" }[code];
  return el("div", { class: "error", role: "alert" },
    el("strong", {}, t(`error.${code}`, { fallback: t("error.internal") })),
    error.message ? el("p", {}, error.message) : null,
    hint ? el("p", {}, t(hint)) : null,
    error.details?.length ? el("ul", {}, error.details.map(d => el("li", {}, d))) : null,
    home ? el("p", {}, el("a", { href: "index.html" }, t("common.home"))) : null);
}

export function showError(node, error, { home = false, append = false } = {}) {
  if (append) node.append(errorPanel(error, home));
  else node.replaceChildren(errorPanel(error, home));
  report(error);
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
      showError(where, e, { append: true });
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

// The core's grading statuses (the API sends these values; status.<value> translates them).
export const STATUS = { ungraded: "belum dinilai", stale: "usang", graded: "dinilai", reviewed: "ditinjau" };
export const statusClass = status => `st-${status.replace(" ", "-")}`;
export const statusChip = status =>
  el("span", { class: `chip ${statusClass(status)}` }, t(`status.${status}`, { fallback: status }));
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
      showError(panels[i], e);
    }
  }
  return open(location.hash.slice(1), false);
}

const REVIEWER = "autograde.reviewer";
let current = "";
let navButton = null;

function storedReviewer() {
  try {
    return (localStorage.getItem(REVIEWER) || "").trim();
  } catch {
    return "";
  }
}

function setReviewer(by) {
  current = by;
  try {
    localStorage.setItem(REVIEWER, by);
  } catch {
    // storage blocked: the name lasts until the page reloads, then the app asks again
  }
  navButton.textContent = `${t("nav.reviewer")}: ${by}`;
}

// The reviewer dialog; resolves with the name entered, or "" when it was left empty or cancelled.
function askReviewer() {
  const input = el("input", { id: "reviewer", class: "mono", value: current, autocomplete: "off" });
  const dialog = el("dialog", { "aria-labelledby": "reviewer-title" },
    el("form", { method: "dialog" },
      el("h2", { id: "reviewer-title" }, t("reviewer.title")),
      el("p", { class: "small muted" }, t("reviewer.help")),
      field(t("reviewer.name"), input),
      el("div", { class: "actions" },
        el("button", { class: "btn primary", value: "ok" }, t("reviewer.save")),
        el("button", { class: "btn secondary", value: "cancel" }, t("reviewer.cancel")))));
  document.body.append(dialog);
  return new Promise(resolve => {
    dialog.addEventListener("close", () => {
      const by = dialog.returnValue === "ok" ? input.value.trim() : "";
      dialog.remove();
      if (by) setReviewer(by);
      resolve(by);
    });
    dialog.showModal();
  });
}

// The reviewer name for a review or correction: asked for once, then kept; no name stops the action.
export async function requireReviewer() {
  const by = current || await askReviewer();
  if (!by) throw fail("invalid", t("error.reviewer"));
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
  current = storedReviewer();
  navButton = el("button", { type: "button", class: "reviewer mono", title: t("nav.reviewer_change"),
    onclick: () => askReviewer() }, `${t("nav.reviewer")}: ${current || "—"}`);
  return el("nav", { class: "topnav", "aria-label": t("nav.label") },
    el("a", { href: "index.html", class: "brand" }, "ag:AutoGrade"), MAIN.map(link), menu,
    link(["evaluasi.html", "nav.evaluation"]), el("span", { class: "spacer" }), navButton,
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
      showError(main, e, { home: true });
    }
  };
  await refresh();
}
