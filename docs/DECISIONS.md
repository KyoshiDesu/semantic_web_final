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

## Open — needs a human decision

- **Pronoun subjects.** Many SAF answers start "It is used to…". In LLM mode the grounding check keeps "it" as the subject, which doesn't match "DHCP". Options: resolve pronouns to the question's topic concept, or accept the miss. (The AI-drafted annotations keep the student's explicit subjects.)
- **SAF in the article.** The deck lists SAF as an optional comparison, pending the lecturer's approval. If it's used, the gold triples need a human review first.

- **The deck's partial-credit example does not hold with the chosen embedding model.** cos(makanan, glukosa) = 0.358 with `paraphrase-multilingual-MiniLM-L12-v2`, below τ_l, so A07 scores 60, not 70, on real embeddings. The test fixture stubs the value at 0.70, as the plan specifies. Options: add "makanan" as a lecturer alias, choose a different embedding model, or keep it as is and let calibration decide.
- **Unknown concept vs gold concept** compares against the concept's id label only ("glukosa"), not its aliases ("gula", cos 0.541). Taking the max over id and aliases is a candidate change to `sim`.
