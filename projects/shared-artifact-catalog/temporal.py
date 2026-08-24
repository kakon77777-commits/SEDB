from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from schema import CatalogStore


SAFE_BATCH = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SAFE_OPERATION = re.compile(r"^[a-z0-9_]{1,40}$")


class CtclError(RuntimeError):
    """Raised when CTCL rejects or returns a malformed temporal response."""


class JsonTransport(Protocol):
    def post_json(self, url: str, payload: dict, timeout: float) -> dict:
        raise NotImplementedError


class UrllibJsonTransport:
    def post_json(self, url: str, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "SEDB-Artifact-Catalog/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class CtclClient:
    base_url: str
    timeout_seconds: float
    transport: JsonTransport = field(default_factory=UrllibJsonTransport)

    def register_instant(
        self,
        captured_utc: datetime,
        batch_id: str,
        operation_kind: str,
    ) -> dict:
        if not SAFE_BATCH.fullmatch(batch_id):
            raise CtclError("batch id must be opaque ASCII")
        if not SAFE_OPERATION.fullmatch(operation_kind):
            raise CtclError("operation kind must be a safe lowercase key")
        value = _utc_text(captured_utc)
        payload = {
            "value": value,
            "encoding": "rfc3339",
            "timescale": "utc",
            "label": f"sedb-catalog:{batch_id}",
            "meta": {
                "operation_kind": operation_kind,
                "sensitive": False,
            },
        }
        body = self.transport.post_json(
            f"{self.base_url.rstrip('/')}/v1/instants",
            payload,
            self.timeout_seconds,
        )
        data = body.get("data", {}) if isinstance(body, dict) else {}
        if not body.get("ok") or not data.get("id"):
            raise CtclError("CTCL response missing registered instant id")
        return data


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("captured instant must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _local_zone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Taipei":
            return timezone(timedelta(hours=8), name="Asia/Taipei")
        raise


def _source_name(data: dict) -> str:
    source = data.get("source", "")
    if isinstance(source, dict):
        return str(source.get("name", ""))
    return str(source)


def _registered_values(data: dict) -> dict:
    quality = data.get("quality", {})
    uncertainty = quality.get("estimated_uncertainty_ns")
    values = {
        "temporal_status": "registered",
        "ctcl_instant_id": str(data["id"]),
        "ctcl_source": _source_name(data),
        "ctcl_precision": str(quality.get("precision", "")),
    }
    if uncertainty is not None:
        values["ctcl_uncertainty_ns"] = int(uncertainty)
    return values


def create_temporal_anchor(
    store: CatalogStore,
    client: CtclClient,
    operation_kind: str,
    *,
    captured_utc: datetime | None = None,
    batch_id: str | None = None,
    timezone_name: str = "Asia/Taipei",
) -> dict:
    captured = captured_utc or datetime.now(timezone.utc)
    utc_text = _utc_text(captured)
    local_text = captured.astimezone(_local_zone(timezone_name)).isoformat()
    opaque_batch = batch_id or f"batch-{uuid4().hex}"
    values = {
        "stable_key": opaque_batch,
        "batch_id": opaque_batch,
        "operation_kind": operation_kind,
        "local_observed_at": local_text,
        "ctcl_utc": utc_text,
        "ctcl_local": local_text,
    }
    try:
        data = client.register_instant(
            captured, opaque_batch, operation_kind
        )
        values.update(_registered_values(data))
    except (OSError, ValueError, CtclError, json.JSONDecodeError) as exc:
        values.update(
            {
                "temporal_status": "pending",
                "failure_reason": str(exc),
            }
        )
    return store.create_record(
        "temporal_anchor",
        f"{operation_kind} {opaque_batch}",
        values,
        entity_id=f"temporal-anchor:{uuid4().hex}",
        source="artifact-catalog:temporal",
    )


def _successful_reconciliations(
    store: CatalogStore, anchor_id: str
) -> list[dict]:
    return [
        event
        for event in store.find(
            "temporal_reconciliation", source_record_id=anchor_id
        )
        if event["values"].get("outcome") == "registered"
    ]


def reconcile_pending(
    store: CatalogStore, client: CtclClient
) -> list[dict]:
    created: list[dict] = []
    for anchor in store.find("temporal_anchor", temporal_status="pending"):
        if _successful_reconciliations(store, anchor["id"]):
            continue
        values = anchor["values"]
        captured = datetime.fromisoformat(
            str(values["ctcl_utc"]).replace("Z", "+00:00")
        )
        try:
            data = client.register_instant(
                captured,
                str(values["batch_id"]),
                str(values["operation_kind"]),
            )
            event_values = {
                "source_record_id": anchor["id"],
                "outcome": "registered",
                "ctcl_utc": str(values["ctcl_utc"]),
                "ctcl_local": str(values["ctcl_local"]),
                **_registered_values(data),
            }
        except (OSError, ValueError, CtclError, json.JSONDecodeError) as exc:
            event_values = {
                "source_record_id": anchor["id"],
                "outcome": "failed",
                "failure_reason": str(exc),
                "ctcl_utc": str(values["ctcl_utc"]),
                "ctcl_local": str(values["ctcl_local"]),
            }
        created.append(
            store.create_record(
                "temporal_reconciliation",
                f"reconcile {anchor['id']}",
                event_values,
                source="artifact-catalog:temporal",
            )
        )
    return created


def get_effective_temporal_anchor(
    store: CatalogStore, anchor_id: str
) -> dict:
    values = dict(store.get_record(anchor_id)["values"])
    reconciliations = _successful_reconciliations(store, anchor_id)
    if reconciliations:
        values.update(reconciliations[-1]["values"])
    return values
