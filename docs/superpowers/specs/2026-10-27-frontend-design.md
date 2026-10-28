# Frontend (phase 2, part 2 of 4): design

Date: 2026-10-27. Status: decisions made in brainstorming, pending spec review. Builds on the API backend (`2026-10-27-api-backend-design.md`, part 1), whose phase 2 section sets the order of the four parts.

## Goal

Every feature of the Streamlit app as plain HTML/CSS/vanilla JS pages in `web/`, served by `python -m autograde serve` next to the API, in Indonesian and English, with an original look. Streamlit is deleted at the end of this part, once browser tests cover every page.

Decisions from brainstorming:

- **Pages by object, not by tool.** A short top nav (Beranda · Kelas · Soal · Semantic Web ▾ · Evaluasi). Import, grading, review and export live on one page per assessment; every "Jelajahi relasi semantik" link opens one page per answer that holds all of its RDF views.
- **Home shaped like the lecturer's example**: a hero naming each Semantic Web piece, quick-demo chips, a search box, and one card per student answer.
- **Visual direction "Skema graf"**: a technical schematic. Graph paper, monospace RDF names, one colour per namespace, cards that show a triple (Section 4).
- **One HTML file per page** with shared ES modules. No build step, no router, no framework.
- **Playwright browser tests** replace `tests/test_app.py`.
- **Indonesian and English UI**, switchable in the nav (Section 3).

## Scope

In scope:

- The pages, shared modules, stylesheet and translations in `web/`; vendored vis-network, Graphviz (WebAssembly) and marked.
- Two API additions, a `lang` parameter on three endpoints, and a Content-Security-Policy on the pages (Sections 1, 3, 6).
- Small core changes: the graph palette, language-neutral DOT labels, English column keys for the properties table (Sections 3, 4).
- Playwright tests and their `live_server` fixture.
- Deleting Streamlit, `app/` and `tests/test_app.py`; README walkthrough rewritten.

Out of scope:

- Dark mode, phone layouts, logins, editing the ontology, starting research runs from the UI, delete or rename actions.
- Translating content: question and answer text, the student feedback (written in Indonesian by design), the evaluation report, the CSV exports, comments inside SPARQL templates.
- The dataset and subject-agnostic keys (parts 3 and 4).

## 1. Architecture

`python -m autograde serve` already serves `web/` at `/` and the API at `/api` from one origin; nothing changes there. The UI is desktop-first and works down to tablet width.

### Pages

| File | Page | Holds |
|---|---|---|
| `index.html` | Beranda | Hero, quick demos, answer search and cards |
| `kelas.html?course=` | Kelas | Courses, assessments, students, question upload, LMS CSV import |
| `penilaian.html?id=` | Penilaian | One assessment: status, grading job, bulk review, exports |
| `soal.html`, `soal.html?id=` | Soal | Question list; one question's key, editor and answers |
| `jawaban.html?run=&answer=` | Jawaban | One graded answer: score, SPARQL check, ledger, graphs, reasoning, RDF, SPARQL, OWL export, review |
| `ontologi.html` | Ontologi | The `ag:` ontology |
| `graf.html?name=` | Graf Pengetahuan | Named graphs of the Oxigraph store |
| `jelajah.html?question=&run=&answers=` | Penjelajah Graf | One question's knowledge graph with chosen answers |
| `sparql.html?graphs=&template=` | Konsol SPARQL | Editor, scope, templates, results |
| `evaluasi.html?run=` | Evaluasi | Research runs, reports, figures |

The query string holds the page's state and the hash holds the open tab (`jawaban.html?run=assessment-1&answer=Q1_A08#penalaran`), so every view can be linked, reloaded and bookmarked.

### Shared code

| File | Job |
|---|---|
| `web/css/app.css` | The visual system (Section 4) |
| `web/js/api.js` | `get`, `post`, `put`, `form`; JSON or text out; `ApiError {status, error, message, details}`; 503 retry |
| `web/js/i18n.js` | Loads `web/i18n/<lang>.json`; `t(key, vars)`; fills `[data-i18n]` elements; the language switch |
| `web/js/ui.js` | `el()` DOM builder, nav, tables, tabs, status and IRI chips, triple chips, editable table, toasts, error panel |
| `web/js/graph.js` | vis-network graphs (legend toggles, details panel; the drawing code of `explorer.html()` moves here) and DOT to SVG with Graphviz |
| `web/js/<page>.js` | One module per page |
| `web/vendor/` | vis-network 9.1.9 (moved from `app/static/`), `@viz-js/viz` 3.31.0 (`viz-standalone.mjs`, Graphviz in WebAssembly), marked 18.1.1, each with its licence file |

