from __future__ import annotations

import json
from datetime import datetime, timezone

from schema import CatalogStore
from temporal import (
    CtclClient,
    create_temporal_anchor,
    get_effective_temporal_anchor,
    reconcile_pending,
)


class FakeTransport:
    def __init__(self, *, fail: bool = False, malformed: bool = False):
        self.fail = fail
        self.malformed = malformed
        self.calls: list[tuple[str, dict, float]] = []

    def post_json(self, url: str, payload: dict, timeout: float) -> dict:
        self.calls.append((url, payload, timeout))
        if self.fail:
            raise OSError("offline")
        if self.malformed:
            return {"ok": True, "data": {}}
        return {
            "ok": True,
            "data": {
                "id": "ctcl:instant:test",
                "reference": {
                    "timescale": "utc",
                    "value": payload["value"],
                },
                "source": {"name": "cloudflare-edge-wall-clock"},
                "quality": {
                    "precision": "ms",
                    "estimated_uncertainty_ns": 1_000_000,
                },
            },
        }


def _store(tmp_path) -> CatalogStore:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    return store


def test_registered_anchor_payload_is_opaque_and_locally_readable(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    transport = FakeTransport()
    client = CtclClient(
        "https://commoninstant.org", 8, transport=transport
    )
    captured = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    anchor = create_temporal_anchor(
        store,
        client,
        "ingest",
        captured_utc=captured,
        batch_id="batch-0123456789abcdef",
    )

    _, payload, timeout = transport.calls[0]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "D:\\" not in serialized
    assert ".md" not in serialized
    assert payload == {
        "value": "2026-08-24T12:00:00Z",
        "encoding": "rfc3339",
        "timescale": "utc",
        "label": "sedb-catalog:batch-0123456789abcdef",
        "meta": {"operation_kind": "ingest", "sensitive": False},
    }
    assert timeout == 8
    assert anchor["values"]["temporal_status"] == "registered"
    assert anchor["values"]["ctcl_instant_id"] == "ctcl:instant:test"
    assert anchor["values"]["ctcl_utc"] == "2026-08-24T12:00:00Z"
    assert anchor["values"]["ctcl_local"] == "2026-08-24T20:00:00+08:00"


def test_offline_anchor_is_pending_without_fabricating_ctcl_id(tmp_path) -> None:
    store = _store(tmp_path)
    captured = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    anchor = create_temporal_anchor(
        store,
        CtclClient("https://commoninstant.org", 1, FakeTransport(fail=True)),
        "copy",
        captured_utc=captured,
        batch_id="batch-offline",
    )

    assert anchor["values"]["temporal_status"] == "pending"
    assert "ctcl_instant_id" not in anchor["values"]
    assert anchor["values"]["ctcl_utc"] == "2026-08-24T12:00:00Z"
    assert anchor["values"]["failure_reason"] == "offline"


def test_malformed_ctcl_response_is_pending(tmp_path) -> None:
    store = _store(tmp_path)

    anchor = create_temporal_anchor(
        store,
        CtclClient(
            "https://commoninstant.org",
            1,
            FakeTransport(malformed=True),
        ),
        "translation_start",
    )

    assert anchor["values"]["temporal_status"] == "pending"
    assert "registered instant id" in anchor["values"]["failure_reason"]


def test_pending_reconciliation_uses_original_time_once(tmp_path) -> None:
    store = _store(tmp_path)
    captured = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    pending = create_temporal_anchor(
        store,
        CtclClient("https://x", 1, FakeTransport(fail=True)),
        "copy",
        captured_utc=captured,
        batch_id="batch-pending",
    )
    transport = FakeTransport()
    client = CtclClient("https://x", 1, transport)

    first = reconcile_pending(store, client)
    second = reconcile_pending(store, client)
    effective = get_effective_temporal_anchor(store, pending["id"])

    assert transport.calls[0][1]["value"] == "2026-08-24T12:00:00Z"
    assert len(transport.calls) == 1
    assert len(first) == 1
    assert second == []
    assert first[0]["kind"] == "temporal_reconciliation"
    assert first[0]["values"]["source_record_id"] == pending["id"]
    assert effective["temporal_status"] == "registered"
    assert effective["ctcl_instant_id"] == "ctcl:instant:test"
