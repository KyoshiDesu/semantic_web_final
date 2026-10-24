"""Score agreement (r, ρ, MAE, RMSE), audit metrics (EP, ER, FF), figures, and the audit template."""
import numpy as np
import pandas as pd
from scipy import stats

from autograde import baselines, db, gold, io, llm
from autograde.models import LedgerEntry
from autograde.score import score


class NotFrozenError(RuntimeError):
    pass


def human_criterion_scores(scores):
    """Mean over raters of each (answer, criterion) score."""
    return scores.groupby(["answer_id", "criterion"])["score_0_100"].mean()


def human_totals(scores, weights_by_question, question_of):
    """100-scale total per answer: criterion scores weighted by the sum of that criterion's triple weights."""
    per_crit = human_criterion_scores(scores)
    totals = {}
    for answer_id in sorted(per_crit.index.get_level_values(0).unique()):
        weights = weights_by_question[question_of[answer_id]]
        crit = per_crit.loc[answer_id]
        if io.TOTAL in crit.index:  # holistic score: no per-criterion breakdown
            totals[answer_id] = crit[io.TOTAL]
            continue
        missing = set(weights) - set(crit.index)
        if missing:
            raise ValueError(f"{answer_id}: no human score for criteria {sorted(missing)}")
        totals[answer_id] = sum(weights[c] * crit[c] for c in weights) / sum(weights.values())
    return pd.Series(totals, name="human")


def icc_2_1(matrix):
    """ICC(2,1) (two-way random, absolute agreement, single rater) for an answers × raters matrix."""
    x = np.asarray(matrix, dtype=float)
    n, k = x.shape
    grand = x.mean()
    msr = k * ((x.mean(axis=1) - grand) ** 2).sum() / (n - 1)
    msc = n * ((x.mean(axis=0) - grand) ** 2).sum() / (k - 1)
    mse = ((x - x.mean(axis=1, keepdims=True) - x.mean(axis=0, keepdims=True) + grand) ** 2).sum() / ((n - 1) * (k - 1))
    return (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n)


def agreement(system, human):
    s, h = np.asarray(system, float), np.asarray(human, float)
    row = {"n": len(s), "MAE": float(np.mean(np.abs(s - h))), "RMSE": float(np.sqrt(np.mean((s - h) ** 2)))}
    if len(s) >= 3 and s.std() > 0 and h.std() > 0:
        r, rp = stats.pearsonr(s, h)
        rho, sp = stats.spearmanr(s, h)
        row.update(pearson_r=float(r), pearson_p=float(rp), spearman_rho=float(rho), spearman_p=float(sp))
    else:  # undefined for constant or tiny samples
        row.update(pearson_r=np.nan, pearson_p=np.nan, spearman_rho=np.nan, spearman_p=np.nan)
    return row


def report_dir(run_id):
    """Metrics CSVs and figures; the report text itself is stored with the run in the database."""
    return io.ROOT / "outputs" / "reports" / run_id


def load_ledger(run_id, answer_id, corrected=False):
    r = db.result(run_id, answer_id)
    return [LedgerEntry(**e) for e in (r["ledger_corrected"] if corrected else r["ledger"])]


def criterion_scores(entries):
    out = {}
    for c in sorted({e.criterion for e in entries}):
        es = [e for e in entries if e.criterion == c]
        out[c] = 100 * sum(e.weight * e.credit for e in es) / sum(e.weight for e in es)
    return out


def audit_metrics(run_id):
    df = db.evidence_audit()
    df = df[df.run_id == run_id]
    if df.empty:
        return {}
    answer = {c: df[c].str.strip().str.lower() for c in ("evidence_correct", "present_in_answer", "supported")}
    ledger_row, detected = df.row_type == "ledger", df.status.isin(["MATCHED", "PARTIAL"])
    out = {}
    hits = ledger_row & detected & (answer["evidence_correct"] != "")
    if hits.any():
        out["EP"] = ((answer["evidence_correct"][hits] == "yes").mean(), int(hits.sum()))
    present = ledger_row & (answer["present_in_answer"] == "yes")
    if present.any():
        out["ER"] = (detected[present].mean(), int(present.sum()))
    claims = (df.row_type == "claim") & (answer["supported"] != "")
    if claims.any():
        out["FF"] = ((answer["supported"][claims] == "yes").mean(), int(claims.sum()))
    return out


