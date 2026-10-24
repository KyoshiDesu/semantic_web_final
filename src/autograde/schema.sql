-- AutoGrade-RDF records (schema version 1, see db.SCHEMA_VERSION). Pipeline objects are stored as JSON text.
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE course (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE assessment (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES course(id),
                         name TEXT NOT NULL, UNIQUE (course_id, name));
CREATE TABLE question (id TEXT PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessment(id),
                       prompt TEXT NOT NULL, reference_answer TEXT NOT NULL,
                       rubric TEXT NOT NULL, gold TEXT NOT NULL);
CREATE TABLE student (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES course(id),
                      external_id TEXT NOT NULL, name TEXT, UNIQUE (course_id, external_id));
CREATE TABLE answer (id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES question(id),
                     student_id INTEGER REFERENCES student(id), text TEXT NOT NULL,
                     split TEXT NOT NULL CHECK (split IN ('pilot', 'test')),
                     source TEXT NOT NULL CHECK (source IN ('real', 'synthetic')), annotation TEXT);
CREATE TABLE human_score (answer_id TEXT NOT NULL REFERENCES answer(id), rater_id TEXT NOT NULL,
                          criterion TEXT NOT NULL, score_0_100 REAL NOT NULL,
                          PRIMARY KEY (answer_id, rater_id, criterion));
CREATE TABLE run (id TEXT PRIMARY KEY, mode TEXT NOT NULL, split TEXT NOT NULL, question TEXT NOT NULL,
                  params TEXT NOT NULL, params_frozen INTEGER NOT NULL, reasoner TEXT NOT NULL,
                  include_synthetic INTEGER NOT NULL, created TEXT NOT NULL, finished TEXT, evaluation_md TEXT);
-- answer_id has no foreign key: answers pasted into the app have no answer row.
CREATE TABLE result (run_id TEXT NOT NULL REFERENCES run(id), answer_id TEXT NOT NULL,
                     question_id TEXT NOT NULL REFERENCES question(id),
                     score TEXT NOT NULL, sentences TEXT NOT NULL, students TEXT NOT NULL, ledger TEXT NOT NULL,
                     feedback TEXT NOT NULL, trace TEXT NOT NULL, extraction_log TEXT NOT NULL,
                     ledger_corrected TEXT, score_corrected TEXT, PRIMARY KEY (run_id, answer_id));
CREATE TABLE override (id INTEGER PRIMARY KEY, answer_id TEXT NOT NULL REFERENCES answer(id),
                       reference_id TEXT NOT NULL, status TEXT NOT NULL, "by" TEXT NOT NULL,
                       date TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE evidence_audit (row_type TEXT, run_id TEXT, answer_id TEXT, entry_id TEXT, reference_id TEXT,
                             status TEXT, quoted_sentences TEXT, present_in_answer TEXT, evidence_correct TEXT,
                             claim_index TEXT, text TEXT, ledger_entry_ids TEXT, supported TEXT);