### API additions

- `GET /answers?q=&filter=&limit=30`: answers of every assessment for the home search. `q` matches answer text, answer id, student id and name, question id and prompt. `filter` is one of `contradiction`, `flagged`, `corrected`, `ungraded`. Each row: `answer_id, question_id, assessment_id, run_id, external_id, name, status, score, final, flagged, contradictions, corrected, text` and `triple` (`{s, p, o, negated, contradicts}`: a contradicting student triple if any, else the first matched one, else null).
- `GET /assessments/{id}/status` also returns `assessment`, `course` and `job` (the assessment's latest job or null, from a new `db.latest_job(assessment_id)`), so a reload during grading picks the progress back up.
- `lang=id|en` on three endpoints (Section 3).

## 2. Pages

**Beranda.** A hero line on what the app does and six chips (RDF, OWL, SWRL, SKOS, PROV, SPARQL), each linking to where that piece is visible: the named graphs, the ontology, its SWRL rules tab, a question's concept graph, an answer's sentences, the SPARQL console. Quick demos are filter chips (*ada kontradiksi*, *perlu ditinjau ⚑*, *dikoreksi dosen*, *belum dinilai*) and two SPARQL template chips ("Jumlah triple per named graph" and "Hitung ulang skor tiap jawaban (Pers. 6) dari graf tersimpan") that open `sparql.html` with the query loaded. The search calls `GET /answers` and shows at most 30 cards; typing narrows them. Each card shows `ans:<id>`, the score, the question and student, its highlight triple, and a left rail in its status colour. A graded answer links "jelajahi relasi semantik ↗" to its answer page; an ungraded one links to its assessment.

**Kelas.** A course list with an add-course form. The selected course shows its assessments (linking to Penilaian), an add-assessment form, the question upload (the four files, into a chosen assessment) and the students table. The import has tabs *Jawaban* and *Nilai dosen*, each in three steps: choose the CSV and see its columns and first five rows; map the columns (student id, names, per question an answer column or a question column plus value; or for scores, criterion or total to column, and the rater); *Periksa* runs the dry run and shows the report, *Impor* writes it.

**Penilaian.** Course, assessment and run id, and a chip per status count. *Nilai jawaban baru (n)* and *Nilai ulang yang usang (n)* with an "umpan balik LLM" checkbox start a job. A progress bar shows done of total, the current answer and failures; *Batalkan* cancels it. The status table links each row to its answer page. *Setujui semua yang aman (n)* approves the answers with no ⚑ and no contradiction. Final grade and feedback CSVs are disabled with the reason shown until every answer is reviewed; drafts are always available. The reviewer name is asked for once, kept in `localStorage` and shown in the nav as *Peninjau: DS*, where it can be changed.

**Soal.** The list shows each question's prompt, language, assessment, answer and result counts, and *Soal baru*. One question has three tabs:

- *Kunci*: prompt, reference answer, criteria with weights, reference triples as triple chips, concepts with aliases and `skos:broader`, the concept and reified-RDF graphs, the Turtle of `urn:ag:gold:<qid>`, and *Unduh berkas (.zip)*.
- *Editor*: prompt, reference answer, language, *validated by*, and editable tables for criteria, concepts (aliases; `broader` picked from the concepts) and triples (subject from the concepts, predicate from `/predicates?lang`, object from the concepts, criterion, weight), with add and remove row. A preview debounced to half a second shows the errors, or the concept graph, reified RDF, Turtle and YAML. *Simpan* is disabled while the draft is invalid and reports how many answers became *usang*. *Salin sebagai soal baru* and *Soal baru* open the same editor with an id and assessment picker.
- *Jawaban*: the question's answers with the lecturer's totals. *Coba nilai* grades one in the UI run (gold mode when annotated, else LLM), and a text box grades a pasted answer. The result shows inline (score, B1 keyword baseline, link to the answer page).

**Jawaban.** `ans:<id>`, its question and run, the score in large type, the corrected score and the status. A SPARQL check box shows the Python score beside the SPARQL recompute score with ✓, and expands to the query and its rows. Tabs:

- *Ledger & umpan balik*: ledger rows (reference triple, status, credit, ⚑, evidence sentences), the corrected ledger, the feedback, and the sentences with their ids (the PROV sources of the student triples).
- *Graf interaktif*: vis-network with legend toggles and a details panel.
- *Penyelarasan*: the alignment graph.
- *Penalaran*: the σ table, aligned pairs, contradictions, the Pellet before and after graphs, the extraction log.
- *RDF (Turtle)*: the gold, answer and ledger graphs (and the corrected ledger), each downloadable.
- *SPARQL*: the console limited to this answer's graphs, with the answer templates.

An OWL download link exports the answer for Protégé. When the answer is in an assessment run, graded, up to date and not yet reviewed, each ledger row gets a status dropdown and a reason; *Simpan koreksi* shows the new score and its SPARQL check, *Tandai ditinjau* reviews it, and *Berikutnya yang perlu ditinjau →* opens the next *dinilai* answer of that assessment. A stale answer shows a banner linking to Penilaian.

**Semantic Web.**

- *Ontologi*: counts; tabs for the class hierarchy, the properties table, predicates and relations (with an all / id / en filter), the SWRL rules, the OWL file.
- *Graf Pengetahuan*: named graphs grouped by kind with triple counts; the chosen graph's Turtle, interactive view (noting truncation) and a triple table (a SPARQL `SELECT` over that graph).
- *Penjelajah Graf*: pick a question, a run and its answers; one graph with legend toggles and details.
- *Konsol SPARQL*: a monospace editor (Ctrl+Enter runs it), scope (whole store or chosen named graphs), templates by scope, a results table or Turtle, the parser's error shown inline.

**Evaluasi.** The runs table; the chosen run's parameters, rendered report and figures.

## 3. Languages

Indonesian is the default. An `ID | EN` switch in the nav stores the choice in `localStorage`, sets `<html lang>` and reloads the page.

- **UI text** lives in `web/i18n/id.json` and `web/i18n/en.json` (same keys). HTML marks static text with `data-i18n`; JS uses `t(key)`.
- **The API returns keys, not labels**, wherever the browser shows a label, and the browser translates them: table columns through `col.<name>` (falling back to the name itself), graph legend types through `node.<type>` and `edge.<type>`, grading statuses through `status.<value>` (*belum dinilai*, *usang*, *dinilai*, *ditinjau* stay the core's values). `rdfviz.properties_table` gets English column keys (`property, kind, domain, range, characteristics`) for this.
- **Text the browser can't translate** is made language-neutral or chosen by `lang`:
  - DOT graphs use RDF names only. The alignment graph's two cluster labels become `ag:StudentTriple` and `ag:ReferenceTriple`.
  - `explorer.build(..., lang="id")` takes the language for its details (kinds and field names); `GET /results/{run}/{answer}/views/graph` and `GET /questions/{qid}/explorer` pass `?lang=`.
  - `GET /sparql/templates?scope=&lang=` returns English titles when `lang=en`, from an id-to-en title map next to the templates in `rdfviz`.
- **Error headings** come from the API's `error` code in the UI language; the API's message and details (English) are shown below as they are.
- **Content keeps its own language** (see Out of scope).

## 4. Visual system: "Skema graf"

- **Page**: `#fbfcfd` with a 16 px `#e9eef4` grid. Panels, cards and tables are white with a 1 px `#16202e` border. No shadows, no rounded corners.
- **Type**: prose in `"Avenir Next", "Helvetica Neue", system-ui, sans-serif`; IRIs, ids, scores, Turtle and SPARQL in `"SF Mono", Menlo, ui-monospace, monospace`. System fonts only, so the app works offline.
- **Namespace colours**: `key:` `#1d4ed8`, `ans:` `#6d28d9`, `ag:` `#b45309`, `skos:` `#047857`, `prov:` `#0e7490`, rdf/owl/rdfs ink. All pass WCAG AA on white.
- **Ledger statuses**: `rdfviz.STATUS_COLOR`, as in the DOT graphs. **Grading statuses**: *belum dinilai* grey, *usang* amber, *dinilai* blue, *ditinjau* green.
- **Graph palette**: `explorer.NODE_TYPES`/`EDGE_TYPES` and `rdfviz.VIS_NODE_TYPES`/`VIS_EDGE_TYPES` change to these colours, so the interactive graphs match the pages.
- **Components**: a white bordered nav with an `ag:AutoGrade` mono wordmark, the active item inverted, *Semantic Web ▾*, the language switch and *Peninjau* on the right. IRI tokens (`key:Q1_R2`) in mono with namespace-coloured text and border. Triple chips `[s] —p→ [o]` (`—NOT p→` when negated), with `⟂ ag:contradicts key:…` in red below a contradicting one. Cards with a 5 px status rail. Status chips in small uppercase mono. Tables with mono ids and numbers, a sticky header and an ink rule under it. Tabs as a bordered segmented row, active inverted. Buttons: primary filled ink, secondary white with an ink border, destructive red border; a disabled button shows its reason as visible text. Graph panels with a grid background and legend toggle chips. The error panel has a red rail, the message and the details list.
- **Accessibility**: semantic HTML (`nav`, `main`, `table`, `button`), a 2 px `#1d4ed8` focus outline, keyboard-operable tabs, `aria-live` on job progress and toasts.

## 5. Data flow and errors

- Downloads (CSV, zip, Turtle, OWL) are `<a download>` links to the GET endpoints. Uploads check the 10 MB limit in the browser, then send `FormData`; the server's 413 still applies.
- The editor preview ignores a response that arrives after a newer request. Job progress polls `GET /jobs/{id}` once a second while the job runs and reloads the status table when it ends.
- A page whose main data fails to load shows the error panel instead of its content, with a link home; an unknown id in the URL shows *tidak ditemukan* / *not found*. A failed action shows the panel next to its form or button, with validation details beside the fields.
- 503: `api.js` retries up to 3 times, waiting `Retry-After` seconds, then reports that the knowledge graph is in use (probably by the CLI). A failed `fetch` (server stopped) says to run `python -m autograde serve`.
- `localStorage` (reviewer name, language) is read and written inside `try`; when it is unavailable, the app asks again or uses Indonesian.

## 6. Security

Student text appears on almost every page, so escaping is the main risk.

- Pages are built with `ui.el(tag, attrs, ...children)`, which sets text through `textContent`. API data never goes into `innerHTML`.
- Graphviz SVG comes from DOT whose labels `rdfviz.esc` escapes, and Graphviz writes them as SVG text. vis-network tooltips and the details panel are text only.
- The evaluation report is rendered with `marked`, with raw HTML in the Markdown escaped by a renderer override.
- A Content-Security-Policy on responses from the `web/` mount: `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:`. `/docs` and `/api` are left without it (Swagger UI loads from a CDN).
- Part 1's checks stay: same-origin writes (the pages' own `fetch` sends a matching `Origin`), the trusted-host check, read-only SPARQL.

## 7. Testing

- `playwright` and `pytest-playwright` pinned in `requirements.txt`; Chromium installed once with `playwright install chromium` (README). Browser tests carry a `browser` marker and are skipped when Chromium is missing, as Pellet tests are without Java.
- A `live_server` fixture runs uvicorn in a thread on a free port, one server per test module, on a fresh import of the demo data with the `client` fixture's offline setup (stub embeddings, SPARQL reasoner, no API key, context cache reset).
- **Every page**, in both languages: loads with no console errors and no failed requests, shows its key content (an SVG class graph on Ontologi, a score and content in each tab on Jawaban), and shows no raw translation key.
- **Class flow**: create a course and assessment, upload question files, import a `;`-separated CSV (check, then import), grade and see the job reach done, bulk approve, correct the contradicted entry (new score with the SPARQL ✓), review the rest, download the final grades CSV.
- **Editor**: a change updates the preview; an invalid predicate shows errors and disables *Simpan*; saving marks graded answers *usang*.
- **Semantic Web**: home search with *ada kontradiksi* leads to a card, the answer page and its tabs; a SPARQL template runs and a typo shows the parser's message; an explorer legend toggle hides its nodes; the OWL link downloads.
- **Escaping**: an answer containing `<img src=x onerror=…>` shows as text on the home card, the answer page and the explorer details, with no `img` element created.
- **pytest without a browser**: `id.json` and `en.json` have the same keys; every `data-i18n` and `t("…")` key used in `web/` exists; API tests for `GET /answers`, the new status fields, the `lang` parameters and the CSP header.
- Every existing test keeps passing until Section 8 deletes `test_app.py`.

## 8. Removing Streamlit

The last task, once every browser test passes:

- Delete `app/` (`streamlit_app.py`, `manage.py`, `grading.py`, `static/`), `tests/test_app.py`, and `explorer.html()` with its template and `VIS_JS`.
- Remove `streamlit` and the pins only it needed (checked with `pip`) from `requirements.txt`; drop `app` from pytest's `pythonpath`; drop the `embeddings` marker (only `test_app.py` uses it).
- README: the web app walkthrough replaces the Streamlit one (Kelas, Penilaian, Soal, Jawaban, the Semantic Web menu, the language switch), plus the Playwright setup.

## Build order

1. Foundation: vendored libraries, `app.css`, `api.js`, `i18n.js`, `ui.js`, `graph.js`, the nav, the CSP, the palette and language-neutral DOT labels, `live_server` with one smoke test.
2. API additions and the `lang` parameters.
3. Pages: Jawaban (the other pages link to it and it uses the most components), Penilaian, Kelas, Soal with the editor, Beranda, then Ontologi, Graf Pengetahuan, Penjelajah Graf, Konsol SPARQL, then Evaluasi.
4. Removing Streamlit and the README.
