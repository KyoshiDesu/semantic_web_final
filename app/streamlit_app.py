"""AutoGrade-RDF demo: streamlit run app/streamlit_app.py

Works offline with gold-mode annotations and template feedback. There is no control that changes a score.
"""
import html

import pandas as pd
import streamlit as st

from autograde import feedback as fb_mod
from autograde import io, ledger, pipeline
from autograde.models import STATUS_IRI_NAME
from autograde.score import score

st.set_page_config(page_title="AutoGrade-RDF", layout="wide")
CHIP = {"MATCHED": "#2e7d32", "PARTIAL": "#b26a00", "MISSING": "#616161", "CONTRADICTED": "#c62828"}


@st.cache_resource
def context(qid):
    return pipeline.Context.load(qid)


def chip(status):
    return (f"<span style='background:{CHIP[status]};color:white;border-radius:8px;padding:1px 8px;"
            f"font-size:0.85em'>{STATUS_IRI_NAME[status]}</span>")


def page_question():
    qid = st.selectbox("Soal", io.question_ids())
    ctx = context(qid)
    d = io.question_dir(qid)
    st.subheader("Soal")
    st.markdown(d.joinpath("question.md").read_text(encoding="utf-8"))
    st.subheader("Rubrik")
    st.table(pd.DataFrame(ctx.rubric["criteria"]).rename(columns={"id": "Kriteria", "description": "Deskripsi"}))
    st.subheader("Triple acuan (gold)")
    st.table(pd.DataFrame([{"ID": r.id, "Subjek": " / ".join(r.s), "Predikat": r.p, "Objek": r.o,
                            "Kriteria": r.criterion, "Bobot": r.weight} for r in ctx.refs]))
    edges = "\n".join(f'"{s}" -> "{r.o}" [label="{r.p} ({r.id})"]' for r in ctx.refs for s in r.s[:1])
    st.graphviz_chart(f"digraph {{ rankdir=LR; node [shape=box, style=rounded]; {edges} }}")


def page_grade():
    answers = io.load_answers(include_synthetic=True)
    choice = st.radio("Sumber jawaban", ["Pilih jawaban tersimpan", "Tempel jawaban baru"], horizontal=True)
    if choice == "Pilih jawaban tersimpan":
        labels = {f"{a.answer_id}{' (sintetis)' if a.synthetic else ''}": a for a in answers.itertuples()}
        a = labels[st.selectbox("Jawaban", list(labels))]
        answer_id, qid, text = a.answer_id, a.question_id, a.text
        st.info(a.text)
    else:
        qid = st.selectbox("Soal", io.question_ids())
        answer_id = f"{qid}_UI"
        text = st.text_area("Jawaban mahasiswa", height=120)
    has_annotation = io.annotation_path(answer_id) is not None
    mode = st.radio("Ekstraksi triple", ["gold", "llm"], horizontal=True, index=0 if has_annotation else 1,
                    format_func=lambda m: "Anotasi manual (gold)" if m == "gold" else "LLM")
    use_llm_fb = st.checkbox("Umpan balik dari LLM (butuh API key)", value=False)
    if not st.button("Nilai jawaban", type="primary"):
        return
    if mode == "gold" and not has_annotation:
        st.error("Tidak ada anotasi manual untuk jawaban ini. Pilih mode LLM.")
        return
    try:
        res = pipeline.run_answer(context(qid), answer_id, text, mode, io.ROOT / "outputs" / "ui" / answer_id, use_llm_fb)
    except Exception as e:  # e.g. no API key for LLM extraction
        st.error(f"Gagal menilai: {e}")
        return
    show_result(qid, answer_id, res)


