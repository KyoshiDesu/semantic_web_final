"""AutoGrade-RDF demo: streamlit run app/streamlit_app.py

Shows the Semantic Web pieces (OWL ontology, SWRL rules, RDF graphs, SPARQL) behind each score.
Works offline with hand-annotated triples and template feedback. Nothing here can change a score.
"""
import html
import re

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from rdflib import OWL, RDF, Namespace

import explorer
import rdfviz
from autograde import baselines, db, evaluate, io, kg, pipeline
from autograde import feedback as fb_mod
from autograde import ledger as ledger_mod
from autograde.evaluate import human_totals
from autograde.gold import criterion_weights
from autograde.models import STATUS_IRI_NAME
from autograde.score import score

st.set_page_config(page_title="AutoGrade-RDF", layout="wide")
try:
    if db.is_empty():
        raise db.NoDatabaseError("no questions in the database; run `python -m autograde db import`")
    kg.sync_ontology()
except (db.NoDatabaseError, db.SchemaVersionError, kg.KGBusyError) as e:
    st.error(str(e))
    st.stop()


# ---------- cached loaders ----------

@st.cache_resource
def context(qid):
    return pipeline.Context.load(qid)


@st.cache_data
def answers_table():
    df = io.load_answers(include_synthetic=True)
    human = io.load_human_scores(include_synthetic=True)
    totals = {}
    for qid in df.question_id.unique():
        ctx = context(qid)
        sub = human[human.answer_id.isin(df[df.question_id == qid].answer_id)]
        if len(sub):
            totals.update(human_totals(sub, {qid: criterion_weights(ctx.refs)},
                                       dict.fromkeys(sub.answer_id.unique(), qid)).to_dict())
    df["human"] = df.answer_id.map(totals)
    return df


def question_label(qid):
    lang = {"id": "ID", "en": "EN"}[context(qid).rubric.get("language", "id")]
    return f"{qid} · {lang}"


def gold_notice(ctx):
    if ctx.gold_raw.get("drafted_by"):
        st.warning(f"Triple acuan soal ini disusun oleh **{ctx.gold_raw['drafted_by']}** dan belum divalidasi dosen.")
    elif not ctx.gold_raw.get("validated_by"):
        st.info("Triple acuan ini adalah contoh dari presentasi dan belum divalidasi dosen.")


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def chip(status):
    return (f"<span style='background:{rdfviz.STATUS_COLOR[status]};color:white;border-radius:8px;padding:1px 8px;"
            f"font-size:0.85em'>{STATUS_IRI_NAME[status]}</span>")


# ---------- pages ----------

