# AutoGrade-RDF

Auditable short-answer scoring for Indonesian answers. The score is a published formula over a ledger of RDF triple matches weighted by the lecturer's rubric; SWRL (Pellet) detects limited contradictions; an LLM only writes feedback from the ledger. See `PROTOTYPE_PLAN.md` (single source of truth) and `docs/DECISIONS.md`.

## Setup

```bash
# conda keeps the env outside ~/Documents, so iCloud sync can't hide files inside it.
conda create -n semantic_web python=3.12 pip && conda activate semantic_web
pip install -r requirements.txt -e .
playwright install chromium   # once: the browser tests drive Chromium
cp .env.example .env          # add ANTHROPIC_API_KEY for LLM extraction, feedback and baseline B2
```

Pellet needs **Java 25+** (Owlready2 0.51). It is looked up in `JAVA_EXE`, `JAVA_HOME`, `~/.local/share/jdk/*`, then `PATH`. Without Java, set `reasoner: sparql` in `config/config.yaml`.

## Run

`./run.sh` (macOS, Linux) or `.\run.ps1` (Windows PowerShell) starts the app on http://127.0.0.1:8000: the API and the web pages are one server. On the first start it imports `data/` into an empty database. A port can be given: `./run.sh 8080`, `.\run.ps1 -Port 8080`. If Windows blocks the script, run `powershell -ExecutionPolicy Bypass -File .\run.ps1`.

```bash
pytest                                             # all tests, offline (they build their own temp database)
python -m autograde db import                      # once: data/ -> db/autograde.sqlite + db/kg/ (Oxigraph)
python -m autograde gold --question Q1             # re-validate a key -> named graph urn:ag:gold:Q1 + docs/gold_Q1_review.md
python -m autograde run --question Q1 --mode gold --split all --synthetic --template-feedback   # offline demo
python -m autograde evaluate --run <run_id>        # report saved with the run; figures in outputs/reports/<run_id>/
python -m autograde serve                          # the app on http://127.0.0.1:8000 (API docs at /docs)
```

Storage: everything lives in `db/` (SQLite for records, an Oxigraph triple store with one named graph per document). Set `AUTOGRADE_DB_DIR` to keep it elsewhere. `data/` is only read by `db import`; re-import with `db import --replace` after editing files there. **`--replace` deletes everything entered in the app** (courses, questions, imported answers, grades, reviews); download each question (Soal → Kunci → Unduh berkas) and the grade exports first. Older databases are upgraded in place on first use. A run can be resumed with `run ... --run-id <id>`. Lecturer corrections: `override --run <id> --file overrides.yaml`; evidence audit: `audit-template --run <id>`, fill the CSV, then `audit-import --file <csv>`.

A real course is set up in the app. On **Kelas**, add a course and an assessment, then upload a question's four files in the format of `data/questions/Q1` (`question.md`, `reference_answer.md`, `rubric.yaml`, `gold.yaml`), or write one on **Soal → Soal baru**: the question text, reference answer, rubric criteria, concepts (aliases and the `skos:broader` hierarchy) and reference triples, in editable tables with dropdowns for predicates, concepts and criteria. A live preview shows the concept graph, the reified RDF, the Turtle of `urn:ag:gold:<qid>` and the YAML; validation errors block saving. Any question can be edited later on its *Editor* tab; graded results are kept but stale until re-graded. *Unduh berkas (.zip)* on the *Kunci* tab downloads the four files for backup or git. Still on **Kelas**, import the LMS export as CSV and map its columns: the student id, the name(s), and one answer column per question (or a question column and an answer column for one-row-per-answer exports). *Periksa* shows what would be imported, *Impor* writes it. Answers get the id `<question>_<student id>`. Blank answers and Moodle's `-` are skipped, and answers that are already imported are never replaced. The *Nilai dosen* tab imports your own 0–100 scores the same way. Imported answers have no triple annotations, so they are graded through the LLM (needs `ANTHROPIC_API_KEY`).

