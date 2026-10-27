"""Data pages: courses, assessments, question upload, and LMS CSV import of answers and the lecturer's scores.

The pages only collect input; validation and writes live in autograde.importer and autograde.db.
"""
import sqlite3
from io import BytesIO

import pandas as pd
import streamlit as st

from autograde import authoring, db, extract, gold, importer, io, rdfviz
from autograde.io import TOTAL

NONE = "—"
ERRORS = (importer.ImportDataError, gold.GoldError, sqlite3.IntegrityError)


def pick(label, options, key):
    """Selectbox over db rows (dicts with id and a display name); returns the id or None."""
    names = {o["id"]: f"{o['code']} · {o['name']}" if "code" in o else o["name"] for o in options}
    return st.selectbox(label, list(names), format_func=names.get, key=key) if names else None


def upload_table(label, key):
    f = st.file_uploader(label, type="csv", key=key)
    if f is None:
        return None
    try:  # sep=None sniffs "," or ";" (spreadsheets in Indonesian locale save with ";"); utf-8-sig strips a BOM
        df = pd.read_csv(BytesIO(f.getvalue()), dtype=str, keep_default_na=False, encoding="utf-8-sig",
                         sep=None, engine="python")
    except ValueError as e:
        st.error(f"CSV tidak bisa dibaca: {e}")
        return None
    st.caption(f"{len(df)} baris, {len(df.columns)} kolom")
    return df


def page_courses():
    st.header("Mata kuliah")
    with st.form("add_course", clear_on_submit=True):
        c = st.columns([1, 3])
        code, name = c[0].text_input("Kode"), c[1].text_input("Nama mata kuliah")
        if st.form_submit_button("Tambah mata kuliah"):
            try:
                if not code.strip() or not name.strip():
                    raise importer.ImportDataError("kode dan nama wajib diisi")
                st.session_state["courses_course"] = db.add_course(code.strip(), name.strip())  # select the new course
                st.success(f"Mata kuliah {code.strip()} ditambahkan.")
            except ERRORS as e:
                st.error(f"Gagal: {e}")
    course = pick("Mata kuliah", db.courses(), "courses_course")
    if course is None:
        return
    with st.form("add_assessment", clear_on_submit=True):
        name = st.text_input("Nama penilaian (mis. UTS, Kuis 1)")
        if st.form_submit_button("Tambah penilaian"):
            try:
                if not name.strip():
                    raise importer.ImportDataError("nama wajib diisi")
                db.add_assessment(course, name.strip())
                st.success(f"Penilaian {name.strip()} ditambahkan.")
            except ERRORS as e:
                st.error(f"Gagal: {e}")
    assessments = db.assessments(course)
    counts = db.answers(include_synthetic=True).question_id.value_counts()
    rows = []
    for a in assessments:
        rows += [{"Penilaian": a["name"], "Soal": q, "Pertanyaan": db.question(q)["prompt"][:100],
                  "Jawaban": int(counts.get(q, 0))} for q in db.questions(a["id"])] \
            or [{"Penilaian": a["name"], "Soal": NONE, "Pertanyaan": "", "Jawaban": 0}]
    st.subheader("Penilaian dan soal")
    st.dataframe(pd.DataFrame(rows, columns=["Penilaian", "Soal", "Pertanyaan", "Jawaban"]), hide_index=True,
                 width="stretch")

    st.subheader("Unggah soal")
    st.caption("Empat berkas dengan format `data/questions/Q1`: `question.md`, `reference_answer.md`, `rubric.yaml`, "
               "`gold.yaml`. ID soal diambil dari `question_id` di `rubric.yaml` dan harus unik.")
    target = pick("Ke penilaian", assessments, "upload_assessment")
    files = st.file_uploader("Berkas soal", type=["md", "yaml"], accept_multiple_files=True, key="question_files")
    if target is not None and files and st.button("Tambah soal", type="primary"):
        try:
            qid = importer.add_question(target, {f.name: f.getvalue().decode("utf-8") for f in files})
            st.cache_data.clear()
            st.success(f"Soal {qid} ditambahkan; graf acuan `urn:ag:gold:{qid}` dibuat.")
        except (*ERRORS, UnicodeDecodeError) as e:
            st.error(f"Gagal: {e}")

    st.subheader("Mahasiswa")
    st.caption("Dibuat otomatis saat jawaban diimpor.")
    st.dataframe(db.students(course), hide_index=True, width="stretch")


