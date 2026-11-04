# Decisions

Agent Rule 2: formula changes need a human decision recorded here. Newest last.

## 2026-10-21 — Formulas (refinements of deck slides 3.4)

1. **SWRL/embedding split.** SWRL cannot compute embeddings, so Python asserts `ag:alignedSubject` and `ag:alignedObject` only for pairs with σ ≥ τ_h. Pellet then infers `ag:contradicts` with Rules 1–3. Mention this in the article.
2. **Negation.** Eq. 3 gives no credit to a negated triple. Eq. 5 marks a contradiction for an incompatible predicate that is *not* negated, or for an equivalent predicate that *is* negated. "Fotosintesis tidak menghasilkan CO2" is a correct statement and is not a contradiction. Python asserts `ag:negated` on every student triple, because under the open-world assumption a missing value never satisfies `negated(?t, false)`.
3. **sim.** Two *known* concepts with different ids score 0.0, with no embedding fallback; this stops Oksigen vs CO2 from earning credit. Embeddings are used only when at least one side is not in the alias table.
4. **Accepted subjects.** A gold triple lists the subjects it accepts (`s: [Fotosintesis, Tumbuhan]`), and σ uses the best one. The lecturer decides the list per triple.
5. **Equivalence lives in the ontology only.** `predicates.yaml` aliases only normalize surface wording. `menyerap` is its own `ag:Relation` with `menyerap equivalentPredicate menggunakan`, as on deck slide 3.2.

## 2026-10-21 — Parameters

- Initial values: τ_h = 0.80, τ_l = 0.60, δ = 0.5, λ = 0.0. λ = 0.5 is reported as a variant row.
- **δ and λ are fixed, not tuned.** Only τ_h and τ_l are searched (12 grid points with τ_l < τ_h). Reason: with a pilot of a few answers per question, tuning four parameters would overfit.
- Calibration is **global**: one search over the pooled pilot answers of all questions, in LLM mode, minimizing MAE against lecturer totals. `frozen.yaml` is written once and never overwritten.
- Calibration uses the SPARQL reasoner rather than Pellet, for speed (12 grid points × answers). The two are parity-tested on 10 crafted cases (`tests/test_reason.py`).

## 2026-10-21 — Implementation

- **LLM:** Claude Opus 5.5 (`claude-opus-5-5`) through the Anthropic SDK with JSON-schema structured output, at effort `medium`. **This model does not accept a temperature parameter**, so plan Rule 7's "temperature 0" cannot be applied. Determinism comes from the response cache, keyed by (provider, model, effort, schema, system prompt, user prompt). Anthropic's server-side refusal fallback (`fallbacks: "default"`) is enabled.
- **Java:** Owlready2 0.51's bundled Pellet needs Java 25 (class-file version 69). A Temurin 25 JRE is installed in `~/.local/share/jdk/`, and `io.java_exe()` finds it (or use `JAVA_EXE` / `JAVA_HOME`). Homebrew's `openjdk` install was blocked by a symlink another tool owns.
- **Starter ontology:** `ontology/build_ontology.py` generates `autograde.owl` (RDF/XML) from plan Section 6. A human checks and refines it in Protégé. Once it has been edited in Protégé, do not re-run the script, because it overwrites the file.
- **Ledger RDF:** statuses are `ag:Status` individuals (`ag:Cocok`, `ag:Parsial`, `ag:Hilang`, `ag:Kontradiksi`); code and JSON use the English enum. IRIs carry the question id (`ag:Q1_R5`, `ag:L_Q1_A07_R5`).
- **Lecturer corrections** (deck slide 1.4): `data/human/overrides.yaml` → `python -m autograde override`. This writes `ledger_corrected.*` and `score_corrected.json`; the original ledger is never changed. Corrected scores are never used in `evaluate`.
- **Synthetic data** lives in `data/synthetic/` (deck answers A07/A08 plus five invented answers, a single invented rater). Reports that include it are stamped "SYNTHETIC DATA — not real results".