def page_ontology():
    st.header("Ontologi OWL `ag:`")
    st.caption("Skema (TBox) yang dimuat Pellet untuk setiap jawaban. Dibuat oleh `ontology/build_ontology.py`, "
               "dapat dibuka dan diperiksa di Protégé.")
    st.caption(f"Named graph: `{kg.ONTOLOGY}`")
    g = io.ontology_graph()
    SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
    c = st.columns(5)
    c[0].metric("Kelas", sum(1 for x in g.subjects(RDF.type, OWL.Class) if str(x).startswith(str(io.AG))))
    c[1].metric("Object property", len(set(g.subjects(RDF.type, OWL.ObjectProperty))))
    c[2].metric("Data property", len(set(g.subjects(RDF.type, OWL.DatatypeProperty))))
    c[3].metric("Predikat (ag:Relation)", len(set(g.subjects(RDF.type, io.AG.Relation))))
    c[4].metric("Aturan SWRL", len(set(g.subjects(RDF.type, SWRL.Imp))))
    tabs = st.tabs(["Hierarki kelas", "Properti", "Predikat & relasinya", "Aturan SWRL", "Berkas OWL"])
    with tabs[0]:
        st.graphviz_chart(rdfviz.ontology_classes_dot(g))
        st.caption("Garis putus merah: `owl:AllDisjointClasses` — tidak ada individu yang sekaligus triple acuan dan triple jawaban.")
    with tabs[1]:
        st.dataframe(rdfviz.properties_table(g), hide_index=True, use_container_width=True)
    with tabs[2]:
        lang = st.radio("Bahasa", ["Semua", "Indonesia", "Inggris"], horizontal=True)
        preds = io.load_predicates()["predicates"]
        only = None if lang == "Semua" else {p["id"] for p in preds if p.get("lang") == ("id" if lang.startswith("Indo") else "en")}
        st.graphviz_chart(rdfviz.relations_dot(g, only))
        st.caption("Biru: `ag:equivalentPredicate` (simetris & transitif) → dihitung cocok. "
                   "Merah: `ag:incompatibleWith` (simetris) → bahan aturan kontradiksi SWRL.")
        st.dataframe(pd.DataFrame([{"Predikat": p["id"], "Bahasa": p.get("lang"), "Alias (normalisasi teks)": ", ".join(p.get("aliases", [])),
                                    "Deskripsi": p["description"]} for p in preds
                                   if only is None or p["id"] in only]), hide_index=True, use_container_width=True)
    with tabs[3]:
        st.markdown("Python menegaskan `alignedSubject`/`alignedObject` hanya untuk pasangan dengan σ ≥ τ<sub>h</sub> "
                    "(SWRL tidak bisa menghitung embedding). Pellet lalu menyimpulkan `ag:contradicts`.", unsafe_allow_html=True)
        for block in (io.ROOT / "ontology" / "rules.swrl.txt").read_text(encoding="utf-8").strip().split("\n\n"):
            title, rule = block.split("\n", 1)
            st.markdown(f"**{title.lstrip('# ')}**")
            st.code(rule.replace(" ^ ", " ^\n  ").replace(" -> ", "\n  -> "), language="text")
        st.markdown("1 = predikat inkompatibel dan **tidak** dinegasi · 2 = predikat sama dinegasi · "
                    "3 = predikat setara dinegasi. Asumsi dunia terbuka: triple yang tidak ada **tidak** pernah jadi kontradiksi.")
    with tabs[4]:
        owl = io.ontology_path().read_text(encoding="utf-8")
        st.download_button("Unduh autograde.owl (RDF/XML)", owl, file_name="autograde.owl")
        st.code(owl[:6000] + ("\n…" if len(owl) > 6000 else ""), language="xml")


def page_question():
    qid = st.selectbox("Soal", io.question_ids(), format_func=question_label)
    ctx = context(qid)
    q = db.question(qid)
    gold_notice(ctx)
    c1, c2 = st.columns(2)
    c1.subheader("Soal")
    c1.markdown(strip_comments(q["prompt"]))
    c2.subheader("Jawaban acuan")
    c2.markdown(strip_comments(q["reference_answer"]))
    st.subheader("Rubrik dan triple acuan")
    w = criterion_weights(ctx.refs)
    st.dataframe(pd.DataFrame([{"Kriteria": c["id"], "Deskripsi": c["description"], "Bobot total": w[c["id"]]}
                               for c in ctx.rubric["criteria"]]), hide_index=True, use_container_width=True)
    st.dataframe(pd.DataFrame([{"ID": r.id, "Subjek (diterima)": " / ".join(r.s), "Predikat": r.p, "Objek": r.o,
                                "Kriteria": r.criterion, "Bobot": r.weight} for r in ctx.refs]),
                 hide_index=True, use_container_width=True)
    view = st.radio("Tampilan graf", ["Graf konsep", "RDF terreifikasi"], horizontal=True)
    st.caption(f"Named graph: `{kg.gold_graph_name(qid)}`")
    if view == "Graf konsep":
        st.graphviz_chart(rdfviz.gold_concept_dot(ctx.refs, ctx.gold_raw["concepts"]))
        st.caption("Garis putus abu-abu: subjek alternatif yang juga diterima. Garis putus hijau-biru: hierarki konsep "
                   "dosen (skos:broader) — menyebut konsep yang lebih umum memberi kredit parsial.")
    else:
        st.graphviz_chart(rdfviz.gold_reified_dot(qid, ctx.refs))
        st.caption("Triple RDF biasa tidak bisa diberi bobot, kriteria, atau sumber kalimat, "
                   "jadi setiap triple acuan dijadikan sumber daya `ag:ReferenceTriple`.")
    with st.expander("Konsep dan alias (normalisasi sebelum embedding)"):
        st.dataframe(pd.DataFrame([{"Konsep": f"key:{c}", "Alias": ", ".join((v or {}).get("aliases", [])),
                                    "Lebih umum (skos:broader)": ", ".join((v or {}).get("broader") or [])}
                                   for c, v in ctx.gold_raw["concepts"].items()]), hide_index=True, use_container_width=True)
    gold_name = kg.gold_graph_name(qid)
    with st.expander(f"Turtle — named graph `{gold_name}`"):
        st.code(kg.get_graph(gold_name).serialize(format="turtle"), language="turtle")


