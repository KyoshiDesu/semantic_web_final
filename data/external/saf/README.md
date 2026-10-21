# SAF subset (real answers, third-party)

Source: *Short Answer Feedback* dataset, communication networks, English —
A. Filighera, S. Parihar, T. Steuer, T. Meuser, S. Ochs, "Your Answer is Incorrect... Would you like to know why?
Introducing a Bilingual Short Answer Feedback Dataset", ACL 2022.
https://huggingface.co/datasets/Short-Answer-Feedback/saf_communication_networks_english — licence CC-BY-4.0.

- `raw/`: the downloaded parquet files and dataset card, unchanged.
- `answers.csv`, `scores.csv`: 5 questions; SAF validation → our pilot split, SAF test_unseen_answers → test.
  SAF scores are holistic points (max 1 for these questions), stored as `criterion = _total`, `score_0_100 = 100 × score`.
- `annotations/`: hand-written student triples for a few answers so they can be graded offline (gold mode).
  **Drafted by an AI (Claude), not checked by a human.** Do not use them for the gold-mode ablation.
- Gold triples in `data/questions/SAF_*/gold.yaml` are also **AI-drafted and not lecturer-validated**.
