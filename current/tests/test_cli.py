import json

from sedb.cli import build_parser, main
from sedb.db import Database
from sedb.views import ViewService


def test_init_creates_empty_database(tmp_path, capsys):
    db_path = tmp_path / "empty.sqlite"

    code = main(["init", "--db", str(db_path)])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert db_path.exists()
    assert output["fields"] == 0
    assert output["entities"] == 0
    assert output["cells"] == 0


def test_demo_builds_ten_thousand_logical_fields_but_stays_sparse(tmp_path, capsys):
    db_path = tmp_path / "demo.sqlite"

    code = main(["demo", "--db", str(db_path), "--fields", "10000"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["fields"] == 10_000
    assert output["entities"] == 3
    assert 1 <= output["cells"] <= 20
    assert output["logical_capacity"] == 30_000
    assert output["density"] < 0.001


def test_stats_prints_current_database_statistics(tmp_path, capsys):
    db_path = tmp_path / "db.sqlite"
    main(["demo", "--db", str(db_path), "--fields", "100"])
    capsys.readouterr()

    code = main(["stats", "--db", str(db_path)])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["fields"] == 100
    assert output["entities"] == 3


def test_cli_parser_exposes_local_commands():
    parser = build_parser()

    assert parser.parse_args(["init", "--db", "x.sqlite"]).command == "init"
    assert parser.parse_args(["demo", "--db", "x.sqlite"]).command == "demo"
    assert parser.parse_args(["stats", "--db", "x.sqlite"]).command == "stats"
    serve = parser.parse_args(["serve", "--db", "x.sqlite", "--port", "9000"])
    assert serve.command == "serve"
    assert serve.port == 9000