def page_grade():
    qid = st.selectbox("Soal", io.question_ids(), format_func=question_label)
    ctx = context(qid)
    gold_notice(ctx)
    df = answers_table()
    df = df[df.question_id == qid]
    source = st.radio("Sumber jawaban", ["Jawaban tersimpan", "Tempel jawaban baru"], horizontal=True)
    if source == "Jawaban tersimpan":
        only_annotated = st.checkbox("Hanya jawaban yang punya anotasi triple (bisa dinilai offline)", value=True)
        if only_annotated:
            df = df[df.annotated]
        if df.empty:
            st.info("Tidak ada jawaban untuk pilihan ini.")
            return
        labels = {f"{a.answer_id} · {a.split}" + (f" · dosen {a.human:.0f}" if pd.notna(a.human) else "")
                  + (" · anotasi ✓" if a.annotated else "") + (" · sintetis" if a.synthetic else ""): a for a in df.itertuples()}
        a = labels[st.selectbox("Jawaban", list(labels))]
        answer_id, text = a.answer_id, a.text
        st.markdown(f"> {html.escape(text)}".replace("\n", "<br>"), unsafe_allow_html=True)
        c = st.columns(3)
        if pd.notna(a.human):
            c[0].metric("Nilai manusia" + (" (sintetis)" if a.synthetic else ""), f"{a.human:.1f}")
        c[1].metric("Baseline B1 (kata kunci)", f"{baselines.b1_keyword(text, ctx.refs, ctx.gold_raw['concepts']):.1f}")
        by = (db.annotation(answer_id) or {}).get("annotated_by")
        if by:
            st.warning(f"Anotasi triple jawaban ini ditulis oleh **{by}**.")
    else:
        answer_id = f"{qid}_UI"
        text = st.text_area("Jawaban mahasiswa", height=120)
    has_annotation = db.annotation(answer_id) is not None
    mode = st.radio("Ekstraksi triple", ["gold", "llm"], horizontal=True, index=0 if has_annotation else 1,
                    format_func=lambda m: "Anotasi (gold)" if m == "gold" else "LLM (butuh API key)")
    use_llm_fb = st.checkbox("Umpan balik dari LLM (butuh API key)", value=False)
    if st.button("Nilai jawaban", type="primary"):
        if mode == "gold" and not has_annotation:
            st.error("Tidak ada anotasi untuk jawaban ini. Pilih mode LLM.")
            return
        try:
            with st.spinner("Ekstraksi → pencocokan → Pellet/SWRL → ledger → SPARQL…"):
                res = pipeline.run_answer(ctx, answer_id, text, mode, pipeline.ui_run(), use_llm_fb)
        except Exception as e:  # e.g. no API key for LLM extraction
            st.error(f"Gagal menilai: {e}")
            return
        st.session_state["graded"] = {"qid": qid, "answer_id": answer_id, "res": res}
    graded = st.session_state.get("graded")
    if graded and graded["qid"] == qid and graded["answer_id"] == answer_id:
        show_result(qid, answer_id, graded["res"])


