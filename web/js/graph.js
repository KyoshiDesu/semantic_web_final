// Graph drawing: DOT through Graphviz (WebAssembly, loaded on first use) and JSON graphs through vis-network.
import { t } from "./i18n.js";
import { el, fill } from "./ui.js";

let viz = null;
let vis = null;

export async function dot(container, text) {
  viz ??= import("/vendor/viz.js").then(m => m.instance());
  const svg = (await viz).renderSVGElement(text);
  svg.removeAttribute("width");  // scale with the panel; the viewBox keeps the proportions
  svg.removeAttribute("height");
  container.replaceChildren(el("div", { class: "graph-panel dot-panel" }, svg));
  return svg;
}

function loadVis() {
  vis ??= new Promise((resolve, reject) => {
    const s = el("script", { src: "/vendor/vis-network.min.js" });
    s.onload = () => resolve(window.vis);
    s.onerror = reject;
    document.head.append(s);
  });
  return vis;
}

function details(target, graph, id) {
  const d = graph.details?.[id];
  if (!d) {
    target.replaceChildren(el("h3", {}, id));
    return;
  }
  fill(target, el("div", { class: "muted small" }, d.kind), el("h3", {}, d.title),
    el("table", {}, el("tbody", {}, d.fields.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))))),
    d.sections.map(s => [el("h4", {}, s.heading), el("ul", {}, s.items.map(item => el("li", {}, item)))]));
}

function legendButton(label, swatch, shown, onToggle) {
  const b = el("button", { type: "button", "aria-pressed": String(shown) }, swatch, label);
  b.addEventListener("click", () => {
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(on));
    onToggle(on);
  });
  return b;
}

export async function network(container, graph, nodeTypes, edgeTypes, { height = 600 } = {}) {
  const V = await loadVis();
  const hiddenKinds = new Set(Object.entries(nodeTypes).filter(([, v]) => !v[3]).map(([k]) => k));
  const hiddenEdges = new Set(Object.entries(edgeTypes).filter(([, v]) => !v[4]).map(([k]) => k));
  const nodes = new V.DataSet(graph.nodes.map(n => {
    const [, color, shape] = nodeTypes[n.kind];
    const box = shape === "box" || shape === "ellipse";
    return { id: n.id, label: n.label, title: n.title, kind: n.kind, shape,
      color: { background: color, border: color, highlight: { background: color, border: "#16202e" } },
      font: box ? { color: "#fff", size: 13 } : { color: "#16202e", size: 13 },
      size: n.kind === "answer" ? 22 : n.kind === "student" ? 12 : 14, hidden: hiddenKinds.has(n.kind) };
  }));
  const edges = new V.DataSet(graph.edges.map((e, i) => {
    const [, color, dashed, width] = edgeTypes[e.kind];
    return { id: `e${i}`, from: e.from, to: e.to, kind: e.kind, label: e.label, fullLabel: e.label, title: e.title,
      arrows: e.kind === "ontology" ? "" : "to", dashes: dashed, width,
      color: { color, highlight: "#16202e", opacity: e.kind === "asserted" ? 0.7 : 1 },
      font: { size: 9, color: "#5b6472", strokeWidth: 2, align: "top" }, hidden: hiddenEdges.has(e.kind) };
  }));
  const canvas = el("div", { class: "net", style: { height: `${height}px` } });
  const side = el("aside", { class: "details" }, el("p", { class: "muted" }, t("graph.hint")));
  const legend = el("div", { class: "legend" },
    Object.entries(nodeTypes).map(([k, v]) => legendButton(t(`node.${k}`, { fallback: v[0] }),
      el("span", { class: "swatch", style: { background: v[1] } }), !hiddenKinds.has(k),
      on => nodes.update(nodes.get({ filter: n => n.kind === k }).map(n => ({ id: n.id, hidden: !on }))))),
    Object.entries(edgeTypes).map(([k, v]) => legendButton(t(`edge.${k}`, { fallback: v[0] }),
      el("span", { class: v[2] ? "swatch line dash" : "swatch line", style: { borderTopColor: v[1] } }),
      !hiddenEdges.has(k),
      on => edges.update(edges.get({ filter: x => x.kind === k }).map(x => ({ id: x.id, hidden: !on }))))));
  const search = el("input", { type: "search", placeholder: t("graph.search"), "aria-label": t("graph.search") });
  const fit = el("button", { type: "button", class: "btn secondary" }, t("graph.fit"));
  const freeze = el("button", { type: "button", class: "btn secondary" }, t("graph.freeze"));
  const labels = el("input", { type: "checkbox", checked: true });
  fill(container, legend,
    el("div", { class: "toolbar" }, search, fit, freeze, el("label", {}, labels, " ", t("graph.labels")),
      el("span", { class: "muted small" }, t("graph.counts", { nodes: graph.nodes.length, edges: graph.edges.length }))),
    graph.truncated ? el("p", { class: "muted" }, t("graph.truncated", { n: graph.edges.length })) : null,
    el("div", { class: "graph-body" }, canvas, side));
  const net = new V.Network(canvas, { nodes, edges }, {
    physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -60, springLength: 110 },
      stabilization: { iterations: 250 } },
    interaction: { hover: true, tooltipDelay: 120, navigationButtons: false },
    edges: { smooth: { type: "continuous" } },
  });
  const show = id => details(side, graph, id);
  net.on("click", e => { if (e.nodes.length) show(e.nodes[0]); });
  fit.onclick = () => net.fit({ animation: true });
  let frozen = false;
  freeze.onclick = () => {
    frozen = !frozen;
    net.setOptions({ physics: { enabled: !frozen } });
    freeze.textContent = t(frozen ? "graph.unfreeze" : "graph.freeze");
  };
  labels.onchange = () => edges.update(edges.get().map(x => ({ id: x.id, label: labels.checked ? x.fullLabel : " " })));
  search.oninput = () => {
    const q = search.value.trim().toLowerCase();
    if (q.length < 2) return;
    const hit = nodes.get({ filter: n => !n.hidden && (n.label.toLowerCase().includes(q) || (n.title || "").toLowerCase().includes(q)) })[0];
    if (hit) {
      net.selectNodes([hit.id]);
      net.focus(hit.id, { scale: 1.2, animation: true });
      show(hit.id);
    }
  };
  canvas.network = net;  // for tests and the browser console
  canvas.showDetails = show;
  return net;
}
