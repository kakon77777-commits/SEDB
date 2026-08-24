import pytest

from sedb.agent import DeterministicDiscoveryBackend, ExternalSuggestionBackend, json_sha256


def test_deterministic_backend_discovers_record_keys_without_numeric_array_fields():
    backend = DeterministicDiscoveryBackend()
    observation = {
        "records": [
            {
                "paper": "P001",
                "publication_type": "preprint",
                "ai_assistance_disclosed": True,
                "metrics": {"citation_count": 12},
            },
            {
                "paper": "P002",
                "publication_type": "journal",
                "ai_assistance_disclosed": False,
                "metrics": {"citation_count": 3},
            },
        ]
    }

    suggestions = backend.suggest(observation)
    by_key = {item["key"]: item for item in suggestions}

    assert {"paper", "publication_type", "ai_assistance_disclosed", "metrics_citation_count"} <= set(by_key)
    assert by_key["ai_assistance_disclosed"]["value_type"] == "boolean"
    assert by_key["metrics_citation_count"]["value_type"] == "integer"
    assert all("_0_" not in key and "_1_" not in key for key in by_key)
    assert any(ref.endswith("#/records/0/publication_type") for ref in by_key["publication_type"]["evidence_refs"])


def test_deterministic_backend_is_stable_and_marks_conflicting_types_as_json():
    backend = DeterministicDiscoveryBackend()
    observation = {"records": [{"score": 1}, {"score": "high"}]}

    first = backend.suggest(observation)
    second = backend.suggest(observation)

    assert first == second
    assert first[0]["key"] == "score"
    assert first[0]["value_type"] == "json"
    assert first[0]["confidence"] < 1.0


def test_external_suggestion_backend_validates_and_normalizes_packet():
    backend = ExternalSuggestionBackend()
    packet = {
        "suggestions": [
            {
                "key": "AI Assistance Disclosed",
                "label": "AI Assistance Disclosed",
                "value_type": "boolean",
                "reason": "Observed explicit disclosure metadata",
                "confidence": 0.91,
                "evidence_refs": ["obs:4#/records/0"],
            }
        ]
    }

    result = backend.validate(packet)

    assert result[0]["key"] == "ai_assistance_disclosed"
    assert result[0]["label"] == "AI Assistance Disclosed"
    assert result[0]["confidence"] == 0.91
    assert result[0]["evidence_refs"] == ["obs:4#/records/0"]


@pytest.mark.parametrize(
    "packet,match",
    [
        ({}, "suggestions"),
        ({"suggestions": [{}]}, "key"),
        ({"suggestions": [{"key": "x", "label": "X", "reason": "r", "confidence": 2}]}, "confidence"),
        ({"suggestions": [{"key": "x", "label": "X", "reason": "", "confidence": 0.5}]}, "reason"),
    ],
)
def test_external_suggestion_backend_rejects_malformed_packets(packet, match):
    with pytest.raises(ValueError, match=match):
        ExternalSuggestionBackend().validate(packet)


def test_json_sha256_is_canonical_for_key_order():
    assert json_sha256({"b": 2, "a": 1}) == json_sha256({"a": 1, "b": 2})