def show_result(qid, answer_id, res):
    ctx, sc, entries = context(qid), res["score"], res["entries"]
    st.divider()
    c = st.columns(5)
    c[0].metric("Skor sistem", fb_mod.display_score(sc.score))
    c[1].metric("Σ w·m", f"{sc.sum_weighted_credit:g}")
    c[2].metric("Penalti λ·Σ w·κ", f"{sc.sum_penalty:g}")
    c[3].metric("Σ w", f"{sc.sum_weights:g}")
    ok = abs(sc.score - sc.sparql_score) < 1e-9
    c[4].metric("Hitung ulang SPARQL", fb_mod.display_score(sc.sparql_score), "✓ sama" if ok else "✗ berbeda",
                delta_color="normal" if ok else "inverse")
    with st.expander("Bukti hitung ulang SPARQL (dibaca dari graf tersimpan)"):
        gold_name, _, ledger_name = rdfviz.answer_graph_names(qid, res["run_id"], answer_id)
        rows = ledger_mod.recompute_rows(kg.get_graph(ledger_name), kg.get_graph(gold_name), ctx.params["lambda"])
        st.code(ledger_mod.RECOMPUTE_QUERY.strip(), language="sparql")
        st.dataframe(pd.DataFrame([{"answer": rdfviz.short(r.ans), "skor (sebelum dipotong di 0)": float(r.raw.toPython())}
                                   for r in rows]), hide_index=True)
        st.caption(f"Skor Python = {sc.score:.4f} · skor SPARQL dari triple store = {sc.sparql_score:.4f} "
                   f"{'✓' if ok else '✗'} · graf: `{ledger_name}` + `{gold_name}`")
    tabs = st.tabs(["Ledger & umpan balik", "Graf interaktif", "Graf penyelarasan", "Penalaran", "RDF (Turtle)", "SPARQL"])
    with tabs[0]:
        show_ledger(ctx, answer_id, res)
    with tabs[1]:
        human = answers_table().set_index("answer_id").human.dropna().to_dict()
        components.html(explorer.html(explorer.build(ctx, [explorer.load_answer(res["run_id"], answer_id)], ctx.params,
                                                     human), height=600), height=700, scrolling=False)
    with tabs[2]:
        st.graphviz_chart(rdfviz.alignment_dot(ctx.refs, res["students"], entries, res["trace"]))
        st.caption("Kiri: triple hasil ekstraksi ([konsep] dari tabel alias, [?] = tidak dikenal → embedding). "
                   "Kanan: triple acuan berwarna sesuai status. Panah tebal: bukti di ledger; "
                   "merah: `ag:contradicts` dari SWRL; titik-titik: selaras tetapi predikat lain. "
                   f"Dibaca dari `{kg.answer_graph_name(res['run_id'], answer_id, 'answer')}`.")
    with tabs[3]:
        show_reasoning(ctx, answer_id, res)
    names = rdfviz.answer_graph_names(qid, res["run_id"], answer_id)
    with tabs[4]:
        captions = ["Graf acuan (kunci dosen)", "Triple jawaban + provenance PROV-O + masukan/keluaran penalaran",
                    "Ledger: satu ag:LedgerEntry per triple acuan"]
        for name, caption in zip(names, captions):
            ttl = kg.get_graph(name).serialize(format="turtle")
            with st.expander(f"{caption} — `{name}`", expanded=name.endswith(":ledger")):
                st.code(ttl, language="turtle")
                st.download_button("Unduh Turtle", ttl, file_name=rdfviz.turtle_file_name(name), key=f"dl_{name}")
    with tabs[5]:
        g = rdfviz.merged_graph(names)
        st.caption(f"Graf gabungan: ontologi + {', '.join(f'`{n}`' for n in names)} ({len(g)} triple). Hanya baca.")
        sparql_console(g, rdfviz.ANSWER_QUERIES, "ans")


