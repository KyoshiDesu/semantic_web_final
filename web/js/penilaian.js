// Penilaian: an assessment's status, the background grading job (followed after a reload), bulk review, exports.
import { api, url } from "./api.js";
import { t } from "./i18n.js";
import { button, dl, el, errorPanel, fail, href, iri, panel, param, report, requireReviewer, score, start,
  statusChip, table, toast } from "./ui.js";

const STATUSES = ["belum dinilai", "usang", "dinilai", "ditinjau"];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function progressView(job, cancel) {
  return el("div", {},
    el("progress", { max: job.total, value: job.done }),
    el("p", {}, t("penilaian.progress", { done: job.done, total: job.total }), job.current ? ` · ${job.current}` : ""),
    job.status === "running" ? cancel : el("p", {}, t(`penilaian.job_${job.status}`)),
    job.failures.length ? el("details", { open: true }, el("summary", {}, t("penilaian.failures", { n: job.failures.length })),
      el("ul", {}, job.failures.map(f => el("li", {}, `${f.answer_id}: ${f.error}`)))) : null);
}

async function follow(job, area, controls, refresh) {
  controls.hidden = true;  // one job at a time: no start buttons while this one runs
  const cancel = button(t("penilaian.cancel"), async () => { job = await api.post(`/jobs/${job.id}/cancel`); },
    { kind: "danger", slot: area });
  while (job.status === "running") {
    area.replaceChildren(progressView(job, cancel));
    await sleep(1000);
    if (!area.isConnected) return;  // the page was rendered again meanwhile
    job = await api.get(`/jobs/${job.id}`);
  }
  await refresh();
}

function exportsPanel(id, st) {
  const locked = !st.ready;
  const missing = Object.entries(st.counts).filter(([s]) => s !== "ditinjau")
    .map(([s, n]) => `${n} ${t(`status.${s}`)}`).join(", ");
  const final = kind => (locked ? el("button", { type: "button", class: "btn secondary", disabled: true }, t(`penilaian.final_${kind}`))
    : dl(url(`/assessments/${id}/exports/${kind}.csv`), t(`penilaian.final_${kind}`)));
  const draft = kind => dl(url(`/assessments/${id}/exports/${kind}.csv`, { draft: true }), t(`penilaian.draft_${kind}`));
  return panel(t("penilaian.exports"),
    el("div", { class: "actions" }, final("grades"), final("feedback"),
      locked ? el("span", { class: "reason" }, t("penilaian.locked", { missing })) : null),
    el("div", { class: "actions" }, draft("grades"), draft("feedback")),
    el("p", { class: "small muted" }, t("penilaian.mean_note")));
}

start("penilaian.html", "penilaian.title", async (main, refresh) => {
  const id = param("id");
  if (!id) throw fail("not_found", t("penilaian.missing"));
  const st = await api.get(`/assessments/${encodeURIComponent(id)}/status`);
  const col = name => st.columns.indexOf(name);
  const head = el("section", { class: "panel" },
    el("h1", {}, `${st.course.code} · ${st.assessment.name}`),
    el("p", { class: "muted" }, "run ", iri(st.run_id), " · ",
      el("a", { href: href("kelas.html", { course: st.course.id }) }, t("penilaian.course"))),
    el("div", { class: "chips counts" }, STATUSES.filter(s => st.counts[s])
      .map(s => el("span", { class: `chip st-${s.replace(" ", "-")}` }, `${st.counts[s]} ${t(`status.${s}`)}`))),
    st.synthetic ? el("p", { class: "small muted" }, t("penilaian.synthetic")) : null);
  if (!st.rows.length) {
    main.replaceChildren(head, el("p", { class: "muted" }, t("penilaian.no_answers")));
    return;
  }
  const area = el("div", { id: "job-area", "aria-live": "polite" });
  const llm = el("input", { type: "checkbox" });
  const startJob = (which, status) => button(t(`penilaian.grade_${which}`, { n: st.counts[status] || 0 }), async () => {
    const job = await api.post(`/assessments/${id}/grading`, { which, llm_feedback: llm.checked });
    follow(job, area, controls, refresh).catch(e => { area.append(errorPanel(e)); report(e); });
  }, { kind: which === "new" ? "primary" : "secondary", disabled: !st.counts[status], slot: area });
  const controls = el("div", {}, el("label", {}, llm, " ", t("penilaian.llm_feedback")),
    el("div", { class: "actions" }, startJob("new", "belum dinilai"), startJob("stale", "usang")));
  const job = st.job;
  if (job && job.status !== "running") {
    area.append(el("p", { class: "small muted" }, t("penilaian.last_job", { id: job.id })), progressView(job, null));
  }
  const approve = button(t("penilaian.approve", { n: st.approvable.length }), async () => {
    const res = await api.post(`/assessments/${id}/review/bulk`, { by: requireReviewer() });
    toast(t("penilaian.approved", { n: res.reviewed.length }));
    await refresh();
  }, { kind: "primary", disabled: !st.approvable.length });
  main.replaceChildren(head,
    panel(t("penilaian.grading"), el("p", { class: "small muted" }, t("penilaian.grading_help")), controls, area),
    panel(t("penilaian.table"), table(st, { cell: (c, v, row) => {
      if (c === "status") return statusChip(v);
      if (c === "answer_id") {
        return row[col("status")] === "belum dinilai" ? v : el("a", { href: href("jawaban.html", { run: st.run_id, answer: v }) }, v);
      }
      if (c === "score" || c === "final") return score(v);
      if (c === "flagged") return v ? `⚑ ${v}` : "—";
      return undefined;
    } })),
    panel(t("penilaian.review"), el("p", { class: "small muted" }, t("penilaian.review_help")), el("div", { class: "actions" }, approve)),
    exportsPanel(id, st));
  if (job && job.status === "running") {
    follow(job, area, controls, refresh).catch(e => { area.append(errorPanel(e)); report(e); });
  }
});