## 2026-10-21 — SAF subset and demo app

- **SAF subset** (Filighera et al. 2022, English, CC-BY-4.0), imported by `scripts/import_saf.py` into `data/external/saf/`: 5 questions, 150 answers (SAF validation → pilot, SAF test_unseen_answers → test; SAF train not imported). It is loaded only with `--saf`.
  - The 5 questions are DHCP, piggybacking, async/sync transmission, data-link service classes, and CSMA/CD diameter. They were chosen for spread of scores and relation-like reference answers.
  - **The gold triples, rubrics and the 15 triple annotations for SAF were drafted by Claude (AI), not by a lecturer or a human annotator.** Every file says so. They are for the demo only and must not be used for the gold-mode ablation.
  - SAF scores are holistic points (max 1 for these questions), stored as `criterion = _total`. So SAF has no per-criterion errors.
- **English predicates** (`lang: en` in `predicates.yaml`) with ontology relations `utilizes ≡ uses`, `enables ≡ allows`, `provides ≡ assigns`, and `has ⊥ lacks`, `allows ⊥ prevents`, `decreases ⊥ increases`. Extraction prompts, examples and the predicate enum follow each question's `rubric.yaml` `language`.
- **Either/or reference answers can't be expressed.** SAF piggybacking allows "duplex connection OR acknowledgement field", so its gold has only the duplex triple.
- **Embedding labels:** known concept ids are embedded as words (`LowTransmissionRate` → "low transmission rate"), not the run-together id.
- `answer.ttl` now also stores the reasoner's input (`ag:alignedSubject` / `ag:alignedObject`) and output (`ag:contradicts`), so the reasoning can be inspected and queried with SPARQL.
- The demo app's SPARQL console is read-only and refuses `SERVICE` (federated queries to remote endpoints).

## 2026-10-21 — SAF subset extended to 18 questions (demonstration)

- 13 more SAF questions imported (549 answers in total), each with a rubric and gold key **drafted by Claude as a demonstration, not lecturer-validated**. The 8 questions that can't be written as fixed triples were skipped (see `data/external/saf/README.md`).
- SAF scores are now divided by each question's maximum (0.5–3.5 points), not assumed to be out of 1.
- New English predicates `causes`, `determines`, `follows`, `precedes`, `reduces`; new incompatible pairs causes ⊥ prevents, follows ⊥ precedes. `increases`/`decreases` cover both senses ("cwnd increases" and "slow start increases cwnd"), because students use the same verb for both. The alias "reduces" moved from `decreases` to the new `reduces`.
- Known misfits, kept on purpose to show the method's limits:
  - **"Any two of three reasons"** (SAF_ENC): the key lists all three, so a correct answer can lose points.
  - **Rates** (SAF_TCP1/2): triples say *that* cwnd grows, not *how fast* (exponential vs linear).
  - **Implicit subjects**: many answers never name the topic ("we need a duplex operation"), so the subject goes unmatched.
- **Some aliases were added after reading pilot-split answers only.** The keyword check afterwards showed pilot coverage improving but unseen test answers barely changing (SAF_DUP: 20 of 23 test answers still match no key concept). Exact alias lists don't keep up with paraphrase, which is why LLM extraction and the embedding step matter.

### Offline grading of the extended SAF subset (same day)