def page_import():
    st.header("Impor dari LMS")
    course = pick("Mata kuliah", db.courses(), "import_course")
    assessment = course and pick("Penilaian", db.assessments(course), "import_assessment")
    qids = db.questions(assessment) if assessment else []
    if not qids:
        st.info("Pilih mata kuliah dan penilaian yang sudah punya soal (halaman Mata Kuliah).")
        return
    answers_tab, scores_tab = st.tabs(["Jawaban", "Nilai dosen"])
    with answers_tab:
        df = upload_table("CSV jawaban dari LMS", "answers_csv")
        if df is not None:
            import_answers(course, qids, df)
    with scores_tab:
        df = upload_table("CSV nilai dosen", "scores_csv")
        if df is not None:
            import_scores(qids, df)


def import_answers(course, qids, df):
    cols = list(df.columns)
    c = st.columns(2)
    id_col = c[0].selectbox("Kolom ID mahasiswa", cols, key="ans_id")
    name_cols = c[1].multiselect("Kolom nama (boleh lebih dari satu)", cols, key="ans_name")
    layout = st.radio("Bentuk tabel", ["wide", "long"], horizontal=True, key="ans_layout",
                      format_func={"wide": "Satu baris per mahasiswa, satu kolom per soal",
                                   "long": "Satu baris per jawaban"}.get)
    columns = {}
    if layout == "wide":
        for q in qids:
            col = st.selectbox(f"Kolom jawaban {q}", [NONE, *cols], key=f"ans_col_{q}")
            if col != NONE:
                columns[q] = (col, None)
    else:
        c = st.columns(2)
        q_col = c[0].selectbox("Kolom soal", cols, key="ans_qcol")
        a_col = c[1].selectbox("Kolom jawaban", cols, key="ans_acol")
        values = sorted(set(df[q_col].str.strip()))
        for q in qids:
            v = st.selectbox(f"Nilai di kolom soal untuk {q}", [NONE, *values], key=f"ans_val_{q}",
                             index=values.index(q) + 1 if q in values else 0)
            if v != NONE:
                columns[q] = (a_col, (q_col, v))
    split = st.radio("Split", ["test", "pilot"], horizontal=True, key="ans_split",
                     help="test: jawaban yang dinilai dan dievaluasi. pilot: hanya untuk kalibrasi parameter.")
    if not columns:
        st.info("Pilih minimal satu kolom jawaban.")
        return
    try:
        rows, report = importer.answers_from_table(df, id_col, name_cols, columns, split)
    except importer.ImportDataError as e:
        st.error(str(e))
        return
    st.write(f"**{len(rows)}** jawaban baru · {report['blank']} kosong dilewati · "
             f"{len(report['existing'])} sudah ada dilewati")
    if report["existing"]:
        with st.expander("Sudah ada (tidak diganti)"):
            st.write(", ".join(report["existing"]))
    if rows:
        st.dataframe(pd.DataFrame(rows)[["answer_id", "external_id", "name", "text"]], hide_index=True,
                     width="stretch")
        if st.button("Impor jawaban", type="primary", key="ans_import"):
            db.import_course_answers(course, rows)
            st.cache_data.clear()
            st.success(f"{len(rows)} jawaban diimpor. Nilai di halaman Nilai Jawaban (mode LLM).")


def import_scores(qids, df):
    cols = list(df.columns)
    c = st.columns(3)
    qid = c[0].selectbox("Soal", qids, key="sc_q")
    id_col = c[1].selectbox("Kolom ID mahasiswa", cols, key="sc_id")
    rater = c[2].text_input("ID penilai", "D1", key="sc_rater")
    columns = {}
    for crit in [c["id"] for c in db.question(qid)["rubric"]["criteria"]] + [TOTAL]:
        label = "Kolom nilai total (holistik)" if crit == TOTAL else f"Kolom nilai {crit}"
        col = st.selectbox(label, [NONE, *cols], key=f"sc_{qid}_{crit}")
        if col != NONE:
            columns[crit] = col
    st.caption("Nilai 0–100 (koma desimal boleh). Nilai lama dengan penilai dan kriteria yang sama diganti.")
    if not columns:
        st.info("Pilih minimal satu kolom nilai.")
        return
    try:
        scores = importer.scores_from_table(df, id_col, qid, columns, rater)
    except importer.ImportDataError as e:
        st.error(str(e))
        return
    st.dataframe(scores, hide_index=True, width="stretch")
    if len(scores) and st.button("Impor nilai", type="primary", key="sc_import"):
        db.add_human_scores(scores, replace=True)
        st.cache_data.clear()
        st.success(f"{len(scores)} nilai diimpor.")


