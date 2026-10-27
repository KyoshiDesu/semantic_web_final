// Beranda: a hero that names each Semantic Web piece and links to where it is visible.
import { t } from "./i18n.js";
import { el, start } from "./ui.js";

const PIECES = [["piece_rdf", "graf.html", "ns-key"], ["piece_owl", "ontologi.html", "ns-ag"],
  ["piece_swrl", "ontologi.html#rules", "ns-swrl"], ["piece_skos", "soal.html", "ns-skos"],
  ["piece_prov", "graf.html", "ns-prov"], ["piece_sparql", "sparql.html", "ns-other"]];

export function hero() {
  return el("section", { class: "panel hero" },
    el("div", { class: "prefixes" }, t("home.prefixes")),
    el("h1", {}, t("home.title")),
    el("p", { class: "lead" }, t("home.lead")),
    el("nav", { class: "chips", "aria-label": t("home.pieces") },
      PIECES.map(([key, link, cls]) => el("a", { href: link, class: cls }, t(`home.${key}`)))));
}

start("index.html", "nav.home", async main => main.replaceChildren(hero()));