- 40 more AI-drafted annotations (55 in total, about 3 answers per question), following the rules in `data/external/saf/README.md`, including filling in subjects the question implies (marked `# implied subject`).
- Fixed after reading real answers: merged `increments`/`lowers` back into `increases`/`decreases` (students use the same verbs), frame bursting's disadvantage uses `requires`, bridges accept "bridge" as subject. Pilot-derived aliases added for TCP, DUPMETH, DQDB, IPv6 and Poisson.
- Gold-mode result on the 32 annotated test answers (AI-drafted keys and annotations, so a demonstration only): Pearson r 0.61, Spearman ρ 0.66, MAE 34.2. The keyword baseline scores r 0.64, MAE 28.8.
- Failure patterns seen, useful for the article's discussion:
  - near-synonym predicates count as different: *avoids* vs *reduces*, *minimizes* vs *prevents*, *requires* vs *causes*;
  - typos and long paraphrases fall below τl ("the playload", "the source of the received packet");
  - an unknown wrong concept can earn partial credit by embedding ("character oriented encoding" vs Binary Encoding);
  - SAF graders accept reasons the key doesn't list (e.g. "duplicates waste bandwidth" scored full marks).

## 2026-10-21 — Separate namespaces and a concept hierarchy

- **Namespaces.** Schema and data no longer share one namespace:
  - `ag:` = `http://example.org/autograde/ontology#`: classes, properties, the predicate vocabulary, status values;
  - `key:` = `http://example.org/autograde/key/`: the lecturer's data (concepts, key facts, rubric criteria);
  - `ans:` = `http://example.org/autograde/answer/`: student data (answers, sentences, student facts, ledger entries).

  Criteria now include the question id (`key:Q1_K2_Produk`), since criterion names repeat across questions.
- **Concept hierarchy (formula change to §4 `sim`).** `gold.yaml` concepts may list `broader:` concepts, written to `gold.ttl` as `skos:broader` (W3C SKOS). For two known concepts, sim(key, student) is:
  - 1.0 if they are the same, or the student's concept is narrower (more specific) than the key's;
  - `broader_similarity` = 0.70 if the student's concept is broader (more general) than the key's (partial credit, flagged for review);
  - 0.0 otherwise.

  The hierarchy is transitive (`skos:broader+`). 0.70 lies in the partial band for every calibration grid point, and grading refuses to run if it doesn't.
- **Q1 hierarchy (demonstration, to confirm with the lecturer):** Glukosa → Makanan, Oksigen → Gas, CO2 → Gas, Cahaya → Energi. With it, the deck's answer A07 scores 70 with the real embedding model, through a link the lecturer wrote. (Before, it scored 60, because cos(makanan, glukosa) = 0.36.)
- A broader concept never aligns for the reasoner (0.70 < τh), so a vague answer can't trigger a contradiction.

## Open — needs a human decision

- ~~The deck's partial-credit example does not hold with the chosen embedding model~~: resolved by the concept hierarchy (see the namespaces and hierarchy entry above).
- **Unknown concept vs gold concept** compares against the concept's id label only ("glukosa"), not its aliases ("gula", cos 0.541). Taking the max over id and aliases is a candidate change to `sim`.

## 2026-10-24 — SAF dataset dropped

- The SAF subset (data, AI-drafted keys and annotations, import script, tests) is removed; a better dataset will replace it. The only bundled data is Q1 with its synthetic answers.
- Kept because they are generic: holistic `_total` human scores, `language: en` rubrics, English extraction prompts, `lang: en` predicates and the English ontology relations.
- The two open questions about SAF (pronoun subjects, SAF in the article) no longer apply.

## 2026-10-24 — Database storage (sub-project 1 of 4)

- Records (courses, questions with rubric and gold key as JSON, answers, human scores, runs, results, overrides, evidence audit) live in SQLite; every RDF graph lives in an embedded Oxigraph store as a named graph (`urn:ag:ontology`, `urn:ag:gold:<qid>`, `urn:ag:run:<run>:<answer>:{answer|ledger|ledger_corrected}`). Spec: `docs/superpowers/specs/2026-10-24-persistence-foundation-design.md`.
- The SPARQL recompute now reads the ledger and gold graphs back from the store, so it audits what was persisted.
- Oxigraph stores decimals canonically (`"2.0"` comes back as `"2"`); scores are unaffected because SPARQL compares numeric values.
- Runs are resumable: re-running a run id skips answers that already have a result row. Evaluation figures go to `outputs/reports/<run>/`; the report text is stored with the run.

