# Datasets for AutoGrade-RDF (English and Indonesian)

Two public short-answer datasets, converted to the app's import formats. They live outside `data/`, so `db import` never touches them; everything is loaded through the app (Kelas page or its API).

| Folder | Language | Source | Questions | Answers | Human scores |
|---|---|---|---|---|---|
| `en_mohler_cs/` | English | Mohler et al. 2011, CS data structures [1] | 12 of 80 | 343 (75 pilot, 268 test) | 2 graders, 0–5 → `_total` 0–100 |
| `id_ukara/` | Indonesian | UKARA 1.0 Challenge Track 1 [2], [3] | 2 (Task A, B) | 2,860 (573 pilot, 459 dev, 1,828 test) | binary label → `_total` 0 or 100 |

Each folder also has a small `demo` split (72 EN answers, 20 ID answers, all taken from `test`) for a quick, cheap trial: every imported answer is graded through the LLM, so the full sets cost thousands of API calls.

## What is real and what is drafted

| Part | Mohler (EN) | UKARA (ID) |
|---|---|---|
| `question.md` | dataset | dataset (stimulus + question from the coding-guideline file) |
| `reference_answer.md` | dataset | **drafted by Claude** from the guideline's Label 1 (the dataset has none) |
| `rubric.yaml` criteria | **drafted by Claude** | **drafted by Claude** from the coding guideline |
| `gold.yaml` (concepts, aliases, `skos:broader`, triples) | **drafted by Claude** | **drafted by Claude** |
| Student answers | dataset | dataset |
| Human scores | dataset | dataset |

Every `gold.yaml` has `validated_by: null`. As with the earlier SAF subset (see `docs/DECISIONS.md`), these keys are a demonstration until a lecturer reviews them, and they must not be used for the gold-mode ablation. Aliases were written from the reference answers, the coding guidelines and a reading of **pilot** answers only; test answers were not used.

## File formats (as the app expects them)

- `questions/<QID>/` holds the four files of `data/questions/Q1`. `rubric.yaml` sets `language: en` or `language: id`, which picks the extraction prompt and predicate list.
- `answers_<split>.csv` is a **wide** LMS table: `student_id`, then one column per question id. Each row is one answer, so the other question columns are blank. The app skips blanks and counts them, so the preview shows a large "blank" number. That is expected.
- `scores_<split>.csv`: `student_id`, then one column per question and rater, named `<QID>__<rater>`. Values are 0–100.
  - Mohler: raters `G1` and `G2` are the dataset's two graders (`score_me` and `score_other` in the source file). Each is imported as its own rater, so `evaluate` averages them and reports ICC. The dataset's average is not imported, which would count the graders twice.
  - UKARA: rater `UKARA` (label 1 → 100, label 0 → 0).
