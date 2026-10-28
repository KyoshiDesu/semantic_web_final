// Kelas: courses and assessments, students, question upload, and the LMS CSV import through a column mapping.
import { api } from "./api.js";
import { t } from "./i18n.js";
import { add, button, el, fail, field, fill, href, loading, panel, param, records, select, showError, start, table,
  tabs, ticked, toast } from "./ui.js";

const MAX_UPLOAD = 10 * 1024 * 1024;
const NONE = [["", "—"]];

function upload(name, files) {
  const fd = new FormData();
  for (const f of files) {
    if (f.size > MAX_UPLOAD) throw fail("too_large", t("kelas.too_large", { name: f.name }));
    fd.append(name, f);
  }
  return fd;
}

// The file input, its preview, then the mapping form once the columns are known; send(path, mapping, dryRun) posts
// the file again with the mapping (the import is stateless).
function csvStep(p, before, drawMapping) {
  const file = el("input", { type: "file", accept: ".csv,text/csv" });
  const mapping = el("div");
  const result = el("div", { "aria-live": "polite" });
  file.addEventListener("change", async () => {
    mapping.replaceChildren(loading());
    result.replaceChildren();
    try {
      const pv = await api.form("/imports/preview", upload("file", [file.files[0]]));
      mapping.replaceChildren(el("p", { class: "small muted" }, t("import.preview", { n: pv.count })), table(pv, { translate: false }));
      await drawMapping(mapping, pv, async (path, map, dryRun) => {
        const fd = upload("file", [file.files[0]]);
        fd.append("mapping", JSON.stringify(map));
        return api.form(path, fd, { dry_run: dryRun });
      }, result);
    } catch (e) {
      showError(mapping, e);
    }
  });
  p.replaceChildren(before, field(t("import.file"), file), mapping, result);
}

function answersTab(p, courseId, assessments, refresh) {
  const usable = assessments.filter(a => a.questions.length);
  if (!usable.length) {
    p.replaceChildren(el("p", { class: "muted" }, t("import.no_questions")));
    return;
  }
  const which = select(usable.map(a => [String(a.id), a.name]), String(usable[0].id));
  csvStep(p, field(t("import.assessment"), which), (box, pv, send, result) => {
    const cols = pv.columns.map(c => [c, c]);
    const questions = usable.find(a => String(a.id) === which.value).questions;
    const idCol = select(cols, pv.columns[0]);
    const names = pv.columns.map(c => el("label", {}, el("input", { type: "checkbox", value: c }), " ", c));
    const layout = select([["wide", t("import.wide")], ["long", t("import.long")]], "wide");
    const wide = Object.fromEntries(questions.map(q => [q, select([...NONE, ...cols], pv.columns.includes(q) ? q : "")]));
    const qCol = select(cols, pv.columns[0]);
    const aCol = select(cols, pv.columns[pv.columns.length - 1]);
    const values = el("datalist", { id: "question-values" });
    const long = Object.fromEntries(questions.map(q => [q, el("input", { value: q, list: "question-values" })]));
    const split = select([["test", t("import.split_test")], ["pilot", t("import.split_pilot")]], "test");
    const wideBox = el("div", {}, questions.map(q => field(t("import.answer_col", { q }), wide[q])));
    const longBox = el("div", { hidden: true }, el("div", { class: "row" }, field(t("import.question_col"), qCol),
      field(t("import.answers_col"), aCol)), values, questions.map(q => field(t("import.value_for", { q }), long[q])));
    const fillValues = () => values.replaceChildren(...[...new Set(pv.rows.map(r => r[pv.columns.indexOf(qCol.value)]))]
      .map(v => el("option", { value: v })));
    qCol.addEventListener("change", fillValues);
    fillValues();
    layout.addEventListener("change", () => {
      wideBox.hidden = layout.value !== "wide";
      longBox.hidden = layout.value === "wide";
    });
    const mapping = () => {
      const columns = {};
      for (const q of questions) {
        if (layout.value === "wide" && wide[q].value) columns[q] = { column: wide[q].value };
        if (layout.value === "long" && long[q].value.trim()) {
          columns[q] = { column: aCol.value, filter_column: qCol.value, filter_value: long[q].value.trim() };
        }
      }
      return { id_col: idCol.value, name_cols: ticked(names),
        columns, split: split.value };
    };
    const go = dryRun => async () => {
      const r = await send(`/courses/${courseId}/answers`, mapping(), dryRun);
      if (!dryRun) {
        toast(t("import.answers_done", { n: r.added }));
        await refresh();
        return;
      }
      fill(result, el("p", {}, t("import.check_result", { new: r.new, blank: r.blank, existing: r.existing.length })),
        r.existing.length ? el("details", {}, el("summary", {}, t("import.existing")), el("p", { class: "small" }, r.existing.join(", "))) : null,
        table(records(r.answers, ["answer_id", "external_id", "name", "text"])));
    };
    box.append(field(t("import.id_col"), idCol), el("fieldset", {}, el("legend", {}, t("import.name_cols")), el("div", { class: "row" }, names)),
      field(t("import.layout"), layout), wideBox, longBox, field(t("import.split"), split),
      el("div", { class: "actions" }, button(t("import.check"), go(true), { slot: result }),
        button(t("import.run"), go(false), { kind: "primary", slot: result })));
  });
}

