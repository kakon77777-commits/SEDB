import json

from conftest import paper
from cli import main
from sedb.db import Database
from sedb.fields import FieldService


def run(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def base_args(registry, db):
    return ("--source", str(registry), "--db", str(db))


def test_bootstrap_then_no_op_json(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001"), paper("lm-000002")])
    db = tmp_path / "corpus.sqlite"

    code, first = run(
        capsys,
        *base_args(registry, db),
        "bootstrap",
        "--month",
        "2026-04",
    )
    code_again, second = run(
        capsys,
        *base_args(registry, db),
        "bootstrap",
        "--month",
        "2026-04",
    )

    assert code == 0
    assert first["status"] == "imported"
    assert first["diff"]["new"] == 2
    assert code_again == 0
    assert second["status"] == "no_op"
    assert second["no_op"] is True
    assert second["diff"]["unchanged"] == 2


def test_empty_valid_month_is_exit_2(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])

    code, result = run(
        capsys,
        *base_args(registry, tmp_path / "db.sqlite"),
        "bootstrap",
        "--month",
        "2026-09",
    )

    assert code == 2
    assert result["status"] == "error"
    assert result["reason_code"] == "target_month_empty"


def test_missing_month_argument_is_json_exit_2(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])

    code, result = run(
        capsys,
        *base_args(registry, tmp_path / "db.sqlite"),
        "bootstrap",
    )

    assert code == 2
    assert result["reason_code"] == "invalid_arguments"


def test_schema_conflict_is_exit_3_and_is_not_overwritten(
    write_registry,
    tmp_path,
    capsys,
):
    registry = write_registry([paper("lm-000001")])
    db_path = tmp_path / "db.sqlite"
    db = Database(db_path)
    conflict = FieldService(db).create_field(
        key="paper_id",
        label="Wrong",
        namespace="wrong",
    )

    code, result = run(
        capsys,
        *base_args(registry, db_path),
        "bootstrap",
        "--month",
        "2026-04",
    )

    assert code == 3
    assert result["reason_code"] == "schema_conflict"
    assert FieldService(db).get_field(conflict["id"])["label"] == "Wrong"


def test_data_conflict_is_exit_4_and_blocks_new(
    write_registry,
    tmp_path,
    capsys,
):
    first_registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"
    first_code, _ = run(
        capsys,
        *base_args(first_registry, db),
        "bootstrap",
        "--month",
        "2026-04",
    )
    changed_registry = write_registry(
        [paper("lm-000001", title="Changed"), paper("lm-000002")]
    )

    code, result = run(
        capsys,
        *base_args(changed_registry, db),
        "bootstrap",
        "--month",
        "2026-04",
    )

    assert first_code == 0
    assert code == 4
    assert result["status"] == "blocked"
    assert result["diff"]["conflict"] == 1
    assert result["diff"]["new"] == 1


def test_storage_failure_is_exit_5(
    write_registry,
    tmp_path,
    capsys,
    monkeypatch,
):
    import cli
    from store import StorageError

    registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"

    def fail_apply(self, plan):
        raise StorageError("storage_failure", "injected CLI storage failure")

    monkeypatch.setattr(cli.CorpusStore, "apply", fail_apply)

    code, result = run(
        capsys,
        *base_args(registry, db),
        "bootstrap",
        "--month",
        "2026-04",
    )

    assert code == 5
    assert result["status"] == "error"
    assert result["reason_code"] == "storage_failure"


def test_init_and_stats_are_json_commands(write_registry, tmp_path, capsys):
    registry = write_registry([paper("lm-000001")])
    db = tmp_path / "db.sqlite"

    init_code, initialized = run(
        capsys,
        *base_args(registry, db),
        "init",
    )
    stats_code, stats = run(
        capsys,
        *base_args(registry, db),
        "stats",
    )

    assert init_code == 0
    assert initialized["status"] == "initialized"
    assert stats_code == 0
    assert stats["status"] == "ok"
    assert stats["stats"]["integrity"] == "ok"