def show_ledger(ctx, answer_id, res):
    entries, refs = res["entries"], {r.id: r for r in ctx.refs}
    sentences = dict(res["sentences"])
    rows = "".join(
        f"<tr><td><code>{e.reference_id}</code></td><td>{html.escape(fb_mod.triple_label(refs[e.reference_id]))}</td>"
        f"<td>{e.criterion}</td><td>{e.weight:g}</td><td>{chip(e.status)}{' ⚑' if e.needs_review else ''}</td>"
        f"<td>{e.credit:g}</td><td>{'–' if e.sigma is None else f'{e.sigma:.2f}'}</td>"
        f"<td>{html.escape(' '.join(sentences.get(s, '') for s in e.sentence_ids)) or '–'}</td></tr>"
        for e in entries)
    st.markdown("<table><tr><th>Ref</th><th>Triple acuan</th><th>Kriteria</th><th>w</th><th>Status</th><th>m</th>"
                f"<th>σ</th><th>Kalimat bukti</th></tr>{rows}</table>", unsafe_allow_html=True)
    st.caption("⚑ = parsial, perlu ditinjau dosen. Setiap baris ditelusuri ke triple acuan, kriteria, bobot, dan kalimat.")
    overrides = db.overrides(answer_id)
    if overrides:
        fixed = ledger_mod.apply_overrides(entries, overrides, ctx.params)
        st.subheader("Ledger setelah koreksi dosen")
        st.dataframe(pd.DataFrame([{"Ref": e.reference_id, "Status": STATUS_IRI_NAME[e.status], "m": e.credit,
                                    "Koreksi": f"{e.override['by']}: {e.override['reason']}" if e.override else ""}
                                   for e in fixed]), hide_index=True)
        st.metric("Skor terkoreksi", fb_mod.display_score(score(answer_id, fixed, ctx.params).score))
    st.subheader("Umpan balik")
    fb = res["feedback"]
    for c in fb.claims:
        st.markdown(f"- {html.escape(c.text)} <small>({', '.join(c.ledger_entry_ids)})</small>", unsafe_allow_html=True)
    st.markdown(f"_{html.escape(fb.summary)}_ · sumber: {'LLM' if fb.source == 'llm' else 'templat'}")


def show_reasoning(ctx, answer_id, res):
    p = ctx.params
    st.markdown(f"**1 · Normalisasi konsep** — tabel alias dulu, embedding hanya untuk konsep yang tidak dikenal. "
                f"Parameter: τ<sub>h</sub> = {p['tau_h']}, τ<sub>l</sub> = {p['tau_l']}, δ = {p['delta']}, λ = {p['lambda']}.",
                unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{"Triple": t.id.rsplit("_", 1)[1], "Subjek": t.s_text, "→ konsep": t.s_concept or "? (embedding)",
                                "Predikat": t.p, "Negasi": t.negated, "Objek": t.o_text,
                                "→ konsep ": t.o_concept or "? (embedding)", "Kalimat": ", ".join(t.sentence_ids)}
                               for t in res["students"]]), hide_index=True, use_container_width=True)
    if res["students"]:
        st.markdown("**2 · σ = min(sim subjek, sim objek)** untuk setiap pasangan (baris: triple jawaban, kolom: triple acuan).")
        table = rdfviz.sigma_table(ctx.refs, res["students"], res["trace"]["sigmas"])
        st.dataframe(table.style.format("{:.2f}").background_gradient(cmap="Greens", vmin=0, vmax=1),
                     use_container_width=True)
    aligned = res["trace"]["aligned"]
    st.markdown(f"**3 · Fakta yang ditegaskan Python ke Pellet** (σ ≥ τ<sub>h</sub>): {len(aligned)} pasangan",
                unsafe_allow_html=True)
    if aligned:
        st.code("\n".join(f"ans:{t} ag:alignedSubject key:{ctx.qid}_{r} ; ag:alignedObject key:{ctx.qid}_{r} ." for t, r in aligned),
                language="turtle")
    contra = res["trace"]["contradictions"]
    st.markdown(f"**4 · Disimpulkan Pellet dengan aturan SWRL:** {len(contra)} `ag:contradicts`")
    if contra:
        st.code("\n".join(f"ans:{t} ag:contradicts key:{ctx.qid}_{r} ." for t, r in contra), language="turtle")
    else:
        st.caption("Tidak ada kontradiksi. Triple acuan yang tidak disebut tetap Hilang (asumsi dunia terbuka).")
    st.markdown("**5 · Pellet: sebelum dan sesudah penalaran**")
    if aligned:
        answer_name = kg.answer_graph_name(res["run_id"], answer_id, "answer")
        g = kg.get_graph(answer_name, kg.gold_graph_name(ctx.qid))
        _, eq, inc = io.ontology_relations()
        before, after = rdfviz.pellet_dots(g, eq, inc)
        c = st.columns(2)
        c[0].caption("Sebelum: fakta yang ditegaskan Python (masukan Pellet)")
        c[0].graphviz_chart(before)
        c[1].caption("Sesudah: + `ag:contradicts` yang disimpulkan (merah putus-putus, dengan nomor aturan SWRL)")
        c[1].graphviz_chart(after)
        st.caption(f"Dibaca dari named graph `{answer_name}` + `{kg.gold_graph_name(ctx.qid)}`.")
    else:
        st.caption("Tidak ada pasangan selaras (σ ≥ τh), jadi Pellet tidak punya masukan untuk aturan kontradiksi.")
    if res["log"]:
        with st.expander(f"{len(res['log'])} triple dibuang saat ekstraksi (cek grounding)"):
            st.json(res["log"])


