"""After `db import`, only importer.py may read data/ or the old run folders (spec, section 3)."""
import re

from autograde import io

BANNED = re.compile(r'question_dir|annotation_path|runs_dir|"data" /|"outputs" / "(runs|ui)"'
                    r'|"(gold|answer|ledger)[a-z_]*\.ttl"')


def test_no_module_reads_the_old_files():
    files = [p for p in (io.ROOT / "src" / "autograde").rglob("*.py") if p.name != "importer.py"]
    files += list((io.ROOT / "app").glob("*.py"))
    hits = [f"{p.relative_to(io.ROOT)}:{i}: {line.strip()}"
            for p in files for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if BANNED.search(line)]
    assert hits == []
