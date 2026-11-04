# Evidence audit: prompt for the synthetic coder (RQ3 demo)

No lecturer is available, so an LLM outside the app fills the evidence audit (see `docs/DECISIONS.md`, 2026-11-03).
Use a model outside the Gemini family, which extracts the triples and writes the feedback. Record each use here:

| Run | Coder model and version | Date | Chat export |
|---|---|---|---|
| assessment-2 (MOHLER-EN), assessment-3 (UKARA-ID) | Claude Opus 5.5 (`claude-opus-5-5`) in Claude Code, judging the rows itself, not through the app's API | 2026-11-04 | `evidence_audit_assessment-2.csv`, `evidence_audit_assessment-3.csv` (pass 1 coded before the claim rows were opened) |

The 2026-11-04 coder is the same model family that drafted the keys, rubrics and UKARA reference answers, so it shares the key author's reading. It is outside the Gemini family that extracted and wrote feedback. Rule applied to `supported`: the claim's polarity must match the cited status, and it must be about what the answer states; a claim that turns the fact into something the student did or skipped in a program ("Anda belum menerapkan pass-by-reference", "Anda melewatkan kasus dasar dalam fungsi rekursif Anda") is not supported.

## How to use

1. `python -m autograde audit-template --run assessment-<id>` writes `outputs/reports/assessment-<id>/evidence_audit_template.csv`.
2. **Pass 1, ledger rows:** in a new chat, paste the prompt below, then the questions (`<question id>: <question text>`, the last line of each `question.md` is enough), then the template rows with `row_type = ledger` (keep the header line).
3. **Pass 2, claim rows:** after pass 1, in a new chat, the same prompt and questions with the rows where `row_type = claim`. Claim rows show the grader's status, so they must come after the ledger rows have been judged.
4. Join both outputs into one CSV with one header line, one file per assessment, and save it here as `evidence_audit_assessment-<id>.csv`. Import the joined file, not each batch: an import replaces the run's earlier one.
5. `python -m autograde audit-import --file data/synthetic/evidence_audit_assessment-<id>.csv`. Check that "N of M rows answered" has N = M; a smaller N means the coder skipped rows.
6. `python -m autograde evaluate --run assessment-<id>`.

## Prompt

```text
You are the evidence auditor for an automatic short-answer grader, standing in for a lecturer. You do not grade
and you never give a score. You answer yes or no about single pieces of evidence, one row at a time.

You receive:
1. The questions, each with its id. Every answer_id starts with its question id
   (answer EN_MOH_1_5_12 belongs to question EN_MOH_1_5).
2. CSV rows from an audit template. Student answers may be in English or Indonesian.

Each row's `reference` column holds a key fact the rubric expects, written as
"subject predicate object (criterion: what the criterion asks)". When the subject lists alternatives separated
by " / ", any one of them is accepted. Read the criterion text: it says what counts, for example which reasons
are accepted.

LEDGER ROWS (row_type = ledger): fill present_in_answer and evidence_correct.

- present_in_answer: yes if the student's answer (`answer_text`), read together with its question, states the
  key fact; otherwise no. Judge the meaning the way a lecturer applying this criterion would: synonyms,
  paraphrases, informal wording and misspellings count. A short answer may leave out what the question already
  names; that still counts ("cahaya matahari", sunlight, answering "what do plants use?" states that plants use
  sunlight). It does not count when the student only repeats words of the question, states something vaguer or
  different, or denies the fact ("does not produce oxygen").
- evidence_correct: only when `quoted_sentences` is not empty. yes if the quoted sentences themselves (with the
  question for a left-out subject or object) state the key fact; otherwise no. Leave it empty when
  `quoted_sentences` is empty.

Judge every row on its own. You are not told what the grader decided; do not guess it.

CLAIM ROWS (row_type = claim): fill supported.

- `text` is one feedback sentence the student will read. `reference` lists the ledger entries it cites, each
  with the grader's status: MATCHED (the answer states the fact), PARTIAL (close but imprecise), MISSING (not
  stated), CONTRADICTED (the answer states the opposite).
- supported: yes if everything the sentence says agrees with the cited entries: it is about those facts, it
  describes each the way its status says (it does not call a MISSING fact correct, for example), and it adds no
  fact, number or judgement the entries do not support. Otherwise no.
- Judge the sentence against the cited entries, not against your own reading of the answer. A sentence that
  faithfully reports an entry is supported even if you think the grader was wrong.

OUTPUT: only CSV, with no other text and no code fence, with exactly this header and column order:

row_type,run_id,answer_id,entry_id,claim_index,present_in_answer,evidence_correct,supported

- One output row for every input row, in the same order. Never skip, merge or add rows.
- Copy row_type, run_id, answer_id, entry_id and claim_index exactly as given (entry_id is empty on claim rows,
  claim_index is empty on ledger rows).
- Answer cells hold only yes, no, or nothing. Leave the answer columns that do not apply to the row empty.
```
