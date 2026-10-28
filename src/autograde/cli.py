"""python -m autograde <command> (plan Section 8)."""
import argparse
import sys

from autograde import io


def cmd_gold(args):
    from autograde import gold
    path, refs = gold.build(args.question)
    print(f"{len(refs)} reference triples -> named graph {path}\nreview table -> docs/gold_{args.question}_review.md")


def cmd_extract(args):
    from autograde import pipeline, segment
    answers = io.load_answers(args.synthetic)
    answers = answers[answers.question_id == args.question]
    if args.answers:
        answers = answers[answers.answer_id.isin(args.answers.split(","))]
    ctx = pipeline.Context.load(args.question)
    out = io.ROOT / "outputs" / "extract" / args.question / args.mode
    for a in answers.itertuples():
        students, log = pipeline.extract_triples(ctx, a.answer_id, segment.split(a.answer_id, a.text), args.mode)
        io.save_json([t.model_dump() for t in students], out / f"{a.answer_id}.json")
        print(f"{a.answer_id}: {len(students)} triples, {len(log)} dropped")


def cmd_run(args):
    from autograde import pipeline
    run_id = pipeline.run_split(args.question, args.mode, args.split, args.synthetic,
                                use_llm_feedback=not args.template_feedback, run_id=args.run_id)
    print(f"run -> {run_id}")


def cmd_calibrate(args):
    from autograde import calibrate
    print(f"frozen parameters -> {calibrate.calibrate(include_synthetic=args.synthetic, mode=args.mode)}")


def cmd_evaluate(args):
    from autograde import evaluate
    print(evaluate.evaluate(args.run, gold_run_id=args.gold_run))
    print(f"metrics and figures -> {evaluate.report_dir(args.run)}")


def cmd_audit_import(args):
    import pandas as pd
    from autograde import db
    df = pd.read_csv(args.file, dtype=str).fillna("")
    db.add_evidence_audit(df)
    print(f"{len(df)} evidence audit rows imported")


def _run_or_exit(run_id):
    from autograde import db
    run = db.run(run_id)
    if run is None:
        sys.exit(f"no run {run_id}")
    return run


def cmd_recompute(args):
    from autograde import db, kg, ledger
    run, res = _run_or_exit(args.run), db.result(args.run, args.answer)
    if res is None:
        sys.exit(f"{args.answer} is not in run {args.run}")
    sparql = ledger.recompute_sparql(kg.get_graph(kg.answer_graph_name(args.run, args.answer, "ledger")),
                                     kg.get_graph(kg.gold_graph_name(res["question_id"])), run["params"]["lambda"])
    stored = res["score"]["score"]
    ok = abs(sparql - stored) < 1e-9
    print(f"{args.answer}: SPARQL {sparql:.4f} | stored {stored:.4f} | {'OK' if ok else 'MISMATCH'}")
    sys.exit(0 if ok else 1)


def cmd_override(args):
    from autograde import db, pipeline
    _run_or_exit(args.run)
    if args.file:
        db.add_overrides(io.load_yaml(args.file) or [])
    for answer_id in sorted({o["answer_id"] for o in db.overrides()}):
        res = db.result(args.run, answer_id)
        if res is None:
            print(f"{answer_id}: not in run {args.run}, skipped")
            continue
        sc, skipped = pipeline.apply_corrections(args.run, answer_id)
        for o in skipped:
            print(f"{answer_id}: override for {o['reference_id']} skipped (not in the ledger)")
        if sc:
            print(f"{answer_id}: {res['score']['score']:.1f} -> {sc.score:.1f} (corrected)")


def cmd_audit_template(args):
    from autograde import evaluate
    print(f"audit template -> {evaluate.audit_template(args.run)}")


def cmd_db(args):
    from autograde import db, importer, kg
    if args.action == "init":
        db.connect(create=True).close()
        kg.sync_ontology()
        print(f"empty database -> {db.db_dir()}")
    else:
        print(f"imported {importer.import_files(replace=args.replace)} -> {db.db_dir()}")


def cmd_serve(args):
    import uvicorn

    from autograde.api.app import create_app
    print(f"AutoGrade-RDF on http://127.0.0.1:{args.port} (API docs: /docs)")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)  # local only: there is no login


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m autograde")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("gold", help="validate the question's gold key and write its named graph + review table")
    s.add_argument("--question", required=True)
    s.set_defaults(func=cmd_gold)
    s = sub.add_parser("extract", help="extract student triples only")
    s.add_argument("--question", required=True)
    s.add_argument("--mode", choices=["llm", "gold"], required=True)
    s.add_argument("--answers", help="comma-separated answer ids")
    s.add_argument("--synthetic", action="store_true", help="include synthetic (demo) answers")
    s.set_defaults(func=cmd_extract)
    s = sub.add_parser("run", help="grade answers and write a run")
    s.add_argument("--question", required=True, help="question id or 'all'")
    s.add_argument("--mode", choices=["llm", "gold"], required=True)
    s.add_argument("--split", choices=["pilot", "test", "all"], required=True)
    s.add_argument("--synthetic", action="store_true", help="include synthetic (demo) answers")
    s.add_argument("--template-feedback", action="store_true", help="skip the LLM for feedback")
    s.add_argument("--run-id", help="resume (or name) a run; graded answers are skipped")
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("calibrate", help="grid search on the pooled pilot split -> config/frozen.yaml")
    s.add_argument("--mode", choices=["llm", "gold"], default="llm")
    s.add_argument("--synthetic", action="store_true", help="demo only: writes outputs/synthetic/frozen.yaml")
    s.set_defaults(func=cmd_calibrate)
    s = sub.add_parser("evaluate", help="metrics for a test-split run")
    s.add_argument("--run", required=True)
    s.add_argument("--gold-run", help="gold-mode run of the same answers, for the ablation row")
    s.set_defaults(func=cmd_evaluate)
    s = sub.add_parser("recompute", help="SPARQL audit of one stored score")
    s.add_argument("--run", required=True)
    s.add_argument("--answer", required=True)
    s.set_defaults(func=cmd_recompute)
    s = sub.add_parser("override", help="apply the lecturer's overrides (optionally adding them from a YAML file) to a run")
    s.add_argument("--run", required=True)
    s.add_argument("--file", help="YAML list of overrides to add first (answer_id, reference_id, status, by, date, reason)")
    s.set_defaults(func=cmd_override)
    s = sub.add_parser("audit-template", help="blank evidence audit CSV for the lecturer (outputs/reports/<run>/)")
    s.add_argument("--run", required=True)
    s.set_defaults(func=cmd_audit_template)
    s = sub.add_parser("audit-import", help="import the lecturer's filled evidence audit CSV")
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_audit_import)
    s = sub.add_parser("db", help="create the database, or import data/ into it")
    s.add_argument("action", choices=["init", "import"])
    s.add_argument("--replace", action="store_true", help="rebuild a non-empty database from data/")
    s.set_defaults(func=cmd_db)
    s = sub.add_parser("serve", help="run the local API and web app on http://127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)
    args = p.parse_args(argv)
    if args.command not in ("db", "serve"):
        from autograde import db
        try:
            if db.is_empty():
                sys.exit("no questions in the database; run `python -m autograde db import`")
        except (db.NoDatabaseError, db.SchemaVersionError) as e:
            sys.exit(str(e))
    args.func(args)