# ---------- question editor ----------

def _records(df):
    """Comparable rows: lists as tuples, NaN/None as None (data_editor round trips may change both)."""
    norm = lambda v: tuple(v) if pd.api.types.is_list_like(v) else (None if pd.isna(v) else v)  # noqa: E731
    return [tuple(norm(v) for v in row) for row in df.itertuples(index=False)]


def _changed(a, b):
    return any(a[k] != b[k] for k in ("prompt", "reference_answer", "language", "validated_by")) or \
        any(_records(a[k]) != _records(b[k]) for k in ("criteria", "concepts", "triples"))


def edit_table(name, column_config):
    """A dynamic data_editor over the draft table. Its widget identity includes the data and the column options, so
    every edit is written back to the draft and the editor is re-keyed (ed_ver) instead of keeping edits in widget
    state, which would be lost when a dropdown's options change."""
    d = st.session_state.ed_draft
    edited = st.data_editor(d[name], key=f"ed_{name}_{st.session_state.ed_ver}", num_rows="dynamic",
                            column_config=column_config, hide_index=True, width="stretch")
    if _records(edited) != _records(d[name]):
        d[name] = edited.reset_index(drop=True)
        st.session_state.ed_ver += 1
        st.rerun()


def _load_draft(target):
    """target: ("edit", qid) or ("new", copy_of_qid or None)."""
    base = db.question(target[1]) if target[1] else None
    draft = authoring.to_tables(base) if base else authoring.empty_tables()
    if target[0] == "new":
        draft["validated_by"] = ""  # a copy is not validated
    st.session_state.update(ed_target=target, ed_base=base, ed_draft=draft, ed_saved=authoring.to_tables(base)
                            if target[0] == "edit" else None, ed_ver=st.session_state.get("ed_ver", 0) + 1)


