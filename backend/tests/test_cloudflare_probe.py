from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx2
import pytest

from telco_twin.bootstrap.cloudflare_probe import (
    CloudflareContext,
    CloudflareTransports,
    probe_cloudflare,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_SHA = "d" * 40
CLOUDFLARE_CREDENTIAL = "fabricated-cloudflare-token"


def install_wrangler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeeds: bool,
) -> tuple[Path, Path]:
    """Install a fake Wrangler executable that records only argv."""
    command_log = tmp_path / "wrangler.log"
    wrangler = tmp_path / "wrangler"
    exit_code = 0 if succeeds else 1
    _ = wrangler.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_WRANGLER_LOG"\nexit {exit_code}\n',
        encoding="utf-8",
    )
    wrangler.chmod(0o755)
    monkeypatch.setenv("FAKE_WRANGLER_LOG", str(command_log))
    return wrangler, command_log


def test_cloudflare_probe_verifies_two_deployments_rollback_content_and_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    wrangler, command_log = install_wrangler(tmp_path, monkeypatch, succeeds=True)
    deployment_list_calls = 0
    api_requests: list[str] = []

    def api_handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal deployment_list_calls
        api_requests.append(f"{request.method} {request.url.path}")
        assert request.headers["authorization"] == f"Bearer {CLOUDFLARE_CREDENTIAL}"
        path = request.url.path
        if path.endswith("/user/tokens/verify"):
            payload = {"success": True, "result": {"id": "token-id", "status": "active"}}
        elif path.endswith("/accounts/account-id"):
            payload = {"success": True, "result": {"id": "account-id"}}
        elif path.endswith("/pages/projects") and request.method == "GET":
            payload = {"success": True, "result": ()}
        elif path.endswith("/pages/projects") and request.method == "POST":
            payload = {
                "success": True,
                "result": {"id": "project-id", "name": "twin-preflight-test"},
            }
        elif path.endswith("/deployments"):
            deployment_list_calls += 1
            deployments = (
                [{"id": "deployment-one"}]
                if deployment_list_calls == 1
                else [{"id": "deployment-two"}, {"id": "deployment-one"}]
            )
            payload = {"success": True, "result": deployments}
        elif path.endswith("/deployments/deployment-one/rollback"):
            payload = {"success": True, "result": {"id": "deployment-one"}}
        elif path.endswith("/twin-preflight-test") and request.method == "DELETE":
            payload = {"success": True, "result": None}
        else:
            return httpx2.Response(404, content=b"{}", request=request)
        return httpx2.Response(200, content=json.dumps(payload).encode(), request=request)

    def public_handler(request: httpx2.Request) -> httpx2.Response:
        assert "authorization" not in request.headers
        assert str(request.url) == "https://twin-preflight-test.pages.dev"
        return httpx2.Response(200, content=b"version-one", request=request)

    context = CloudflareContext(
        account_id="account-id",
        api_token=CLOUDFLARE_CREDENTIAL,
        source_sha=SOURCE_SHA,
        wrangler_command=str(wrangler),
    )
    transports = CloudflareTransports(
        api=httpx2.MockTransport(api_handler),
        public=httpx2.MockTransport(public_handler),
    )

    # When
    receipt = probe_cloudflare(context, transports, suffix="test")

    # Then
    assert receipt.project_id == "project-id"
    assert receipt.deployment_ids == ("deployment-one", "deployment-two")
    assert receipt.rollback_deployment_id == "deployment-one"
    assert receipt.cleanup_complete is True
    assert CLOUDFLARE_CREDENTIAL not in receipt.model_dump_json()
    commands = command_log.read_text(encoding="utf-8")
    assert commands.count("pages deploy") == 2
    assert "--project-name=twin-preflight-test" in commands
    assert f"--commit-hash={SOURCE_SHA}" in commands
    expected_delete = "DELETE /client/v4/accounts/account-id/pages/projects/twin-preflight-test"
    assert api_requests[-1] == expected_delete


def test_cloudflare_probe_rejects_token_verify_http_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    wrangler, _ = install_wrangler(tmp_path, monkeypatch, succeeds=True)

    def api_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, content=b"{}", request=request)

    transports = CloudflareTransports(
        api=httpx2.MockTransport(api_handler),
        public=httpx2.MockTransport(api_handler),
    )
    context = CloudflareContext("account-id", CLOUDFLARE_CREDENTIAL, SOURCE_SHA, str(wrangler))

    # When / Then
    with pytest.raises(ProviderProbeError, match="cloudflare-token-verify-http-403"):
        _ = probe_cloudflare(context, transports, suffix="test")


def test_cloudflare_probe_cleans_project_when_wrangler_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    wrangler, _ = install_wrangler(tmp_path, monkeypatch, succeeds=False)
    deleted: list[bool] = []

    def api_handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/user/tokens/verify"):
            content = b'{"success":true,"result":{"id":"token-id","status":"active"}}'
        elif path.endswith("/accounts/account-id"):
            content = b'{"success":true,"result":{"id":"account-id"}}'
        elif path.endswith("/pages/projects") and request.method == "GET":
            content = b'{"success":true,"result":[]}'
        elif path.endswith("/pages/projects") and request.method == "POST":
            content = b'{"success":true,"result":{"id":"project-id","name":"twin-preflight-test"}}'
        elif request.method == "DELETE":
            deleted.append(True)
            content = b'{"success":true,"result":null}'
        else:
            return httpx2.Response(404, content=b"{}", request=request)
        return httpx2.Response(200, content=content, request=request)

    transports = CloudflareTransports(
        api=httpx2.MockTransport(api_handler),
        public=httpx2.MockTransport(api_handler),
    )
    context = CloudflareContext("account-id", CLOUDFLARE_CREDENTIAL, SOURCE_SHA, str(wrangler))

    # When / Then
    with pytest.raises(ProviderProbeError, match="cloudflare-deploy-failed"):
        _ = probe_cloudflare(context, transports, suffix="test")
    assert deleted == [True]


def test_cloudflare_probe_makes_cleanup_failure_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    wrangler, _ = install_wrangler(tmp_path, monkeypatch, succeeds=False)

    def api_handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.method == "DELETE":
            return httpx2.Response(500, content=b"{}", request=request)
        if path.endswith("/user/tokens/verify"):
            content = b'{"success":true,"result":{"id":"token-id","status":"active"}}'
        elif path.endswith("/accounts/account-id"):
            content = b'{"success":true,"result":{"id":"account-id"}}'
        elif path.endswith("/pages/projects") and request.method == "GET":
            content = b'{"success":true,"result":[]}'
        else:
            content = b'{"success":true,"result":{"id":"project-id","name":"twin-preflight-test"}}'
        return httpx2.Response(200, content=content, request=request)

    transports = CloudflareTransports(
        api=httpx2.MockTransport(api_handler),
        public=httpx2.MockTransport(api_handler),
    )
    context = CloudflareContext("account-id", CLOUDFLARE_CREDENTIAL, SOURCE_SHA, str(wrangler))

    # When / Then
    with pytest.raises(ProviderProbeError, match="cloudflare-cleanup-failed"):
        _ = probe_cloudflare(context, transports, suffix="test")
