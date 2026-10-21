# SAF subset (real answers, third-party)

Source: *Short Answer Feedback* dataset, communication networks, English —
A. Filighera, S. Parihar, T. Steuer, T. Meuser, S. Ochs, "Your Answer is Incorrect... Would you like to know why?
Introducing a Bilingual Short Answer Feedback Dataset", ACL 2022.
https://huggingface.co/datasets/Short-Answer-Feedback/saf_communication_networks_english — licence CC-BY-4.0.

- `raw/`: the downloaded parquet files and dataset card, unchanged.
- `answers.csv`, `scores.csv`: 18 of SAF's questions, 549 answers. SAF validation → our pilot split, SAF
  test_unseen_answers → test; the SAF train split (1,700 answers) is not imported.
  SAF scores are points with different maxima per question (0.5 to 3.5). Each score is stored as
  `score_0_100 = 100 × score ÷ the question's maximum`, where the maximum is the highest score given for that question
  in any split. They are holistic, so `criterion = _total`.
- Not imported (8 questions): figure-based (RPB packet list), calculations (coin flips, queueing), an open design
  question (MAC procedure), address ranges (Class A), and "name any k of n" lists (IPv6 objectives, mobile routing
  challenges, UDP vs TCP headers). A key of fixed triples cannot express those.
- `annotations/`: hand-written student triples for a few answers so they can be graded offline (gold mode).
  **Drafted by an AI (Claude), not checked by a human.** Do not use them for the gold-mode ablation.
- Gold triples in `data/questions/SAF_*/gold.yaml` are also **AI-drafted and not lecturer-validated**.