- Student ids are unique per answer (`MOH-<question>-<nn>`, UKARA's `RES_ID`). The mirror does not say which student wrote which answer, so the ids don't link answers across questions. The final grades CSV therefore has one row per answer.

Split mapping:

- Mohler has no official split. Every 5th answer per question goes to `pilot` and the rest to `test`.
- UKARA keeps its own splits: `train` → `answers_pilot.csv`, `dev` → `answers_dev.csv`, `test` → `answers_test.csv`. Import dev as split *test*, or leave it out.

Dropped rows:

- 1 Mohler answer whose text is the spreadsheet artefact `#NAME?` (the original text is lost in the mirror).
- 1 blank UKARA test answer.

## Before importing UKARA: two new Indonesian predicates

The Indonesian vocabulary had only `menggunakan`, `menyerap`, `mengonsumsi` and `menghasilkan`, which can't express "refugees *face* a challenge" or "a reason *causes* the donation". This change adds two relations and records the decision in `docs/DECISIONS.md`:

- `menghadapi` (aliases: mengalami, menemui, berhadapan dengan, menanggung)
- `menyebabkan` (aliases: mengakibatkan, menimbulkan, memicu, mendorong, berakibat pada)

Both are added to `ontology/build_ontology.py` and `config/predicates.yaml`, and `ontology/autograde.owl` is regenerated. The regenerated file was checked first: it is identical to the old one except for the two new `ag:Relation` individuals. Restart the app after pulling this change; it reloads `urn:ag:ontology` when the OWL file changes. Without the change, uploading `ID_UKARA_A`/`B` fails with `unknown predicate`.

## Import through the app (Kelas page)

1. **Kelas** → add a course (e.g. `MOHLER-EN`) and an assessment.
2. Upload a question: select the four files of one `questions/<QID>/` folder. Repeat for each question.
3. **Impor Jawaban** → upload `answers_demo.csv` (or `pilot` / `test`).
   - Student id column: `student_id`. Layout: wide.
   - Each question's column is picked automatically, because the column names are the question ids.
   - Choose the split: *pilot* for `answers_pilot.csv`, *test* otherwise.
   - *Periksa*, then *Impor*.
4. **Nilai dosen** → for each question:
   - Upload the matching `scores_<split>.csv`.
   - Set the rater id (`G1`, then `G2`; or `UKARA`).
   - Map *Total* to the column `<QID>__<rater>`.
   - Only rows for that question have a value; the others are skipped.

Step 4 means 24 imports for Mohler. `import_datasets.py` does steps 1–4 through the same API (standard library only, app running):

```bash
python datasets/import_datasets.py datasets/en_mohler_cs --split demo
python datasets/import_datasets.py datasets/id_ukara --split demo
# full sets
python datasets/import_datasets.py datasets/en_mohler_cs --split pilot --split test
python datasets/import_datasets.py datasets/id_ukara --split pilot --split test
```

It is safe to re-run: existing questions and answers are skipped, and a rater's scores are replaced.

**Checked:** every split of both folders was imported into a fresh database through the running API with this script. All 14 questions passed the app's validation, and every answer and score was accepted.

## How the keys were designed, and known misfits

**Either/or rubrics use `skos:broader`.**
- Both UKARA questions accept *any one* of several reasons, but the score is a weighted sum.
- The key therefore has one triple whose object is a general concept: `TantanganPengungsi` for A, `AlasanBerdonasi` for B. The accepted specific ideas are narrower concepts (`KesulitanAdaptasi`, `MasalahEkonomi`, `EmosiDonatur`, …).
- A narrower concept counts as the key concept itself (DECISIONS, concept hierarchy), so naming one challenge earns 100.
- Mohler 12.9 (successor *or* predecessor) uses the accepted-subjects list instead.

**Vague answers may be over-credited.** A student who only writes "tantangan" is an unknown concept. It may embed close to `TantanganPengungsi` and get partial credit, while the guideline labels such answers 0.

**The UKARA stimulus doesn't match the answers.** The guideline files describe a *Waterworld* scenario (A) and a self-service shop with Rp50.000 shirts (B). Many answers instead mention "Travina" and climate refugees (A), or "a vending machine in Berlin selling a 2-Euro T-shirt" and "pakaian beretika" (B).
- So students probably saw a different stimulus text than the one shipped with the data.
- `question.md` uses the shipped text. Replace it if you find the original.

**UKARA labels are noisy.** Septiandri et al. relabelled 73 of the 573 training answers after finding them inconsistent [2]. These files use the official labels.

**Mohler scores lean high.**
- Selected-question means are 67–93 out of 100.
- Correlation between the two graders ranges from 0.37 (3.6) to 0.98 (8.1).
- Questions were chosen because their reference answers can be written as triples with the existing English predicates. They are not a random sample.

**Predicate near-misses (seen before with SAF):**
- 7.7 "uses more memory" vs the key's `requires`.
- 7.3 "linked lists only allow sequential access" vs `LinkedList requires Traversal`.

**Implicit subjects.** Many answers drop the subject, e.g. "a node with no children", "beradaptasi dengan lingkungan baru". Pronoun aliases such as "both", "they" and "mereka" help only when the extractor keeps them.

## Sources

[1] M. Mohler, R. Bunescu, and R. Mihalcea, "Learning to grade short answer questions using semantic similarity measures and dependency graph alignments," in *Proc. 49th Annu. Meeting Assoc. Comput. Linguistics: Human Lang. Technol.*, 2011, pp. 752–762. [Online]. Available: https://aclanthology.org/P11-1076/

[2] A. A. Septiandri, Y. A. Winatmoko, and I. F. Putra, "Knowing right from wrong: Should we use more complex models for automatic short-answer scoring in Bahasa Indonesia?," in *Proc. SustaiNLP: Workshop Simple Efficient Natural Lang. Process.*, Nov. 2020, pp. 1–7. [Online]. Available: https://aclanthology.org/2020.sustainlp-1.1/

[3] UGM NLP Group, "UKARA 1.0 Challenge." [Online]. Available: https://nlp.mipa.ugm.ac.id/ukara-1-0-challenge/

[4] A. A. Septiandri, "ukara," GitHub repository (data files `Data A/`, `Data B/` used here; MIT licence covers the repository). [Online]. Available: https://github.com/aliakbars/ukara

[5] gsasikiran, "Comparative-Evaluation-of-Pretrained-Transfer-Learning-Models-on-ASAG," GitHub repository, file `comparative_evaluation_on_mohler_dataset/dataset/mohler_dataset_edited.csv` (a merged version of Mohler v2.0 edited by T. Metzler, per the repository README; GPL-3.0 covers the repository). [Online]. Available: https://github.com/gsasikiran/Comparative-Evaluation-of-Pretrained-Transfer-Learning-Models-on-ASAG

[6] CATALPA, "Datasets for automatic scoring of educational text data." [Online]. Available: https://catalpa-cl.github.io/EduScoringDatasets/

**Licences.**
- Neither dataset states a data licence in the copies used here. Both are research benchmarks, distributed for research (Mohler v2.0 by R. Mihalcea's group; UKARA by the UGM NLP group with PUSPENDIK), used in published work and redistributed by others [4], [5], [6].
- Cite the original papers in the article: Mohler et al. [1] for the English set; Septiandri et al. [2] and the challenge page [3] for UKARA.
- The original Mohler download (`web.eecs.umich.edu/~mihalcea/downloads.html`) could not be reached from this environment, so the mirror [5] was used.