function scoresTab(p, courseId, assessments) {
  const questions = assessments.flatMap(a => a.questions);
  if (!questions.length) {
    p.replaceChildren(el("p", { class: "muted" }, t("import.no_questions")));
    return;
  }
  const which = select(questions.map(q => [q, q]), questions[0]);
  csvStep(p, field(t("import.question"), which), async (box, pv, send, result) => {
    const q = await api.get(`/questions/${encodeURIComponent(which.value)}`);
    const cols = [...NONE, ...pv.columns.map(c => [c, c])];
    const idCol = select(pv.columns.map(c => [c, c]), pv.columns[0]);
    const rater = el("input", { value: "D1" });
    const criteria = [...q.rubric.criteria.map(c => c.id), "_total"];
    const picks = Object.fromEntries(criteria.map(c => [c, select(cols, "")]));
    const mapping = () => ({ id_col: idCol.value, question_id: which.value, rater_id: rater.value,
      columns: Object.fromEntries(criteria.filter(c => picks[c].value).map(c => [c, picks[c].value])) });
    const go = dryRun => async () => {
      const r = await send(`/courses/${courseId}/scores`, mapping(), dryRun);
      result.replaceChildren(table(r));
      if (!dryRun) toast(t("import.scores_done", { n: r.added }));
    };
    add(box, el("div", { class: "row" }, field(t("import.id_col"), idCol), field(t("import.rater"), rater)),
      criteria.map(c => field(c === "_total" ? t("import.total") : t("import.score_col", { criterion: c }), picks[c])),
      el("p", { class: "small muted" }, t("import.scores_help")),
      el("div", { class: "actions" }, button(t("import.check"), go(true), { slot: result }),
        button(t("import.run"), go(false), { kind: "primary", slot: result })));
  });
}

async function coursePanels(main, course, refresh) {
  const [assessments, students] = await Promise.all([api.get(`/courses/${course.id}/assessments`),
    api.get(`/courses/${course.id}/students`)]);
  const name = el("input");
  const target = select(assessments.map(a => [String(a.id), a.name]), String(assessments[0]?.id ?? ""));
  const files = el("input", { type: "file", multiple: true, accept: ".md,.yaml,.yml" });
  const importBox = el("div");
  add(main,
    panel(`${course.code} · ${course.name}`, el("h3", {}, t("kelas.assessments")),
      el("ul", {}, assessments.map(a => el("li", {}, el("a", { href: href("penilaian.html", { id: a.id }) }, a.name), ": ",
        a.questions.length ? a.questions.map((q, i) => [i ? ", " : "", el("a", { href: href("soal.html", { id: q }) }, q)])
          : el("span", { class: "muted" }, t("kelas.no_questions_yet"))))),
      el("div", { class: "row" }, field(t("kelas.assessment_name"), name), button(t("kelas.add_assessment"), async () => {
        await api.post(`/courses/${course.id}/assessments`, { name: name.value });
        await refresh();
      }, { kind: "primary" }))),
    assessments.length ? panel(t("kelas.upload_title"), el("p", { class: "small muted" }, t("kelas.upload_help")),
      el("div", { class: "row" }, field(t("kelas.to_assessment"), target), field(t("kelas.question_files"), files)),
      el("div", { class: "actions" }, button(t("kelas.upload"), async () => {
        if (!files.files.length) throw fail("invalid", t("kelas.choose_files"));
        const r = await api.form(`/assessments/${target.value}/questions/upload`, upload("files", files.files));
        toast(t("kelas.uploaded", { id: r.id }));
        await refresh();
      }, { kind: "primary" }))) : null,
    panel(t("import.title"), importBox),
    panel(t("kelas.students"), el("p", { class: "small muted" }, t("kelas.students_help")), table(students)));
  await tabs(importBox, [
    { id: "answers", label: t("import.tab_answers"), render: async p => answersTab(p, course.id, assessments, refresh) },
    { id: "scores", label: t("import.tab_scores"), render: async p => scoresTab(p, course.id, assessments) },
  ]);
}

start("kelas.html", "kelas.title", async (main, refresh) => {
  const courses = await api.get("/courses");
  const chosen = param("course");
  const code = el("input");
  const name = el("input");
  main.replaceChildren(el("h1", {}, t("kelas.title")),
    panel(t("kelas.courses"),
      el("ul", {}, courses.map(c => el("li", {}, el("a", { href: href("kelas.html", { course: c.id }),
        "aria-current": String(c.id) === chosen ? "page" : null }, `${c.code} · ${c.name}`)))),
      el("div", { class: "row" }, field(t("kelas.code"), code), field(t("kelas.name"), name),
        button(t("kelas.add_course"), async () => {
          const c = await api.post("/courses", { code: code.value, name: name.value });
          location.assign(href("kelas.html", { course: c.id }));
        }, { kind: "primary" }))));
  if (!chosen) {
    main.append(el("p", { class: "muted" }, t("kelas.pick")));
    return;
  }
  const course = courses.find(c => String(c.id) === chosen);
  if (!course) throw fail("not_found", `unknown course ${chosen}`);
  await coursePanels(main, course, refresh);
});