def sparql_console(g, presets, key):
    preset = st.selectbox("Kueri contoh", list(presets), key=f"preset_{key}")
    query = st.text_area("SPARQL", presets[preset], height=260, key=f"q_{key}_{preset}")
    if st.button("Jalankan kueri", key=f"run_{key}"):
        try:
            result = rdfviz.run_query(g, query)
        except Exception as e:
            st.error(f"Kueri gagal: {e}")
            return
        if isinstance(result, str):
            st.code(result or "# (graf kosong)", language="turtle")
        else:
            st.dataframe(result, hide_index=True, use_container_width=True)
            st.caption(f"{len(result)} baris")


def page_sparql():
    st.header("Konsol SPARQL")
    st.caption("Kueri berjalan pada graf RDF lokal (rdflib), hanya baca. Kueri federasi (SERVICE) dinonaktifkan.")
    graded = st.session_state.get("graded")
    runs = pipeline.completed_runs()
    options = (["Jawaban terakhir yang dinilai"] if graded else []) + [f"Run: {r['run_id']}" for r in runs]
    if not options:
        st.info("Nilai sebuah jawaban dulu, atau buat run: `python -m autograde run …`.")
        return
    choice = st.selectbox("Graf", options)
    if choice.startswith("Jawaban"):
        g = rdfviz.merged_graph(rdfviz.answer_graph_names(graded["qid"], graded["res"]["run_id"], graded["answer_id"]))
        presets = rdfviz.ANSWER_QUERIES
    else:
        g = rdfviz.merged_graph(rdfviz.run_graph_names(choice.removeprefix("Run: ")))
        presets = {**rdfviz.RUN_QUERIES, **rdfviz.ANSWER_QUERIES}
    st.caption(f"{len(g)} triple RDF dimuat dari triple store.")
    sparql_console(g, presets, "global")


def page_explorer():
    st.header("Penjelajah Graf (Semantic Explorer)")
    st.caption("Graf pengetahuan satu soal. Node = sumber daya RDF dari tiga namespace: ag: (skema/ontologi), "
               "key: (data dosen: konsep, triple acuan, hierarki skos:broader), ans: (data mahasiswa: jawaban, triple, "
               "ledger). Garis = properti RDF/OWL/SKOS/PROV.")
    qid = st.selectbox("Soal", io.question_ids(), format_func=question_label, key="explorer_q")
    ctx = context(qid)
    sources = {}
    for run in pipeline.completed_runs():
        ids = db.result_ids(run["run_id"], qid)
        if ids:
            sources[f"Run {run['run_id']} · {len(ids)} jawaban"] = (run["run_id"], ids, run["params"])
    ui_ids = db.result_ids(pipeline.UI_RUN, qid)
    if ui_ids:
        sources[f"Dinilai di aplikasi · {len(ui_ids)} jawaban"] = (pipeline.UI_RUN, ui_ids, ctx.params)
    if not sources:
        st.info("Belum ada jawaban yang dinilai untuk soal ini. Nilai jawaban di halaman *Nilai Jawaban*, atau buat run "
                "dengan `python -m autograde run …`. Graf kunci tetap ditampilkan di bawah.")
        run_id, ids, params = None, [], ctx.params
    else:
        run_id, ids, params = sources[st.selectbox("Sumber jawaban", list(sources))]
    chosen = st.multiselect("Jawaban yang ditampilkan", ids, default=ids[:12]) if ids else []
    human = answers_table().set_index("answer_id").human.dropna().to_dict()
    graph = explorer.build(ctx, [explorer.load_answer(run_id, a) for a in chosen], params, human)
    st.caption(f"{len(graph['nodes'])} node · {len(graph['edges'])} relasi")
    st.caption(f"Named graph: `{kg.gold_graph_name(qid)}` + graf answer/ledger tiap jawaban terpilih.")
    components.html(explorer.html(graph, height=640), height=740, scrolling=False)


