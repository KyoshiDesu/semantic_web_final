// UI text in Indonesian (default) or English from web/i18n/<lang>.json; content (answers, questions) is never translated.
const KEY = "autograde.lang";
let dict = {};
let current = "id";

export async function init() {
  try {
    current = localStorage.getItem(KEY) === "en" ? "en" : "id";
  } catch {
    current = "id";
  }
  document.documentElement.lang = current;
  dict = await (await fetch(`/i18n/${current}.json`)).json();
  apply(document);
}

export const lang = () => current;

export function setLang(next) {
  try {
    localStorage.setItem(KEY, next);
  } catch {
    return;  // storage blocked: the app stays in Indonesian
  }
  location.reload();
}

export function t(key, vars = {}) {
  const found = key.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), dict);
  let text = found;
  if (typeof found !== "string") {
    if (!("fallback" in vars)) console.warn(`i18n missing: ${key}`);
    text = vars.fallback ?? key;
  }
  return String(text).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export function apply(root) {
  for (const n of root.querySelectorAll("[data-i18n]")) n.textContent = t(n.dataset.i18n);
  for (const n of root.querySelectorAll("[data-i18n-placeholder]")) n.placeholder = t(n.dataset.i18nPlaceholder);
  for (const n of root.querySelectorAll("[data-i18n-title]")) n.title = t(n.dataset.i18nTitle);
}
