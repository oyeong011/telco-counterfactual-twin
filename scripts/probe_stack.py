#!/usr/bin/env -S uv run --project backend python
"""Probe the live Compose stack and prove the guarded approval lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Final, TypeAlias

import httpx2 as httpx
import typer
from pydantic import JsonValue, TypeAdapter

JSON_HEADERS: Final = {"Accept": "application/json"}
SSE_HEADERS: Final = {"Accept": "text/event-stream"}
DEFAULT_PROBE_OUTPUT: Final = Path("artifacts/eval/local-stack-probe.json")
JsonObject: TypeAlias = dict[str, JsonValue]
JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(dict[str, JsonValue])


class ProbeError(Exception):
    pass


def require(response: httpx.Response, status: int, label: str) -> JsonObject:
    if response.status_code != status:
        raise ProbeError(f"{label}:status={response.status_code}")
    try:
        return JSON_OBJECT_ADAPTER.validate_json(response.content)
    except ValueError as error:
        raise ProbeError(f"{label}:invalid-shape") from error


def require_object(payload: JsonObject, field: str) -> JsonObject:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ProbeError(f"contract-field:{field}")
    return JSON_OBJECT_ADAPTER.validate_python(value)


def require_str(payload: JsonObject, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ProbeError(f"contract-field:{field}")
    return value


def require_build_pair(backend: JsonObject, frontend: JsonObject) -> None:
    for field in ("schema_version", "runtime_source_commit_sha", "release_commit_sha"):
        if backend.get(field) != frontend.get(field):
            raise ProbeError(f"build-info-contract-mismatch:{field}")


def require_finite_sse(
    client: httpx.Client, run_id: str, headers: dict[str, str]
) -> int:
    response = client.get(
        f"/api/runs/{run_id}/events", headers={**headers, **SSE_HEADERS}
    )
    if response.status_code != 200:
        raise ProbeError(f"sse-replay:status={response.status_code}")
    content_type = response.headers.get("content-type", "").split(";")[0]
    if content_type != "text/event-stream":
        raise ProbeError("sse-replay:content-type")
    text = response.text
    if ": heartbeat" not in text:
        raise ProbeError("sse-replay:missing-heartbeat")
    event_count = sum(1 for line in text.splitlines() if line.startswith("event: "))
    if event_count < 1:
        raise ProbeError("sse-replay:empty")
    return event_count


def write_json_atomically(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    _ = temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    )
    _ = temporary.replace(path)


def run(backend: str, frontend: str) -> JsonObject:
    with httpx.Client(base_url=backend, timeout=15) as client:
        origin_headers = {"Origin": frontend}
        health = require(
            client.get("/healthz", headers=JSON_HEADERS),
            200,
            "stack-health-failed",
        )
        ready_response = client.get("/readyz", headers=JSON_HEADERS)
        if ready_response.status_code != 200:
            raise ProbeError(
                f"stack-readiness-degraded:status={ready_response.status_code}"
            )
        ready = require(ready_response, 200, "stack-readiness-degraded")
        build = require(
            client.get("/build-info", headers=JSON_HEADERS),
            200,
            "backend-build-info",
        )
        with httpx.Client(base_url=frontend, timeout=15) as ui:
            ui_build = require(
                ui.get("/build-info.json", headers=JSON_HEADERS),
                200,
                "frontend-build-info",
            )
        require_build_pair(build, ui_build)
        session = require(
            client.post(
                "/api/demo-sessions",
                headers={**JSON_HEADERS, **origin_headers},
                json={"synthetic_only": True},
            ),
            201,
            "bootstrap",
        )
        headers = {"X-Demo-Session-Token": require_str(session, "demo_token")}
        before = client.post(
            "/api/simulations/simulation-missing/approval-requests",
            headers={**headers, "Idempotency-Key": "probe-before"},
            json={},
        )
        if before.status_code < 400:
            raise ProbeError("approval-before-simulation-was-accepted")
        scenario = require(
            client.post(
                "/api/scenarios",
                headers={**headers, "Idempotency-Key": "probe-scenario"},
                json={"fault_family": "radio-congestion", "seed": 6701},
            ),
            201,
            "scenario",
        )
        scenario_contract = require_object(scenario, "scenario")
        scenario_id = require_str(scenario_contract, "scenario_id")
        _ = require(
            client.post(
                f"/api/scenarios/{scenario_id}/diagnose",
                headers={**headers, "Idempotency-Key": "probe-diagnosis"},
                json={},
            ),
            200,
            "diagnosis",
        )
        patch_body = {
            "patch_id": "patch-probe-0001",
            "scenario_id": scenario_id,
            "base_topology_hash": require_str(scenario, "topology_hash"),
            "changes": [
                {
                    "target_id": "cell-0001",
                    "target_kind": "cell",
                    "operation": "adjust-radio-capacity",
                    "parameters": {"capacity_ues": 230},
                }
            ],
            "blast_radius": {"max_cells": 1, "max_ue_cohorts": 1, "max_slices": 1},
            "proposed_at": require_str(scenario_contract, "starts_at"),
            "schema_version": "1.0",
        }
        patch = require(
            client.post(
                f"/api/scenarios/{scenario_id}/patches",
                headers={**headers, "Idempotency-Key": "probe-patch"},
                json=patch_body,
            ),
            201,
            "patch",
        )
        patch_id = require_str(require_object(patch, "patch"), "patch_id")
        simulation = require(
            client.post(
                f"/api/patches/{patch_id}/simulations",
                headers={**headers, "Idempotency-Key": "probe-simulation"},
                json={},
            ),
            201,
            "simulation",
        )
        simulation_id = require_str(simulation, "simulation_id")
        run_id = require_str(simulation, "run_id")
        comparison = require(
            client.post(
                f"/api/simulations/{simulation_id}/comparisons",
                headers={**headers, "Idempotency-Key": "probe-comparison"},
                json={},
            ),
            201,
            "comparison",
        )
        _ = require_str(comparison, "comparison_id")
        sse_event_count = require_finite_sse(client, run_id, headers)
        approval = require(
            client.post(
                f"/api/simulations/{simulation_id}/approval-requests",
                headers={**headers, "Idempotency-Key": "probe-approval"},
                json={},
            ),
            201,
            "approval",
        )
    if "effect" in approval:
        raise ProbeError("approval-authority-boundary-violated")
    approval_request = require_object(approval, "approval_request")
    approval_state = require_str(approval_request, "state")
    if approval_state != "pending":
        raise ProbeError(f"approval-request-state:{approval_state}")
    return {
        "schema_version": "1.0",
        "status": "passed",
        "endpoints": {
            "healthz": health,
            "readyz": ready,
            "backend_build_info": build,
            "frontend_build_info": ui_build,
        },
        "lifecycle": {
            "approval_before_simulation_status": before.status_code,
            "scenario_created": True,
            "simulation_created": True,
            "comparison_created": True,
            "approval_request_created": True,
            "approval_state": approval_state,
            "fault_family": "radio-congestion",
            "seed": 6701,
            "network_change_permitted": False,
            "effect": "none",
            "sse_event_count": sse_event_count,
        },
    }


def main(
    backend_url: Annotated[
        str, typer.Option("--backend-url")
    ] = "http://127.0.0.1:18080",
    frontend_url: Annotated[
        str, typer.Option("--frontend-url")
    ] = "http://127.0.0.1:4173",
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    output = out if out is not None else DEFAULT_PROBE_OUTPUT
    try:
        payload = run(backend_url, frontend_url)
    except (httpx.HTTPError, KeyError, ValueError, ProbeError) as error:
        print(f"stack-probe-failed:{error}")
        raise typer.Exit(1) from error
    write_json_atomically(output, payload)
    print(f"stack-probe-passed:{output}")


if __name__ == "__main__":
    typer.run(main)
