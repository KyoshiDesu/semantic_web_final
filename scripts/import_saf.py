"""Import a 5-question subset of SAF (Short Answer Feedback, communication networks, English; CC-BY-4.0).

Reads the parquet files downloaded to data/external/saf/raw/ and writes
data/external/saf/answers.csv, scores.csv and data/questions/<id>/question.md, reference_answer.md.
Gold triples and rubrics for these questions are written by hand (see each gold.yaml).

    python -I scripts/import_saf.py
"""
import glob
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAF = ROOT / "data" / "external" / "saf"
QUESTIONS = {  # our question id -> unique text in the SAF question
    "SAF_DHCP": "Dynamic Host Configuration Protocol",
    "SAF_PIGGY": "piggybacking extension",
    "SAF_SYNC": "asynchronous and synchronous transmission",
    "SAF_DLL": "3 service classes the Data Link Layer",
    "SAF_CSMA": "collision domain diameter",
}
SPLITS = {"validation": ("pilot", "V"), "test_unseen_answers": ("test", "T")}  # SAF train is not imported
HEADER = "<!-- From SAF (Filighera et al., 2022), CC-BY-4.0. -->\n"


def main():
    frames = []
    for path in sorted(glob.glob(str(SAF / "raw" / "*.parquet"))):
        name = Path(path).name.split("-")[0]
        if name in SPLITS:
            frames.append(pd.read_parquet(path).assign(saf_split=name))
    df = pd.concat(frames, ignore_index=True)
    answers, scores = [], []
    for qid, key in QUESTIONS.items():
        sub = df[df.question.str.contains(key, regex=False)].sort_values(["saf_split", "id"])
        assert sub.question.nunique() == 1 and sub.reference_answer.nunique() == 1, qid
        assert sub.score.max() <= 1.0, f"{qid}: score above 1 point; normalize by the question's maximum"
        qdir = ROOT / "data" / "questions" / qid
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / "question.md").write_text(HEADER + sub.question.iloc[0].strip() + "\n", encoding="utf-8")
        (qdir / "reference_answer.md").write_text(HEADER + sub.reference_answer.iloc[0].strip() + "\n", encoding="utf-8")
        counters = {s: 0 for s in SPLITS}
        for r in sub.itertuples():
            counters[r.saf_split] += 1
            split, letter = SPLITS[r.saf_split]
            answer_id = f"{qid}_{letter}{counters[r.saf_split]:03d}"
            answers.append({"answer_id": answer_id, "question_id": qid, "text": r.provided_answer.strip(),
                            "split": split, "saf_id": r.id, "saf_feedback": r.answer_feedback.strip()})
            scores.append({"answer_id": answer_id, "rater_id": "SAF", "criterion": "_total",
                           "score_0_100": round(100 * r.score, 4)})
    pd.DataFrame(answers).to_csv(SAF / "answers.csv", index=False)
    pd.DataFrame(scores).to_csv(SAF / "scores.csv", index=False)
    print(pd.DataFrame(answers).groupby(["question_id", "split"]).size())


if __name__ == "__main__":
    main()