def page_evaluation():
    runs = [r for r in pipeline.completed_runs() if r["evaluation_md"]]
    if not runs:
        st.info("Belum ada hasil evaluasi. Jalankan `python -m autograde evaluate --run <run_id>`.")
        return
    run = st.selectbox("Run", runs, format_func=lambda r: r["run_id"])
    st.markdown(run["evaluation_md"])
    out = evaluate.report_dir(run["run_id"])
    for col, name in zip(st.columns(2), ["scatter.png", "per_criterion.png"]):
        if (out / name).exists():
            col.image(str(out / name))


def page_kg():
    st.header("Graf Pengetahuan (triple store Oxigraph)")
    st.caption("Semua graf RDF tersimpan sebagai named graph dalam satu triple store: ontologi, kunci tiap soal, "
               "dan graf jawaban/ledger tiap jawaban yang dinilai. Hanya baca.")
    graphs = pd.DataFrame(kg.graphs())
    if graphs.empty:
        st.info("Triple store kosong. Jalankan `python -m autograde db import`.")
        return
    question_of = answers_table().set_index("answer_id").question_id
    graphs["question"] = graphs.question.fillna(graphs.answer.map(question_of))
    c = st.columns(3)
    c[0].metric("Named graph", len(graphs))
    c[1].metric("Triple (total)", int(graphs.triples.sum()))
    c[2].metric("Run", graphs.run.nunique())
    st.dataframe(graphs, hide_index=True, use_container_width=True)
    name = st.selectbox("Lihat satu graf", list(graphs.name))
    g = kg.get_graph(name)
    tabs = st.tabs(["Turtle", "Graf interaktif", "Tabel triple", "SPARQL (seluruh dataset)"])
    with tabs[0]:
        ttl = g.serialize(format="turtle")
        st.download_button("Unduh Turtle", ttl, file_name=rdfviz.turtle_file_name(name), key="kg_dl")
        st.code(ttl, language="turtle")
    with tabs[1]:
        vis = rdfviz.vis_graph(g)
        if vis["truncated"]:
            st.caption(f"Menampilkan 400 dari {len(g)} triple.")
        components.html(explorer.html(vis, height=600, node_types=rdfviz.VIS_NODE_TYPES,
                                      edge_types=rdfviz.VIS_EDGE_TYPES), height=700, scrolling=False)
    with tabs[2]:
        st.dataframe(pd.DataFrame([[rdfviz.short(s), rdfviz.short(p), rdfviz.short(o)] for s, p, o in sorted(g)],
                                  columns=["subjek", "predikat", "objek"]), hide_index=True, use_container_width=True)
    with tabs[3]:
        st.caption("Graf bawaan = gabungan semua named graph; pakai `GRAPH ?g { … }` untuk melihat asal triple.")
        preset = st.selectbox("Kueri contoh", list(rdfviz.KG_QUERIES), key="kg_preset")
        query = st.text_area("SPARQL", rdfviz.KG_QUERIES[preset], height=260, key=f"kg_q_{preset}")
        if st.button("Jalankan kueri", key="kg_run"):
            try:
                result = kg.query(query)
            except Exception as e:
                st.error(f"Kueri gagal: {e}")
                return
            if isinstance(result, str):
                st.code(result or "# (graf kosong)", language="turtle")
            else:
                st.dataframe(result.map(lambda v: rdfviz.short(v) if isinstance(v, str) else v),
                             hide_index=True, use_container_width=True)
                st.caption(f"{len(result)} baris")


PAGES = {"Ontologi": page_ontology, "Soal & Kunci": page_question, "Penjelajah Graf": page_explorer,
         "Nilai Jawaban": page_grade, "Konsol SPARQL": page_sparql, "Evaluasi": page_evaluation,
         "Graf Pengetahuan": page_kg}
st.sidebar.title("AutoGrade-RDF")
page = st.sidebar.radio("Halaman", list(PAGES), index=3)
st.sidebar.caption("Skor = fungsi eksplisit atas ledger triple RDF (Pers. 6). LLM tidak pernah menentukan skor.")
PAGES[page]()
