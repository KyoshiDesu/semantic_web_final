"""Background grading for the API: one job at a time in a daemon thread, progress in the job table.

Grading is resumable per answer, so a job that dies with the server is marked interrupted at the next start and is
simply started again: the status table no longer lists the answers it already graded.
"""
import logging
import threading

from autograde import db, grades, pipeline
from autograde.normalize import Embedder

log = logging.getLogger("uvicorn.error")
WANTED = {"new": "belum dinilai", "stale": "usang"}
_start_lock = threading.Lock()  # checking for a running job and inserting the new one are one step
_cancel = {}  # job id -> threading.Event, for jobs whose thread runs in this process
_contexts = {}  # (qid, question.updated) -> pipeline.Context
_embedder = None


class JobConflict(RuntimeError):
    pass


class NothingToGrade(ValueError):
    pass


def embedder():
    """One Embedder per process: the sentence-transformers model loads once, not once per question."""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def context(qid):
    """The question's grading context, keyed by its `updated` stamp: an edited key is used from the next answer on,
    instead of grading the rest of a job with the old one."""
    key = (qid, db.question_updated([qid]).get(qid))
    if key not in _contexts:
        for old in [k for k in _contexts if k[0] == qid]:
            _contexts.pop(old, None)
        _contexts[key] = pipeline.Context.load(qid, cosine=embedder().cosine)
    return _contexts[key]


def start(assessment_id, which, llm_feedback):
    run_id = pipeline.assessment_run(assessment_id)
    table = grades.status_table(assessment_id, run_id)
    ids = table[table.status == WANTED[which]].answer_id.tolist()
    if not ids:
        raise NothingToGrade(f"no answers are '{WANTED[which]}'")
    with _start_lock:
        running = db.running_job()
        if running:
            raise JobConflict(f"job {running['id']} is still grading; wait for it or cancel it")
        job_id = db.create_job(assessment_id, run_id, which, llm_feedback, ids)
        _cancel[job_id] = threading.Event()
    threading.Thread(target=run_job, args=(job_id,), name=f"grading-job-{job_id}", daemon=True).start()
    return db.job(job_id)


def run_job(job_id):
    job = db.job(job_id)
    cancel = _cancel.setdefault(job_id, threading.Event())
    try:
        answers = {a.answer_id: a for a in db.assessment_answers(job["assessment_id"]).itertuples()}
        done, failures, cancelled = 0, [], False
        for aid in job["answer_ids"]:
            if cancel.is_set():
                cancelled = True
                break
            db.update_job(job_id, aid, done, failures)
            a = answers[aid]
            try:
                pipeline.grade_assessment_answer(job["run_id"], a, {a.question_id: context(a.question_id)},
                                                 job["llm_feedback"])
            except Exception as e:  # one answer's failure (no API key, parity) must not stop the class
                log.warning("grading job %s: %s failed: %s", job_id, aid, e)
                failures.append({"answer_id": aid, "error": str(e)})
            done += 1
        db.update_job(job_id, None, done, failures)
        db.finish_run(job["run_id"])
        db.finish_job(job_id, "cancelled" if cancelled else "done")
    except Exception:  # never leave a dead job 'running': it would block every new one
        log.exception("grading job %s stopped", job_id)
        db.finish_job(job_id, "interrupted")
    finally:
        _cancel.pop(job_id, None)


def cancel(job_id):
    """Stops after the current answer: an LLM call can't be stopped halfway."""
    job = db.job(job_id)
    if job["status"] != "running":
        raise JobConflict(f"job {job_id} is {job['status']}, not running")
    event = _cancel.get(job_id)
    if event is None:  # marked running, but its thread died with an earlier server
        db.finish_job(job_id, "interrupted")
    else:
        event.set()
    return db.job(job_id)
