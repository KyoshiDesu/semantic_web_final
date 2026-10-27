# AutoGrade-RDF

Auditable short-answer scoring for Indonesian answers. The score is a published formula over a ledger of RDF triple matches weighted by the lecturer's rubric; SWRL (Pellet) detects limited contradictions; an LLM only writes feedback from the ledger. See `PROTOTYPE_PLAN.md` (single source of truth) and `docs/DECISIONS.md`.

## Setup

```bash
# conda keeps the env outside ~/Documents, so iCloud sync can't hide files inside it.
conda create -n semantic_web python=3.12 pip && conda activate semantic_web
pip install -r requirements.txt -e .
cp .env.example .env          # add ANTHROPIC_API_KEY for LLM extraction, feedback and baseline B2
```

Pellet needs **Java 25+** (Owlready2 0.51). It is looked up in `JAVA_EXE`, `JAVA_HOME`, `~/.local/share/jdk/*`, then `PATH`. Without Java, set `reasoner: sparql` in `config/config.yaml`.

## Run

```bash
pytest                                             # all tests, offline (they build their own temp database)
python -m autograde db import                      # once: data/ -> db/autograde.sqlite + db/kg/ (Oxigraph)
python -m autograde gold --question Q1             # re-validate a key -> named graph urn:ag:gold:Q1 + docs/gold_Q1_review.md
python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback   # offline demo
python -m autograde evaluate --run <run_id>        # report saved with the run; figures in outputs/reports/<run_id>/
streamlit run app/streamlit_app.py
```

Storage: everything lives in `db/` (SQLite for records, an Oxigraph triple store with one named graph per document). Set `AUTOGRADE_DB_DIR` to keep it elsewhere. `data/` is only read by `db import`; re-import with `db import --replace` after editing files there. **`--replace` deletes everything entered in the app** (courses, questions, imported answers, grades, reviews); download questions from Editor Soal and the grade exports first. Older databases are upgraded in place on first use. A run can be resumed with `run ... --run-id <id>`. Lecturer corrections: `override --run <id> --file overrides.yaml`; evidence audit: `audit-template --run <id>`, fill the CSV, then `audit-import --file <csv>`.

A real course is set up in the app (sidebar section **Data**). On **Mata Kuliah**, add a course and an assessment, then upload a question's four files in the format of `data/questions/Q1` (`question.md`, `reference_answer.md`, `rubric.yaml`, `gold.yaml`). Questions can also be written on **Editor Soal**: the question text, reference answer, rubric criteria, concepts (aliases and the `skos:broader` hierarchy) and gold triples, in editable tables with dropdowns for predicates, concepts and criteria. A live preview shows the concept graph, the reified RDF and the Turtle of `urn:ag:gold:<qid>`, and validation errors block saving. Any question can be edited later; if it already has graded results, they are kept but stale until re-graded. **Unduh berkas** downloads the four files as a zip for backup or git. On **Impor Jawaban**, upload the LMS export as CSV and map its columns: the student id, the name(s), and one answer column per question (or a question column and an answer column for one-row-per-answer exports). Answers get the id `<question>_<student id>`. Blank answers and Moodle's `-` are skipped, and answers that are already imported are never replaced. The **Nilai dosen** tab imports your own 0–100 scores the same way. Imported answers have no triple annotations, so grade them in LLM mode.

Grading a class happens on **Penilaian** (sidebar section **Penilaian Kelas**): pick the assessment and grade every answer with a progress bar. Grading is resumable, and answers with a hand annotation use it while the rest go through the LLM. Then review. One button approves every answer with no ⚑ and no contradiction. Flagged answers are opened one by one, where a ledger status can be corrected with a reason; the score is recomputed and checked with SPARQL. Finally, export. The final grades CSV (one row per student, a column per question and the mean) and the feedback CSV unlock only when every answer is reviewed; drafts are always available. Editing a question's key marks its graded answers *usang* until they are re-graded.

## Open in Protégé

The API exports one graded answer or a whole run as an OWL file: `GET /api/export/owl?run=<run>[&answer=<answer>]`. An assessment's run is `assessment-<id>`. The file holds the ontology and its SWRL rules, each question's key, every answer's student triples with their sentences (`prov:wasDerivedFrom`) and the reasoner's input (`alignedSubject`/`alignedObject`), and the ledger (the corrected one when you made corrections). The app's own `ag:contradicts` inferences are left out, so the reasoner derives them again.

1. *File → Open* the `.owl` file.
2. *Reasoner → HermiT*, then *Reasoner → Start reasoner*.
3. Under *Individuals*, pick a student triple of an answer with a contradiction: the inferred `contradicts` link shows in yellow.
4. *DL Query* tab: `LedgerEntry and status value Hilang` lists every missing reference triple; `ReferenceTriple and criterion value Q1_K1_Bahan` lists the triples of one criterion.

Full command list: plan Section 8. Before import, real data goes in `data/answers/answers.csv`, `data/human/scores.csv` (per criterion), `data/annotations/` (gold mode) and `data/human/evidence_audit.csv` / `overrides.yaml`. `data/synthetic/` is demo data only.
