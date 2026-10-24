"""CLI entry points that touch the database."""
import pytest

from autograde import cli


def test_cli_without_database_exits_with_hint(fresh_db):
    with pytest.raises(SystemExit, match="db import"):
        cli.main(["run", "--question", "Q1", "--mode", "gold", "--split", "all"])


def test_db_init_creates_an_empty_database(fresh_db, capsys):
    cli.main(["db", "init"])
    assert "empty database" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="db import"):  # still no questions
        cli.main(["evaluate", "--run", "x"])
