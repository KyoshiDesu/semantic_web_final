"""Load one dataset folder into a running AutoGrade-RDF app through its HTTP API (the same calls the Kelas page makes).

Optional: everything here can also be done by hand on the Kelas page (see datasets/README.md).

    ./run.sh                                     # start the app first
    python datasets/import_datasets.py datasets/en_mohler_cs --split demo
    python datasets/import_datasets.py datasets/id_ukara --split pilot --split test

It creates the course and assessment if they don't exist, uploads every question folder that isn't in the app yet,
imports answers_<split>.csv (pilot -> split "pilot", anything else -> split "test") and scores_<split>.csv
(one import per question and rater). Already imported answers are skipped by the app, so re-running is safe.
Standard library only.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib import error, request

QUESTION_FILES = ("question.md", "reference_answer.md", "rubric.yaml", "gold.yaml")
DATASETS = {
    "en_mohler_cs": ("MOHLER-EN", "Mohler CS short answers (EN)", "Mohler 2011 subset"),
    "id_ukara": ("UKARA-ID", "UKARA 1.0 jawaban singkat (ID)", "UKARA Task A & B"),
}


class Api:
    def __init__(self, base):
        self.base = base.rstrip("/") + "/api"

    def call(self, method, path, body=None, headers=None):
        req = request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with request.urlopen(req) as r:
                return json.loads(r.read() or b"null")
        except error.HTTPError as e:
            sys.exit(f"{method} {path} failed ({e.code}): {e.read().decode('utf-8', 'replace')}")
        except error.URLError as e:
            sys.exit(f"cannot reach {self.base} ({e.reason}); start the app with ./run.sh first")

    def get(self, path):
        return self.call("GET", path)

    def post_json(self, path, obj):
        return self.call("POST", path, json.dumps(obj).encode(), {"Content-Type": "application/json"})

    def post_files(self, path, files, fields=None):
        """multipart/form-data: files = [(field, filename, bytes)], fields = {name: text}."""
        b = uuid.uuid4().hex
        parts = []
        for name, value in (fields or {}).items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for field, fname, data in files:
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                         f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
        body = b"".join(parts) + f"--{b}--\r\n".encode()
        return self.call("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={b}"})


def header(csv_path):
    return csv_path.read_text(encoding="utf-8-sig").splitlines()[0].split(",")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="datasets/en_mohler_cs or datasets/id_ukara")
    ap.add_argument("--split", action="append", default=[], help="demo, pilot, dev or test (repeatable)")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    code, cname, aname = DATASETS[args.folder.resolve().name]
    api = Api(args.url)

    course = next((c for c in api.get("/courses") if c["code"] == code), None) \
        or api.post_json("/courses", {"code": code, "name": cname})
    cid = course["id"]
    assessment = next((a for a in api.get(f"/courses/{cid}/assessments") if a["name"] == aname), None) \
        or api.post_json(f"/courses/{cid}/assessments", {"name": aname})
    aid = assessment["id"]
    known = {q["id"] for q in api.get("/questions")}
    qids = []
    for qdir in sorted(p for p in (args.folder / "questions").iterdir() if p.is_dir()):
        qids.append(qdir.name)
        if qdir.name in known:
            print(f"question {qdir.name}: already in the app")
            continue
        files = [("files", f, (qdir / f).read_bytes()) for f in QUESTION_FILES]
        print("question", api.post_files(f"/assessments/{aid}/questions/upload", files)["id"], "added")

    for split in args.split:
        answers, scores = args.folder / f"answers_{split}.csv", args.folder / f"scores_{split}.csv"
        cols = header(answers)
        mapping = {"id_col": "student_id", "name_cols": [], "split": "pilot" if split == "pilot" else "test",
                   "columns": {q: {"column": q} for q in qids if q in cols}}
        r = api.post_files(f"/courses/{cid}/answers", [("file", answers.name, answers.read_bytes())],
                           {"mapping": json.dumps(mapping)})
        print(f"{answers.name}: {r['added']} answers added, {len(r['existing'])} already there")
        added = 0
        for col in header(scores)[1:]:
            qid, rater = col.rsplit("__", 1)
            m = {"id_col": "student_id", "question_id": qid, "rater_id": rater, "columns": {"_total": col}}
            added += api.post_files(f"/courses/{cid}/scores", [("file", scores.name, scores.read_bytes())],
                                    {"mapping": json.dumps(m)})["added"]
        print(f"{scores.name}: {added} lecturer scores added")


if __name__ == "__main__":
    main()