Grading a class happens on the assessment's page (click it on **Kelas**). *Nilai jawaban baru* grades every answer in the background with a progress bar; closing the browser doesn't stop it, and a job cut off by a restart carries on where it stopped when started again. Answers with a hand annotation use it while the rest go through the LLM. Then review: one button approves every answer with no ⚑ and no contradiction. The others open on their own page from the table, where a ledger status can be corrected with a reason; the score is recomputed and checked with SPARQL, and *Berikutnya yang perlu ditinjau* moves on. Finally, export. The final grades CSV (one row per student, a column per question and the mean) and the feedback CSV unlock only when every answer is reviewed; drafts are always available. Editing a question's key marks its graded answers *usang* until they are re-graded.

Every answer page also shows its RDF side: the interactive graph, the alignment, the reasoning with Pellet's before and after, the Turtle of its named graphs, a SPARQL console and an OWL download for Protégé. The **Semantic Web** menu has the ontology, every named graph, the graph explorer and the SPARQL console with its templates. The home page names each Semantic Web piece and searches every answer. The top bar switches the interface between Indonesian and English and shows the reviewer's name, which the app asks for at the first review or correction.

## API

`python -m autograde serve` runs everything on `http://127.0.0.1:8000`: the JSON API under `/api` (try it at `/docs`) and the web pages from `web/`. It only listens on this machine and has no login. Writes from other web origins are refused. Grading an assessment runs in the background, one job at a time; closing the browser doesn't stop it, and a job cut off by a server restart is marked *interrupted* and carries on where it stopped when started again.

| Area | Endpoints |
|---|---|
| Courses | `GET/POST /courses`, `GET/POST /courses/{id}/assessments`, `GET /courses/{id}/students` |
| Questions | `GET /questions`, `GET /assessments/{id}/questions`, `GET /questions/{qid}`, `POST /questions`, `PUT /questions/{qid}`, `POST /questions/preview`, `POST /assessments/{id}/questions/upload`, `GET /questions/{qid}/files.zip`, `GET /predicates` |
| Imports | `POST /imports/preview`, `POST /courses/{id}/answers`, `POST /courses/{id}/scores` (CSV + a JSON column mapping, `?dry_run=true` to check first) |
| Grading | `GET /assessments/{id}/status`, `POST /assessments/{id}/grading`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /assessments/{id}/review/bulk`, `POST /results/{run}/{answer}/review`, `POST /results/{run}/{answer}/corrections`, `GET /assessments/{id}/exports/{grades,feedback}.csv` |
| Semantic Web | `GET /ontology`, `GET /graphs`, `GET /graphs/turtle?name=`, `GET /graphs/view?name=`, `POST /sparql`, `GET /sparql/templates`, `GET /questions/{qid}/gold`, `GET /questions/{qid}/answers`, `POST /questions/{qid}/try`, `GET /results/{run}/{answer}`, `GET /results/{run}/{answer}/views/{graph,alignment,reasoning}`, `GET /questions/{qid}/explorer`, `GET /export/owl` |
| Research (read-only) | `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/figures/{name}` |

## Open in Protégé

The API exports one graded answer or a whole run as an OWL file: `GET /api/export/owl?run=<run>[&answer=<answer>]`. An assessment's run is `assessment-<id>`. The file holds the ontology and its SWRL rules, each question's key, every answer's student triples with their sentences (`prov:wasDerivedFrom`) and the reasoner's input (`alignedSubject`/`alignedObject`), and the ledger (the corrected one when you made corrections). The app's own `ag:contradicts` inferences are left out, so the reasoner derives them again.

1. *File → Open* the `.owl` file.
2. *Reasoner → HermiT*, then *Reasoner → Start reasoner*.
3. Under *Individuals*, pick a student triple of an answer with a contradiction: the inferred `contradicts` link shows in yellow.
4. *DL Query* tab: `LedgerEntry and status value Hilang` lists every missing reference triple; `ReferenceTriple and criterion value Q1_K1_Bahan` lists the triples of one criterion.

Full command list: plan Section 8. Before import, real data goes in `data/answers/answers.csv`, `data/human/scores.csv` (per criterion), `data/annotations/` (gold mode) and `data/human/evidence_audit.csv` / `overrides.yaml`. `data/synthetic/` is demo data only.
