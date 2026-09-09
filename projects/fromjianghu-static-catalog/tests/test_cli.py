from __future__ import annotations

import io
import json
import sys

from cli import main


def base_args(source_fixture):
    return [
        "--source-root", str(source_fixture["root"]),
        "--db", str(source_fixture["db"]),
        "--contract", str(source_fixture["contract"]),
    ]


def test_plan_is_read_only_when_database_does_not_exist(source_fixture, capsys):
    code = main([*base_args(source_fixture), "plan"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "ready"
    assert payload["diff"] == {
        "new": 10,
        "unchanged": 0,
        "conflict": 0,
        "missing_from_source": 0,
    }
    assert source_fixture["db"].exists() is False


def test_bootstrap_then_replay_and_classify(source_fixture, capsys):
    first_code = main([*base_args(source_fixture), "bootstrap"])
    first = json.loads(capsys.readouterr().out)
    second_code = main([*base_args(source_fixture), "bootstrap"])
    second = json.loads(capsys.readouterr().out)
    classify_code = main([*base_args(source_fixture), "classify"])
    classified = json.loads(capsys.readouterr().out)

    assert first_code == second_code == classify_code == 0
    assert first["status"] == "imported"
    assert first["write"]["created_entities"] == 10
    assert second["status"] == "no_op"
    assert second["diff"]["unchanged"] == 10
    assert classified["classification"]["by_kind"] == source_fixture["expected_counts"]
    assert classified["integrity"] == "ok"


def test_main_reconfigures_cp950_stdout_before_emitting_source_text(
    source_fixture,
    capsys,
    monkeypatch,
):
    assert main([*base_args(source_fixture), "bootstrap"]) == 0
    capsys.readouterr()
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp950", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    code = main([*base_args(source_fixture), "search", "功能甲"])
    stream.flush()
    payload = json.loads(buffer.getvalue().decode("utf-8"))

    assert code == 0
    assert payload["status"] == "ok"
    assert any("功能甲" in json.dumps(item, ensure_ascii=False) for item in payload["results"])