def page_editor():
    st.header("Editor soal")
    saved = st.session_state.pop("ed_after_save", None)
    if saved:
        st.session_state.update(ed_mode="Ubah soal", ed_qid=saved[0], ed_target=None)
        st.success(saved[1])
    mode = st.radio("Mode", ["Ubah soal", "Soal baru"], horizontal=True, key="ed_mode", label_visibility="collapsed")
    if mode == "Ubah soal":
        qid = st.selectbox("Soal", db.questions(), key="ed_qid")
        assessment, target = None, ("edit", qid)
        n = db.result_count(qid)
        if n:
            st.warning(f"{n} hasil penilaian memakai kunci ini. Setelah disimpan, hasil itu usang sampai dinilai ulang.")
    else:
        course = pick("Mata kuliah", db.courses(), "ed_course")
        assessment = course and pick("Penilaian", db.assessments(course), "ed_assessment")
        c = st.columns(2)
        qid = c[0].text_input("ID soal baru", key="ed_new_id").strip()
        copy = c[1].selectbox("Mulai dari salinan soal", [NONE, *db.questions()], key="ed_copy")
        target = ("new", None if copy == NONE else copy)
        if not assessment or not qid:
            st.info("Pilih penilaian dan isi ID soal baru.")
            return
        if qid in db.questions():
            st.error(f"Soal {qid} sudah ada; pilih ID lain atau ubah soal itu.")
            return
    if st.session_state.get("ed_target") != target:
        _load_draft(target)
    d, v = st.session_state.ed_draft, st.session_state.ed_ver

    c = st.columns(2)
    d["prompt"] = c[0].text_area("Soal", d["prompt"], height=120, key=f"ed_prompt_{v}")
    d["reference_answer"] = c[1].text_area("Jawaban acuan", d["reference_answer"], height=120, key=f"ed_ref_{v}")
    d["language"] = st.radio("Bahasa", ["id", "en"], index=["id", "en"].index(d["language"]), horizontal=True,
                             key=f"ed_lang_{v}", format_func={"id": "Indonesia", "en": "Inggris"}.get)
    col = st.column_config
    st.subheader("Kriteria rubrik")
    edit_table("criteria", {"id": col.TextColumn("ID", required=True), "description": col.TextColumn("Deskripsi",
                                                                                                    width="large")})
    st.subheader("Konsep")
    st.caption("Alias menormalkan kata mahasiswa ke konsep. *Lebih umum* (skos:broader): menyebut konsep yang lebih "
               "umum memberi kredit parsial.")
    concepts = sorted(authoring._str(c) for c in d["concepts"].concept if authoring._str(c))
    edit_table("concepts", {"concept": col.TextColumn("Konsep", required=True),
                            "aliases": col.MultiselectColumn("Alias", options=[], accept_new_options=True),
                            "broader": col.MultiselectColumn("Lebih umum", options=concepts)})
    st.subheader("Triple acuan")
    st.caption("Subjek boleh lebih dari satu (semua diterima). ID kosong diberi nomor R<n> saat disimpan.")
    offered = [p["id"] for p in extract.for_language(io.load_predicates(), d["language"])["predicates"]
               if p["id"] != "other"]
    in_use = sorted({authoring._str(p) for p in d["triples"].p} - set(offered) - {""})
    criteria = [authoring._str(c) for c in d["criteria"].id if authoring._str(c)]
    edit_table("triples", {
        "id": col.TextColumn("ID"),
        "s": col.MultiselectColumn("Subjek", options=concepts),
        "p": col.SelectboxColumn("Predikat", options=offered + in_use,
                                 format_func=lambda p: f"{p} (tidak dikenal)" if p in in_use else p),
        "o": col.SelectboxColumn("Objek", options=concepts),
        "criterion": col.SelectboxColumn("Kriteria", options=criteria),
        "weight": col.NumberColumn("Bobot", min_value=0.1, step=0.5, default=1.0)})
    d["validated_by"] = st.text_input("Divalidasi oleh (kosongkan bila belum)", d["validated_by"], key=f"ed_val_{v}")

    st.subheader("Pratinjau graf acuan")
    try:
        rubric, gold_raw = authoring.from_tables(qid, d, st.session_state.ed_base)
        refs = importer.validate_question(d["prompt"].strip(), d["reference_answer"].strip(), rubric, gold_raw,
                                          importer.checked_relations())
    except ValueError as e:
        st.error(f"Belum valid: {e}")
        refs = None
    if refs is not None:
        files = authoring.question_files(d["prompt"], d["reference_answer"], rubric, gold_raw)
        st.caption(f"Named graph `urn:ag:gold:{qid}` setelah disimpan.")
        tabs = st.tabs(["Graf konsep", "RDF terreifikasi", "Turtle", "YAML"])
        tabs[0].graphviz_chart(rdfviz.gold_concept_dot(refs, gold_raw["concepts"]))
        tabs[1].graphviz_chart(rdfviz.gold_reified_dot(qid, refs))
        tabs[2].code(gold.to_graph(qid, refs, rubric, gold_raw["concepts"]).serialize(format="turtle"),
                     language="turtle")
        tabs[3].code(files["rubric.yaml"] + "\n---\n" + files["gold.yaml"], language="yaml")

    saved_draft = st.session_state.ed_saved
    if saved_draft is None or _changed(d, saved_draft):
        st.caption("● Belum disimpan")
    c = st.columns([1, 1, 4])
    if c[0].button("Simpan", type="primary", disabled=refs is None, key="ed_save"):
        try:
            importer.save_question(qid, d["prompt"].strip(), d["reference_answer"].strip(), rubric, gold_raw,
                                   assessment)
        except ValueError as e:
            st.error(f"Gagal menyimpan: {e}")
        else:
            st.cache_data.clear()
            st.cache_resource.clear()  # pipeline.Context per question holds the old key
            st.session_state.ed_after_save = (qid, f"Soal {qid} disimpan; `urn:ag:gold:{qid}` diperbarui.")
            st.rerun()
    c[1].download_button("Unduh berkas (.zip)", authoring.question_zip(qid, files) if refs is not None else b"",
                         file_name=f"{qid}.zip", mime="application/zip", disabled=refs is None, key="ed_zip")