def show_result(qid, answer_id, res):
    ctx, sc, entries = context(qid), res["score"], res["entries"]
    cited = {}
    for e in entries:
        for s in e.sentence_ids:
            cited.setdefault(s, e.status)
    st.subheader("Kalimat")
    for sid, text in res["sentences"]:
        color = CHIP.get(cited.get(sid), None)
        style = f"border-left:4px solid {color};padding-left:8px" if color else "padding-left:12px"
        st.markdown(f"<div style='{style}'><code>{sid}</code> {html.escape(text)}</div>", unsafe_allow_html=True)
    st.subheader("Ledger")
    refs = {r.id: r for r in ctx.refs}
    rows = "".join(
        f"<tr><td><code>{e.entry_id}</code></td><td>{fb_mod.triple_label(refs[e.reference_id])}</td><td>{e.criterion}</td>"
        f"<td>{e.weight:g}</td><td>{chip(e.status)}{' ⚑' if e.needs_review else ''}</td><td>{e.credit:g}</td>"
        f"<td>{e.matched_by or e.contradicted_by or '–'}</td>"
        f"<td>{'' if e.sigma is None else f'{e.sigma:.2f}'}</td><td>{' '.join(e.sentence_ids) or '–'}</td></tr>"
        for e in entries)
    st.markdown("<table><tr><th>ID</th><th>Triple acuan</th><th>Kriteria</th><th>w</th><th>Status</th><th>m</th>"
                f"<th>Bukti</th><th>σ</th><th>Kalimat</th></tr>{rows}</table>", unsafe_allow_html=True)
    st.caption("⚑ = perlu ditinjau dosen (parsial)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Σ w·m", f"{sc.sum_weighted_credit:g}")
    c2.metric("Penalti λ·Σ w·κ", f"{sc.sum_penalty:g}")
    c3.metric("Σ w", f"{sc.sum_weights:g}")
    c4.metric("Skor", fb_mod.display_score(sc.score))
    ok = abs(sc.score - sc.sparql_score) < 1e-9
    st.markdown(f"**Hitung ulang SPARQL:** {fb_mod.display_score(sc.sparql_score)} {'✓ sama' if ok else '✗ berbeda'}")
    ov_path = io.ROOT / "data" / "human" / "overrides.yaml"
    overrides = [o for o in (io.load_yaml(ov_path) or []) if o["answer_id"] == answer_id] if ov_path.exists() else []
    if overrides:
        fixed = ledger.apply_overrides(entries, overrides, ctx.params)
        st.subheader("Ledger setelah koreksi dosen")
        st.table(pd.DataFrame([{"ID": e.entry_id, "Status": STATUS_IRI_NAME[e.status], "m": e.credit,
                                "Koreksi": f"{e.override['by']}: {e.override['reason']}" if e.override else ""}
                               for e in fixed]))
        st.metric("Skor terkoreksi", fb_mod.display_score(score(answer_id, fixed, ctx.params).score))
    st.subheader("Umpan balik")
    fb = res["feedback"]
    for c in fb.claims:
        st.markdown(f"- {html.escape(c.text)} <small>({', '.join(c.ledger_entry_ids)})</small>", unsafe_allow_html=True)
    st.markdown(f"_{html.escape(fb.summary)}_ · sumber: {'LLM' if fb.source == 'llm' else 'templat'}")
    if res["log"]:
        with st.expander(f"{len(res['log'])} triple dibuang saat ekstraksi"):
            st.json(res["log"])


def page_evaluation():
    runs = sorted((p for p in pipeline.runs_dir().glob("*") if (p / "evaluation.md").exists()), reverse=True) \
        if pipeline.runs_dir().exists() else []
    if not runs:
        st.info("Belum ada hasil evaluasi. Jalankan `python -m autograde evaluate --run <run_id>`.")
        return
    run = st.selectbox("Run", runs, format_func=lambda p: p.name)
    st.markdown(run.joinpath("evaluation.md").read_text(encoding="utf-8"))
    cols = st.columns(2)
    for col, name in zip(cols, ["scatter.png", "per_criterion.png"]):
        if (run / name).exists():
            col.image(str(run / name))


PAGES = {"Soal & Rubrik": page_question, "Nilai Jawaban": page_grade, "Evaluasi": page_evaluation}
st.sidebar.title("AutoGrade-RDF")
PAGES[st.sidebar.radio("Halaman", list(PAGES))]()
