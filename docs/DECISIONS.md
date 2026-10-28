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

- Two importable datasets, kept outside `data/` so `db import` never reads them; loaded through the Kelas page or `datasets/import_datasets.py`. Details and citations: `datasets/README.md`.
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
