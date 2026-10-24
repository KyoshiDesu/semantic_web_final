"""Data pages: courses, assessments, question upload, and LMS CSV import of answers and the lecturer's scores.

The pages only collect input; validation and writes live in autograde.importer and autograde.db.
"""
import sqlite3
from io import BytesIO

import pandas as pd
import streamlit as st

from autograde import db, gold, importer
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