## 2026-10-24 — Course workflow in the app (sub-projects 2–4)

- Courses, assessments, questions (upload or Editor Soal), LMS answer import, class grading, review and export happen in the app. Specs: `docs/superpowers/specs/2026-10-24-{courses-and-import,question-authoring,grading-review-export}-design.md`.
- The database now holds data that exists nowhere else, so schema changes are upgraded in place (`db.UPGRADES`, schema version 2) instead of asking for `db import --replace`.
- One grading run per assessment (`assessment-<id>`, mode `auto`: gold extraction for hand-annotated answers, LLM otherwise). Lecturer corrections are re-applied after a re-grade when their reference triple still exists. Corrected scores still never feed `evaluate`.
- Corrected answers get template feedback rebuilt from the corrected ledger in the export, because the stored feedback quotes the original score.

## 2026-10-28 — Public datasets for the app (`datasets/`)

- Two importable datasets, kept outside `data/` so `db import` never reads them; loaded through the Kelas page or `datasets/import_datasets.py`; `serve` loads both `demo` splits at every start, so a demo opens with data. Details and citations: `datasets/README.md`.
  - **English:** 12 of the 80 questions of Mohler et al. (2011), CS data structures, 343 answers, two graders (0–5 → `_total` 0–100, raters G1 and G2). Chosen because the reference answers can be written as triples with the existing English predicates. No official split: every 5th answer per question is pilot.
  - **Indonesian:** UKARA 1.0 Track 1, Tasks A and B, 2,860 answers, binary labels (→ 0/100, rater UKARA). Official splits kept (train → pilot, dev, test).