def evaluate(run_id, gold_run_id=None, b2_backend=None):
    run = db.run(run_id)
    if run is None:
        raise LookupError(f"no run {run_id}")
    synthetic = run["include_synthetic"]
    if not run["params_frozen"] and not synthetic:
        raise NotFrozenError("this run used unfrozen parameters; run `calibrate` and re-run the test split")
    if run["split"] not in ("test", "all"):
        raise ValueError("evaluate needs a run that covers the test split")
    runs = db.run_scores(run_id)
    runs = runs[runs.split == "test"].sort_values("answer_id").reset_index(drop=True)
    question_of = dict(zip(runs.answer_id, runs.question_id))
    ctx = {q: gold.load(q) for q in sorted(set(runs.question_id))}
    weights = {q: gold.criterion_weights(refs) for q, (_, _, refs) in ctx.items()}
    scores = io.load_human_scores(synthetic)
    scores = scores[scores.answer_id.isin(runs.answer_id)]
    human = human_totals(scores, weights, question_of)
    runs = runs[runs.answer_id.isin(human.index)]
    h = human[runs.answer_id].to_numpy()

    texts = io.load_answers(synthetic).set_index("answer_id").text
    systems = {f"System ({run['mode']} mode)": runs.score.to_numpy()}
    lam05 = [score(a, load_ledger(run_id, a), {"lambda": 0.5}).score for a in runs.answer_id]
    systems[f"System ({run['mode']} mode), λ = 0.5"] = np.array(lam05)
    if gold_run_id:
        g = db.run_scores(gold_run_id).set_index("answer_id")
        systems["System (gold mode)"] = g.loc[runs.answer_id, "score"].to_numpy()
    systems["B1 keyword"] = np.array([baselines.b1_keyword(texts[a], ctx[question_of[a]][2],
                                                            ctx[question_of[a]][0]["concepts"]) for a in runs.answer_id])
    try:
        systems["B2 LLM-only"] = np.array([baselines.b2_llm(question_of[a], texts[a], ctx[question_of[a]][2],
                                                             ctx[question_of[a]][1], backend=b2_backend)
                                           for a in runs.answer_id])
    except llm.LLMError as e:
        b2_note = f"B2 LLM-only not computed: {e}"
    else:
        b2_note = ""

    metrics = pd.DataFrame([{"system": name, **agreement(vals, h)} for name, vals in systems.items()])
    per_question = pd.DataFrame([{"question_id": q, "system": name, **agreement(vals[m], h[m])}
                                 for q in sorted(set(runs.question_id)) for name, vals in systems.items()
                                 for m in [(runs.question_id == q).to_numpy()]])
    human_crit = human_criterion_scores(scores)
    crit_rows = []
    for a in runs.answer_id:
        for c, s in criterion_scores(load_ledger(run_id, a)).items():
            if (a, c) not in human_crit.index:  # holistic human score only
                continue
            crit_rows.append({"answer_id": a, "criterion": c, "system": s, "human": human_crit.loc[(a, c)]})
    crit = pd.DataFrame(crit_rows, columns=["answer_id", "criterion", "system", "human"])
    per_criterion = crit.assign(abs_err=(crit.system - crit.human).abs()).groupby("criterion").abs_err.mean()

    icc = None
    raters = sorted(scores.rater_id.unique())
    if len(raters) >= 2:  # ICC on per-rater totals over the answers every rater graded
        per_rater = pd.DataFrame({r: human_totals(scores[scores.rater_id == r], weights, question_of)
                                  for r in raters}).dropna()
        if len(per_rater) >= 3:
            icc = (icc_2_1(per_rater.to_numpy()), len(per_rater))
    recon = float((abs(runs.score - runs.sparql_score) < 1e-9).mean())
    audit = audit_metrics(run_id)

    out = report_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    metrics.round(6).to_csv(out / "metrics.csv", index=False)
    per_question.round(6).to_csv(out / "metrics_per_question.csv", index=False)
    per_criterion.round(6).to_csv(out / "per_criterion_mae.csv")
    figures(out, runs.score.to_numpy(), h, per_criterion)
    report = render(run, metrics, per_criterion, icc, recon, audit, b2_note, len(runs))
    db.save_evaluation(run_id, report)
    return report


