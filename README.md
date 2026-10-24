# AutoGrade-RDF

Auditable short-answer scoring for Indonesian answers. The score is a published formula over a ledger of RDF triple matches weighted by the lecturer's rubric; SWRL (Pellet) detects limited contradictions; an LLM only writes feedback from the ledger. See `PROTOTYPE_PLAN.md` (single source of truth) and `docs/DECISIONS.md`.

## Setup

```bash
# The project folder is synced by iCloud, which hides files inside a venv and breaks imports,
# so the venv lives outside ~/Documents and .venv is a symlink to it.
uv venv --python 3.12 ~/.venvs/semantic_web_final && ln -sfn ~/.venvs/semantic_web_final .venv
uv pip install --python .venv/bin/python -r requirements.txt -e .
cp .env.example .env          # add ANTHROPIC_API_KEY for LLM extraction, feedback and baseline B2
```

Pellet needs **Java 25+** (Owlready2 0.51). It is looked up in `JAVA_EXE`, `JAVA_HOME`, `~/.local/share/jdk/*`, then `PATH`. Without Java, set `reasoner: sparql` in `config/config.yaml`.

## Run

```bash
.venv/bin/pytest                                   # all tests, offline (they build their own temp database)
python -m autograde db import                      # once: data/ -> db/autograde.sqlite + db/kg/ (Oxigraph)
python -m autograde gold --question Q1             # re-validate a key -> named graph urn:ag:gold:Q1 + docs/gold_Q1_review.md
python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback   # offline demo
python -m autograde evaluate --run <run_id>        # report saved with the run; figures in outputs/reports/<run_id>/
streamlit run app/streamlit_app.py
```

Storage: everything lives in `db/` (SQLite for records, an Oxigraph triple store with one named graph per document). Set `AUTOGRADE_DB_DIR` to keep it elsewhere. `data/` is only read by `db import`; re-import with `db import --replace` after editing files there. A run can be resumed with `run ... --run-id <id>`. Lecturer corrections: `override --run <id> --file overrides.yaml`; evidence audit: `audit-template --run <id>`, fill the CSV, then `audit-import --file <csv>`.

Full command list: plan Section 8. Before import, real data goes in `data/answers/answers.csv`, `data/human/scores.csv` (per criterion), `data/annotations/` (gold mode) and `data/human/evidence_audit.csv` / `overrides.yaml`. `data/synthetic/` is demo data only.