- **Rubrics and gold keys were drafted by Claude (AI), not by a lecturer**, as were the UKARA reference answers (the dataset has none; drafted from the coding guideline's Label 1). `validated_by: null` everywhere. Demonstration only until reviewed; not for the gold-mode ablation.
- **New Indonesian relations `menghadapi` and `menyebabkan`** (`build_ontology.py`, `predicates.yaml`, `autograde.owl` regenerated; the regenerated file was identical to the previous one before the change). The four Q1 predicates can't express UKARA's "pengungsi menghadapi tantangan" or "alasan menyebabkan donasi". No equivalences or incompatibilities added. Validate with the lecturer.
- **Either/or rubrics through `skos:broader`:** UKARA accepts any one reason, so each key has one triple whose object is a general concept (`TantanganPengungsi`, `AlasanBerdonasi`) and the accepted reasons are narrower concepts, which count as the key concept itself. Mohler 12.9 (successor or predecessor) uses the accepted-subjects list.
- Known misfits: the UKARA guideline stimulus differs from what students saw (answers mention "Travina" and a 2-Euro T-shirt vending machine in Berlin); UKARA labels are noisy (Septiandri et al. 2020 relabelled 73 of 573 training answers); vague answers may get partial credit by embedding.

## 2026-10-28 — LLM through OpenRouter (Gemini 2.5 Flash)

- All LLM calls (extraction, feedback, baseline B2) go through OpenRouter (`llm.provider: openrouter`, key `OPENROUTER_API_KEY`), model `google/gemini-2.5-flash`; Gemini 2.5 Pro and DeepSeek V4 are one config line away. Replaces the Claude Opus 5.5 entry above; `provider: anthropic` still works.
- JSON-schema structured output (`strict`), with `provider.require_parameters` so OpenRouter only routes to providers that enforce it, and `data_collection: deny` so student answers never go to providers that store or train on prompts. Temperature 0 is sent (plan Rule 7 applies again); reasoning effort `medium`. The response cache is keyed by provider and model, so earlier Claude responses are not reused.
- **Extraction decides scores**, so results from runs with Claude and with Gemini are not comparable; report which model graded each run.
- `provider: gemini` (key `GEMINI_API_KEY`, model `gemini-3.8-flash`) calls Google AI Studio directly, for a demo on its free tier. The free tier may use prompts to improve Google's products, so `data_collection: deny` does not hold there: demo data only, never real student answers. No temperature is sent (Gemini 3.6+ ignores it). When its quota runs out or the model is overloaded (still 429 or 503 after the retries), that call and every call in the next 60 s go to `llm.fallback` (OpenRouter, `google/gemini-3.1-flash-lite`), cached under the fallback model, so one run can mix models; each cached response in `outputs/cache/llm/` names its provider and model.

## 2026-11-03 — Production grading (advisor allows LLM-drafted keys)

- **Extraction may take one part of a triple from the question.** Fragment answers ("beradaptasi sama lingkungan baru") name no subject, so extraction found nothing and every graded UKARA demo answer scored 0, including ones the lecturers scored 100. The extractor now gets the question, and the grounding check accepts the subject *or* the object (never both) from the question's words; the other must still come from the student's sentences. "The question" is the prompt's last line only, not the stimulus above it: ID_UKARA_B's stimulus names the expected reason ("kondisi kerja di dalam sebuah pabrik konveksi"), so with the whole prompt the reason-free answer "karena ingin berdonasi" passed grounding as (kondisi kerja pabrik konveksi, menyebabkan, berdonasi) and scored 100. Rule 1 holds: the score is still Equation (6) over the knowledge graph. On the 20 UKARA demo answers, "beradaptasi sama lingkungan baru" now scores 100 (human 100) and "bencana linkungan" 0 (human 0). Runs before this change are not comparable with runs after it (the extraction prompt changed, so the LLM cache misses).
- **Alias containment (user decision, 2026-11-03; changes sim's input, Section 4).** A student phrase that is not exactly an alias now gets the concept whose alias appears in it as whole words (stopwords ignored): the earliest alias wins, as the head of the phrase, then the longest at that position. On the 92 demo answers, longest-first and earliest-first differ on one answer ("data structure that moves elements in last in first out": longest-first picks LIFO and scores 0, earliest-first picks DataStructure, 33.3); the demo answers come from the test split, so re-check on pilot. Measured on the same extracted triples (exact -> containment): UKARA demo, pass/fail agreement with the lecturers 9 -> 12 of 20, Pearson r 0.19 -> 0.41; Mohler demo, 19 -> 22 of 72, r 0.22 -> 0.26, MAE 66.4 -> 60.7; no new false passes. Scores stay far below the lecturers' (Mohler mean 20.9 vs 80.5): the drafted keys and exact predicates are strict. "adaptasi terhadap lingkungan baru" -> KesulitanAdaptasi. Before, it had no concept and fell to embedding similarity against the concept *label*, which stayed below tau_l. Exact matches still come first. Known risk: a generic alias ("data", "memory") inside a longer phrase now names that concept, so keys should avoid one-word generic aliases. The worked example (A07) scores the same. `config/frozen.yaml` does not exist yet, so no calibration is invalidated; calibrate after this change.
- **Extraction schema lists predicate ids only, not their aliases.** Gemini 2.5 (the OpenRouter fallback) rejects the English enum of 104 values (ids + aliases) as "too much branching", so every English answer failed once Gemini's own quota ran out. The prompt still lists each id's aliases; the parser still maps an alias to its id.
- **LLM-drafted keys stand in for lecturer-written ones** (research advisor, for the demo, because of time). The question editor's "Draft the key with the LLM" button fills criteria, concepts (aliases, skos:broader) and key triples from the question and reference answer, with one retry carrying the validator's errors. Nothing is saved until the lecturer saves; `validated_by` stays empty, so the question page still says the key is not validated.
- LLM feedback is on by default on the assessment page; the new "Grades and feedback" table shows, per answer, the final score, the feedback and whether the LLM or the template wrote it.
- **RQ3 runs in demo mode with a synthetic coder** (no lecturer is available). An LLM outside the app, not the Gemini family that extracts and writes feedback, fills the evidence audit; the filled file goes in `data/synthetic/` with the model, date and prompt, and the article names the coder. The coder never decides a score (Rule 1); it answers yes/no per audit row.
  - The audit template is **blind**: ledger rows leave out the system's `status` (plan Phase 9 listed it), so "is this fact in the answer?" is judged without the system's verdict. Each row carries the whole answer and the key fact in words with its criterion; a claim row lists its cited entries with their status, since a claim can't be judged without it.
  - `audit-import` reads only `present_in_answer`, `evidence_correct` and `supported`, matches each row to the run's ledger, takes every other field from the ledger, accepts only yes / no / blank, names every row it can't read, and replaces the run's earlier import (before, a second import counted every row twice, and "ya" counted as no).
  - **First audit (2026-11-04), coder Claude Opus 5.5** at the user's request, the same model family that drafted the keys (so it shares the key author's reading). Demo assessments graded once, every call by `openrouter/google/gemini-3.1-flash-lite` (the Gemini free tier was out of quota). Mohler (72 answers): EP 0.978 (n 45), ER 0.489 (n 90), FF 0.810 (n 126); UKARA (20): EP 1.000 (n 4), ER 0.308 (n 13), FF 1.000 (n 20). All 24 unsupported claims are Mohler feedback that turns a fact into a program action ("Anda belum menerapkan pass-by-reference", "Anda melewatkan kasus dasar dalam fungsi rekursif Anda"), two of them on MATCHED entries. Files and prompt: `data/synthetic/`.
  - **Known issue, left for now (user, 2026-11-04):** feedback is always written in Indonesian (`feedback.SYSTEM` says so), so the English Mohler answers get Indonesian feedback; it should follow the question's language. The audit above judged the Indonesian feedback.
  - The report stamp now says "A demonstration run: k of n answers are synthetic, and its evidence audit, if any, may come from a synthetic (LLM) coder": assessment runs are always marked synthetic, even when every answer is real.
- The Gemini free tier may use prompts to train Google's models, so the earlier rule stands: real student answers need `provider: openrouter` (with `data_collection: deny`) or a paid Gemini key, not the free tier.
- **ID_UKARA_B aliases rebuilt from the labelled pilot answers** (phrases counted in accepted vs rejected answers; dev and test not used). The lecturers accept reasons tied to the stimulus (working conditions, wages, ethical production, concern for the workers) and reject generic charity reasons about as often as they accept them, so `pahala`, `amal`, "helping the needy" and "fast fashion" were dropped and the stimulus vocabulary widened. Share of answers naming a reason (accepted / rejected), held-out dev: 57% / 28% -> 63% / 32%. Then the bare generic words `kondisi`, `keadaan`, `layak`, `sadar`, `produksi`, `memproduksi` were dropped, since alias containment let them name a reason inside any phrase ("sadar ingin pahala", "bajunya layak pakai", "kondisi keuangan" -> KesadaranKondisiKerja, full credit): dev 62% / 29%. The labels are noisy (the same text is rejected in pilot and accepted in the demo set), and many answers still fail on the extraction's triple *shape* (e.g. buyer as subject instead of the reason), which no alias can fix.
- **OpenRouter fallback model: `google/gemini-3.1-flash-lite`** instead of `gemini-2.5-flash-lite`. OpenRouter serves 2.5-flash-lite only from Google AI Studio, whose shared limits failed many demo calls (429 upstream, 400 "User location is not supported"); 3.1-flash-lite is also served by Google Vertex, so OpenRouter can switch provider. About 2.5x the price ($0.25 / $1.50 per million tokens in / out). One live call checked: it accepts the extraction schema and extracted UKARA B demo answer TSB629 as (reason, menyebabkan, donasi), 100 like the lecturers.
