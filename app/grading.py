"""Penilaian page: grade a whole assessment, review it (bulk and per answer, with ledger corrections), export.

Flow: imported -> graded -> reviewed -> exported. The final export stays locked until every answer is reviewed.
"""
import html
from datetime import date

import pandas as pd
import streamlit as st

from autograde import db, gold, grades, importer, kg, pipeline
from autograde.feedback import display_score, triple_label
from manage import pick

STATUSES = ["MATCHED", "PARTIAL", "MISSING", "CONTRADICTED"]


def flash(msg, kind="success"):
    """Show a message after the st.rerun that refreshes the status table."""
    st.session_state.setdefault("gr_flash", []).append((kind, msg))


def page_grading():
    st.header("Penilaian kelas")
    for kind, msg in st.session_state.pop("gr_flash", []):
        getattr(st, kind)(msg)
    course = pick("Mata kuliah", db.courses(), "gr_course")
    assessment = course and pick("Penilaian", db.assessments(course), "gr_assessment")
    if not assessment:
        st.info("Pilih mata kuliah dan penilaian (halaman Mata Kuliah).")
        return
    run_id = pipeline.assessment_run(assessment)
    table = grades.status_table(assessment, run_id)
    if table.empty:
        st.info("Belum ada jawaban untuk penilaian ini (halaman Impor Jawaban).")
        return
    n = table.status.value_counts()
    c = st.columns(4)
    c[0].metric("Jawaban", len(table))
    c[1].metric("Sudah dinilai", int(n.get("dinilai", 0) + n.get("ditinjau", 0)))
    c[2].metric("Usang", int(n.get("usang", 0)))
    c[3].metric("Ditinjau", int(n.get("ditinjau", 0)))
    if (table.source == "synthetic").any():
        st.caption("Berisi jawaban sintetis (data demo), bukan jawaban mahasiswa nyata.")
    st.dataframe(table.drop(columns=["source"]).rename(columns={
        "answer_id": "Jawaban", "question_id": "Soal", "external_id": "Mahasiswa", "name": "Nama", "status": "Status",
        "score": "Skor sistem", "final": "Skor final", "flagged": "⚑", "contradictions": "Kontradiksi",
        "reviewed_by": "Peninjau"}), hide_index=True, width="stretch")
    st.caption(f"Run `{run_id}`: graf RDF tiap jawaban ada di halaman Penjelajah Graf dan Graf Pengetahuan.")
    tabs = st.tabs(["Nilai", "Tinjau", "Ekspor"])
    with tabs[0]:
        grade_tab(assessment, run_id, table)
    with tabs[1]:
        review_tab(assessment, run_id, table)
    with tabs[2]:
        export_tab(course, assessment, table, run_id)


def grade_tab(assessment, run_id, table):
    todo = table[table.status == "belum dinilai"].answer_id.tolist()
    stale = table[table.status == "usang"].answer_id.tolist()
    answers = db.assessment_answers(assessment).set_index("answer_id")
    use_llm = st.checkbox("Umpan balik dari LLM (butuh API key)", key="gr_llm")
    if not answers.loc[todo + stale].annotated.all():
        st.caption("Jawaban tanpa anotasi triple diekstraksi dengan LLM (butuh `ANTHROPIC_API_KEY`).")
    st.caption("Penilaian berjalan di tab ini; jangan tutup tab. Bila terhenti, klik lagi untuk melanjutkan.")
    c = st.columns(2)
    new = c[0].button(f"Nilai {len(todo)} jawaban yang belum dinilai", disabled=not todo, type="primary",
                      key="gr_new")
    again = c[1].button(f"Nilai ulang {len(stale)} jawaban usang", disabled=not stale, key="gr_stale")
    ids = todo if new else stale if again else []
    if not ids:
        return
    bar, contexts, failures = st.progress(0.0), {}, []
    for i, a in enumerate(answers.loc[ids].reset_index().itertuples()):
        bar.progress(i / len(ids), text=f"{a.answer_id} ({i + 1}/{len(ids)})")
        try:
            pipeline.grade_assessment_answer(run_id, a, contexts, use_llm)
        except Exception as e:  # one answer's failure (no API key, parity) must not stop the class
            failures.append(f"{a.answer_id}: {e}")
    db.finish_run(run_id)
    flash(f"{len(ids) - len(failures)} jawaban dinilai.")
    if failures:
        flash("Gagal (coba lagi nanti):\n\n" + "\n\n".join(failures), "error")
    st.rerun()


