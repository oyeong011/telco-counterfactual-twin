from __future__ import annotations

import json
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, override
from urllib.parse import urlparse

from pydantic import JsonValue, TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[3]
type JsonObject = dict[str, JsonValue]
JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(dict[str, JsonValue])


class DegradedHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = HTTPStatus.SERVICE_UNAVAILABLE if self.path == "/readyz" else HTTPStatus.OK
        body = json.dumps(
            {"status": "degraded" if status == HTTPStatus.SERVICE_UNAVAILABLE else "live"}
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        _ = self.wfile.write(body)

    @override
    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


class ProbeHandler(BaseHTTPRequestHandler):
    seen_paths: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        self.seen_paths.append(path)
        match path:
            case "/healthz":
                self.write_json({"status": "live"})
            case "/readyz":
                self.write_json({"status": "ready"})
            case "/build-info" | "/build-info.json":
                self.write_json(build_info("release-1"))
            case "/api/runs/run-probe/events":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event_id = "evt-1"
                event_type = "simulation.completed"
                event_body = "\n".join(
                    (
                        f"id: {event_id}",
                        f"event: {event_type}",
                        f'data: {{"event_id":"{event_id}"}}',
                        "",
                        ": heartbeat",
                        "",
                    )
                )
                event_bytes = event_body.encode()
                _ = self.wfile.write(event_bytes)
            case _:
                self.write_json({"error": path}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        self.seen_paths.append(path)
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 0:
            _ = self.rfile.read(content_length)
        match path:
            case "/api/demo-sessions":
                self.write_json({"demo_token": "token-probe"}, status=HTTPStatus.CREATED)
            case "/api/simulations/simulation-missing/approval-requests":
                self.write_json({"error": "missing"}, status=HTTPStatus.NOT_FOUND)
            case "/api/scenarios":
                self.write_json(
                    {
                        "scenario": {
                            "scenario_id": "scenario-probe",
                            "starts_at": "2027-01-01T00:00:00Z",
                        },
                        "topology_hash": "0" * 64,
                    },
                    status=HTTPStatus.CREATED,
                )
            case "/api/scenarios/scenario-probe/diagnose":
                self.write_json({"diagnosis": {"fault_family": "radio-congestion"}})
            case "/api/scenarios/scenario-probe/patches":
                self.write_json(
                    {"patch": {"patch_id": "patch-probe-0001"}}, status=HTTPStatus.CREATED
                )
            case "/api/patches/patch-probe-0001/simulations":
                self.write_json(
                    {"simulation_id": "simulation-probe", "run_id": "run-probe"},
                    status=HTTPStatus.CREATED,
                )
            case "/api/simulations/simulation-probe/comparisons":
                self.write_json({"comparison_id": "comparison-probe"}, status=HTTPStatus.CREATED)
            case "/api/simulations/simulation-probe/approval-requests":
                self.write_json(
                    {
                        "approval_request": {"state": "pending"},
                        "run_id": "run-probe",
                        "evidence_id": "evidence-probe",
                        "policy": {"eligible": True},
                    },
                    status=HTTPStatus.CREATED,
                )
            case _:
                self.write_json({"error": path}, status=HTTPStatus.NOT_FOUND)

    def write_json(self, body: Mapping[str, object], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        _ = self.wfile.write(json.dumps(body).encode())

    @override
    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


def build_info(release: str) -> dict[str, str]:
    return {
        "schema_version": "1.0",
        "runtime_source_commit_sha": release,
        "release_commit_sha": release,
    }


def docker_run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run Docker for bounded image contract checks."""
    return subprocess.run(
        ("docker", *args),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def run_probe(
    handler: type[BaseHTTPRequestHandler], tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], Path, ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "probe.json"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/probe_stack.py"),
                "--backend-url",
                f"http://127.0.0.1:{server.server_port}",
                "--frontend-url",
                f"http://127.0.0.1:{server.server_port}",
                "--out",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return result, output, server


def test_probe_rejects_degraded_readiness_without_artifact(tmp_path: Path) -> None:
    # Given: a stack whose liveness endpoint passes but readiness is degraded.
    # When: the stack probe runs.
    result, output, _ = run_probe(DegradedHandler, tmp_path)
    # Then: it fails without writing a success artifact.
    assert result.returncode == 1
    assert "stack-readiness-degraded" in result.stdout
    assert not output.exists()


def test_probe_writes_success_artifact_after_lifecycle_and_finite_sse(tmp_path: Path) -> None:
    # Given: a live HTTP stack that satisfies the synthetic lifecycle contract.
    ProbeHandler.seen_paths = []
    # When: the stack probe runs.
    result, output, _ = run_probe(ProbeHandler, tmp_path)
    # Then: it records deterministic evidence only after the lifecycle and SSE pass.
    assert result.returncode == 0, result.stdout + result.stderr
    payload = JSON_OBJECT_ADAPTER.validate_json(output.read_bytes())
    assert payload["status"] == "passed"
    lifecycle = payload.get("lifecycle")
    assert isinstance(lifecycle, dict)
    assert lifecycle.get("sse_event_count") == 1
    assert lifecycle.get("approval_state") == "pending"
    assert "approval_status" not in lifecycle
    assert "/api/runs/run-probe/events" in ProbeHandler.seen_paths
    assert not (tmp_path / "probe.json.tmp").exists()


def test_frontend_image_runs_as_node_with_readable_build_info() -> None:
    # Given: the production frontend image is built from the release Dockerfile.
    tag = "telco-counterfactual-twin-task10-frontend-permissions:pytest"
    build = docker_run("build", "-f", "frontend/Dockerfile", "-t", tag, ".", timeout=300)
    assert build.returncode == 0, build.stdout + build.stderr
    try:
        # When: Docker records the configured runtime user and Node reads the built artifact.
        inspect = docker_run("image", "inspect", tag, "--format", "{{.Config.User}}")
        script = """
const fs = require('node:fs');
const paths = ['/app/server.mjs', '/app/dist', '/app/dist/build-info.json'];
if (process.getuid && process.getuid() === 0) process.exit(10);
const payload = JSON.parse(fs.readFileSync('/app/dist/build-info.json', 'utf8'));
if (payload.schema_version !== '1.0') process.exit(11);
for (const path of paths) {
  fs.accessSync(path, fs.constants.R_OK);
  const mode = fs.statSync(path).mode & 0o777;
  if ((mode & 0o002) !== 0) process.exit(12);
}
"""
        read = docker_run("run", "--rm", "--entrypoint", "node", tag, "-e", script)

        # Then: the runtime contract is explicit and does not rely on root-owned startup.
        assert inspect.returncode == 0, inspect.stdout + inspect.stderr
        assert inspect.stdout.strip() == "node"
        assert read.returncode == 0, read.stdout + read.stderr
    finally:
        _ = docker_run("image", "rm", "-f", tag, timeout=60)