def figures(run_dir, system, human, per_criterion):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.5, 4.5), dpi=300)
    ax.scatter(human, system, s=18, color="#2a6f97")
    ax.plot([0, 100], [0, 100], color="#999999", lw=0.8, ls="--")
    ax.set(xlim=(-2, 102), ylim=(-2, 102), xlabel="Nilai dosen", ylabel="Skor sistem")
    fig.tight_layout()
    fig.savefig(run_dir / "scatter.png", metadata={"Software": None})
    plt.close(fig)
    if per_criterion.empty:  # holistic human scores only
        return
    fig, ax = plt.subplots(figsize=(5, 3), dpi=300)
    ax.bar(per_criterion.index, per_criterion.values, color="#2a6f97")
    ax.set(ylabel="MAE (0–100)", xlabel="Kriteria")
    fig.tight_layout()
    fig.savefig(run_dir / "per_criterion.png", metadata={"Software": None})
    plt.close(fig)


def fmt(x, nd=3):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def render(run, metrics, per_criterion, icc, recon, audit, b2_note, n):
    lines = [f"# Evaluation — run {run['run_id']}", ""]
    if run["include_synthetic"]:
        lines += ["> **SYNTHETIC DATA — not real results.** This run includes data/synthetic answers.", ""]
    if not run["params_frozen"]:
        lines += ["> Parameters were not frozen when this run was made (allowed only for synthetic demos).", ""]
    p = run["params"]
    lines += [f"Mode: {run['mode']} · reasoner: {run['reasoner']} · test answers: {n} · "
              f"τh = {p['tau_h']}, τl = {p['tau_l']}, δ = {p['delta']}, λ = {p['lambda']}", "",
              "## Score agreement (test split)", "",
              "| System | n | Pearson r (p) | Spearman ρ (p) | MAE | RMSE |", "|---|---|---|---|---|---|"]
    for m in metrics.itertuples():
        lines.append(f"| {m.system} | {m.n} | {fmt(m.pearson_r)} ({fmt(m.pearson_p)}) | "
                     f"{fmt(m.spearman_rho)} ({fmt(m.spearman_p)}) | {fmt(m.MAE, 2)} | {fmt(m.RMSE, 2)} |")
    if b2_note:
        lines += ["", f"_{b2_note}_"]
    lines += ["", f"Per-question rows: `outputs/reports/{run['run_id']}/metrics_per_question.csv`.", "",
              "## Per-criterion error (system ledger vs lecturer criterion score)", "",
              "| Criterion | MAE |", "|---|---|"]
    lines += [f"| {c} | {v:.2f} |" for c, v in per_criterion.items()] or \
        ["| – | no per-criterion human scores in this run (holistic scores only) |"]
    lines += ["", "## Inter-rater agreement", "",
              f"ICC(2,1) on totals: {fmt(icc[0])} (n = {icc[1]})" if icc else "Only one rater (or fewer than 3 shared answers): not computed.",
              "", "## Audit metrics", ""]
    for key, label in (("EP", "Evidence precision"), ("ER", "Evidence recall"), ("FF", "Feedback faithfulness")):
        lines.append(f"- {label} ({key}): {fmt(audit[key][0])} (n = {audit[key][1]})" if key in audit
                     else f"- {label} ({key}): pending — no evidence audit imported for this run (`audit-template`, then `audit-import`)")
    lines += ["", "## Sanity check", "",
              f"Reconstruction rate (SPARQL score = Python score): {recon:.0%}. This holds by design and is not a finding.",
              "", f"Figures: `outputs/reports/{run['run_id']}/scatter.png`, `per_criterion.png`."]
    return "\n".join(lines) + "\n"


def audit_template(run_id):
    rows = []
    for a in db.run_scores(run_id).answer_id:
        r = db.result(run_id, a)
        sentences = {sid: text for sid, text in r["sentences"]}
        for e in (LedgerEntry(**x) for x in r["ledger"]):
            rows.append({"row_type": "ledger", "run_id": run_id, "answer_id": a, "entry_id": e.entry_id,
                         "reference_id": e.reference_id, "status": e.status,
                         "quoted_sentences": " ".join(sentences.get(s, "") for s in e.sentence_ids),
                         "present_in_answer": "", "evidence_correct": ""})
        for i, c in enumerate(r["feedback"]["claims"], 1):
            rows.append({"row_type": "claim", "run_id": run_id, "answer_id": a, "claim_index": i, "text": c["text"],
                         "ledger_entry_ids": " ".join(c["ledger_entry_ids"]), "supported": ""})
    out = report_dir(run_id) / "evidence_audit_template.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=db.AUDIT_COLUMNS).to_csv(out, index=False)
    return out