def review_tab(assessment, run_id, table):
    by = st.text_input("Nama peninjau", key="gr_by").strip()
    ok_ids = grades.bulk_approvable(table)
    if st.button(f"Setujui {len(ok_ids)} jawaban tanpa ⚑ dan tanpa kontradiksi", disabled=not ok_ids, key="gr_bulk"):
        if not by:
            st.error("Isi nama peninjau.")
        else:
            db.mark_reviewed(run_id, ok_ids, by)
            flash(f"{len(ok_ids)} jawaban ditandai ditinjau.")
            st.rerun()
    pending = table[table.status == "dinilai"].sort_values(["flagged", "contradictions"], ascending=False)
    if pending.empty:
        st.info("Tidak ada jawaban yang menunggu tinjauan.")
        return
    rows = pending.set_index("answer_id")
    aid = st.selectbox("Jawaban untuk ditinjau", rows.index, key="gr_answer", format_func=lambda a: (
        f"{a} · {rows.name[a] or rows.external_id[a]} · {display_score(rows.final[a])}"
        + (" · ⚑" if rows.flagged[a] else "") + (" · kontradiksi" if rows.contradictions[a] else "")))
    r, row = db.result(run_id, aid), rows.loc[aid]
    st.markdown("> " + html.escape(db.assessment_answers(assessment).set_index("answer_id").text[aid])
                .replace("\n", "<br>"), unsafe_allow_html=True)
    final = r["score_corrected"] or r["score"]
    c = st.columns(3)
    c[0].metric("Skor sistem", display_score(r["score"]["score"]))
    c[1].metric("Skor final", display_score(final["score"]), "terkoreksi" if r["score_corrected"] else None)
    ok = final["sparql_score"] is not None and abs(final["score"] - final["sparql_score"]) < 1e-9
    c[2].metric("SPARQL dari triple store", display_score(final["sparql_score"]), "✓ sama" if ok else "✗ berbeda",
                delta_color="normal" if ok else "inverse")

    refs = {ref.id: ref for ref in gold.load(row.question_id)[2]}
    sentences = dict(r["sentences"])
    ledger = r["ledger_corrected"] or r["ledger"]
    df = pd.DataFrame([{
        "ref": e["reference_id"],
        "triple acuan": triple_label(refs[e["reference_id"]]) if e["reference_id"] in refs else "(tidak ada di kunci)",
        "kriteria": e["criterion"], "w": e["weight"], "⚑": "⚑" if e["needs_review"] else "",
        "σ": e["sigma"], "bukti": " ".join(sentences.get(s, "") for s in e["sentence_ids"]),
        "koreksi": f"{e['override']['by']}: {e['override']['reason']}" if e.get("override") else "",
        "status": e["status"], "alasan": ""} for e in ledger])
    st.caption("Ubah **status** bila sistem keliru dan isi **alasan**; skor dihitung ulang (Pers. 6) dan dicek "
               "dengan SPARQL.")
    edited = st.data_editor(df, key=f"gr_ledger_{aid}_{r['graded']}_{len(db.overrides(aid))}", hide_index=True,
                            width="stretch", disabled=[c for c in df.columns if c not in ("status", "alasan")],
                            column_config={"status": st.column_config.SelectboxColumn(options=STATUSES,
                                                                                      required=True),
                                           "σ": st.column_config.NumberColumn(format="%.2f")})
    changed = edited[edited.status != df.status]
    c = st.columns(2)
    if c[0].button("Simpan koreksi", disabled=changed.empty, key="gr_correct"):
        if not by or (changed.alasan.fillna("").str.strip() == "").any():
            st.error("Isi nama peninjau dan alasan untuk setiap status yang diubah.")
        else:
            db.add_overrides([{"answer_id": aid, "reference_id": x.ref, "status": x.status, "by": by,
                               "date": date.today().isoformat(), "reason": x.alasan.strip()}
                              for x in changed.itertuples()])
            sc, _ = pipeline.apply_corrections(run_id, aid)
            flash(f"{aid}: skor terkoreksi {display_score(sc.score)} (SPARQL {display_score(sc.sparql_score)} ✓).")
            st.rerun()
    if c[1].button("Tandai ditinjau", type="primary", key="gr_reviewed"):
        if not by or not changed.empty:
            st.error("Isi nama peninjau, dan simpan koreksi dulu." if by else "Isi nama peninjau.")
        else:
            db.mark_reviewed(run_id, [aid], by)
            flash(f"{aid} ditandai ditinjau.")
            st.rerun()
    with st.expander("Umpan balik"):
        for claim in r["feedback"]["claims"]:
            st.markdown(f"- {html.escape(claim['text'])}")
        st.markdown(f"_{html.escape(r['feedback']['summary'])}_")
    for kind in ("ledger", "ledger_corrected"):
        name = kg.answer_graph_name(run_id, aid, kind)
        if kind == "ledger" or r["ledger_corrected"]:
            with st.expander(f"Turtle — named graph `{name}`"):
                st.code(kg.get_graph(name).serialize(format="turtle"), language="turtle")


def export_tab(course, assessment, table, run_id):
    qids = db.questions(assessment)
    code = next(c["code"] for c in db.courses() if c["id"] == course)
    name = next(a["name"] for a in db.assessments(course) if a["id"] == assessment)
    stem = importer.slug(f"{code}_{name}")
    final_ok = grades.ready(table)
    if final_ok:
        st.success("Semua jawaban sudah ditinjau. Ekspor final tersedia.")
    else:
        missing = table[table.status != "ditinjau"].status.value_counts()
        st.warning("Ekspor final terkunci: " + ", ".join(f"{n} {s}" for s, n in missing.items()) + ".")
    feedback = grades.feedback_csv(table, run_id).encode("utf-8-sig")
    st.subheader("Final")
    c = st.columns(2)
    c[0].download_button("Nilai (.csv)", grades.grades_csv(table, qids).encode("utf-8-sig"), disabled=not final_ok,
                         file_name=f"{stem}_nilai.csv", mime="text/csv", key="gr_final_grades")
    c[1].download_button("Umpan balik (.csv)", feedback, disabled=not final_ok, file_name=f"{stem}_umpan_balik.csv",
                         mime="text/csv", key="gr_final_feedback")
    st.subheader("Draf")
    st.caption("Selalu tersedia; berkas nilai diberi tanda DRAF dan kolom status per mahasiswa.")
    c = st.columns(2)
    c[0].download_button("Nilai draf (.csv)", grades.grades_csv(table, qids, draft=True).encode("utf-8-sig"),
                         file_name=f"{stem}_nilai_draf.csv", mime="text/csv", key="gr_draft_grades")
    c[1].download_button("Umpan balik draf (.csv)", feedback, file_name=f"{stem}_umpan_balik_draf.csv",
                         mime="text/csv", key="gr_draft_feedback")
    st.caption("Rata-rata dihitung atas semua soal penilaian; soal yang tidak dijawab dihitung 0 (sel kosong).")
