"""Task 9 visual evidence byte-integrity and reviewer-receipt contracts."""
# pyright: reportUnnecessaryComparison=false

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal, assert_never

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from .task9_visual_qa_fixtures import (
    assert_visual,
    nonconsecutive_idat_png_bytes,
    palette_png_bytes,
    unknown_critical_png_bytes,
    visual_fixture,
    write_png,
)
from .task9_visual_review_fixtures import (
    VisualManifest,
    bind_reviewer_receipts,
    canonical_bytes,
    json_object,
)

PngMutation = Literal["missing-plte", "unknown-critical", "split-idat"]


def test_visual_manifest_requires_external_reviewer_receipts(tmp_path: Path) -> None:
    # Given: a manifest that invents an arbitrary reviewer identity.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    manifest["reviewers"][0]["role"] = "self-declared-reviewer"
    _ = manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: reviewer attribution is checked against the external receipt.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: an unbacked arbitrary ID cannot count as an independent approval.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-attribution:" in result.stderr


def test_visual_manifest_requires_distinct_reviewer_runs(tmp_path: Path) -> None:
    # Given: both required roles claim the same external review execution.
    manifest_path, _, now = visual_fixture(tmp_path, shared_run_id=True)
    # When: independence is checked.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: role labels cannot turn one run into two approvals.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-independence:" in result.stderr


def test_visual_manifest_requires_distinct_prebound_reviewer_keys(tmp_path: Path) -> None:
    # Given: both roles are pre-bound to the same Ed25519 public key.
    manifest_path, _, now = visual_fixture(tmp_path, shared_key=True)
    # When: reviewer root independence is checked.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: two role labels cannot turn one signing root into two reviewers.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-root-independence:" in result.stderr


def test_visual_manifest_rejects_forged_reviewer_receipt_hash(tmp_path: Path) -> None:
    # Given: a valid receipt is modified after its hash is recorded.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    receipt = manifest_path.parent / manifest["reviewers"][0]["receipt_path"]
    _ = receipt.write_text("{}\n", encoding="utf-8")
    # When: the receipt hash and strict payload are checked.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: the approval evidence fails closed.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-receipt-hash:" in result.stderr


def test_visual_manifest_rejects_rehashed_but_invalid_signature(tmp_path: Path) -> None:
    # Given: an attacker replaces a signature and updates every author-controlled hash.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    reviewer = manifest["reviewers"][0]
    receipt_path = manifest_path.parent / reviewer["receipt_path"]
    receipt = json_object(receipt_path.read_bytes())
    receipt["signature"] = "A" * 86
    encoded = canonical_bytes(receipt)
    _ = receipt_path.write_bytes(encoded)
    reviewer["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    _ = manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    # When: approval authenticity is checked against the pre-bound public root.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: recomputing manifest hashes cannot forge an Ed25519 approval.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-signature:" in result.stderr


def test_visual_manifest_rejects_tampered_trust_descriptor(tmp_path: Path) -> None:
    # Given: a valid build-info followed by an altered public-root descriptor.
    manifest_path, _, now = visual_fixture(tmp_path)
    _ = (manifest_path.parent / "reviewer-trust.json").write_text("{}\n", encoding="utf-8")
    # When: the validator compares trust roots to build identity.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: reviewer keys cannot be supplied by the manifest author after the build.
    assert result.returncode != 0
    assert "visual-qa-error:reviewer-trust-hash:" in result.stderr


def _replace_first_capture(manifest_path: Path, manifest: VisualManifest, encoded: bytes) -> None:
    capture = manifest["captures"][0]
    capture_path = manifest_path.parent / capture["path"]
    _ = capture_path.write_bytes(encoded)
    capture["sha256"] = hashlib.sha256(encoded).hexdigest()
    bind_reviewer_receipts(manifest_path, manifest)


def test_png_decoder_accepts_indexed_image_with_palette(tmp_path: Path) -> None:
    # Given: a complete indexed PNG whose PLTE precedes IDAT.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    _replace_first_capture(manifest_path, manifest, palette_png_bytes(1280, 800, include_plte=True))
    # When: the immutable capture snapshot is validated.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: indexed screenshots with a valid palette are accepted.
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutation",
    ["missing-plte", "unknown-critical", "split-idat"],
)
def test_png_decoder_rejects_invalid_critical_structure(
    tmp_path: Path, mutation: PngMutation
) -> None:
    # Given: a CRC-valid PNG violating one critical chunk ordering rule.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    match mutation:
        case "missing-plte":
            encoded = palette_png_bytes(1280, 800, include_plte=False)
        case "unknown-critical":
            encoded = unknown_critical_png_bytes(1280, 800)
        case "split-idat":
            encoded = nonconsecutive_idat_png_bytes(1280, 800)
        case unreachable:
            assert_never(unreachable)
    _replace_first_capture(manifest_path, manifest, encoded)
    # When: immutable parsing evaluates the hostile capture.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: critical chunk violations fail closed.
    assert result.returncode != 0
    assert "visual-qa-error:invalid-png:" in result.stderr


def test_visual_manifest_rejects_trailing_png_bytes(tmp_path: Path) -> None:
    # Given: a complete PNG with bytes appended after IEND and fully rebound metadata.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    capture = manifest["captures"][0]
    capture_path = manifest_path.parent / capture["path"]
    forged = capture_path.read_bytes() + b"trailing"
    _ = capture_path.write_bytes(forged)
    capture["sha256"] = hashlib.sha256(forged).hexdigest()
    bind_reviewer_receipts(manifest_path, manifest)
    # When: complete PNG chunk structure is asserted.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: valid headers cannot hide trailing bytes.
    assert result.returncode != 0
    assert "visual-qa-error:invalid-png:" in result.stderr


def test_visual_manifest_rejects_missing_idat_and_iend(tmp_path: Path) -> None:
    # Given: a PNG reduced to its signature and IHDR prefix.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    capture = manifest["captures"][0]
    capture_path = manifest_path.parent / capture["path"]
    truncated = capture_path.read_bytes()[:33]
    _ = capture_path.write_bytes(truncated)
    capture["sha256"] = hashlib.sha256(truncated).hexdigest()
    bind_reviewer_receipts(manifest_path, manifest)
    # When: the capture is decoded.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: IDAT and terminal IEND are mandatory.
    assert result.returncode != 0
    assert "visual-qa-error:invalid-png:" in result.stderr


def test_visual_manifest_rejects_label_only_mobile_geometry(tmp_path: Path) -> None:
    # Given: a mobile-labelled capture containing desktop-sized pixels and metadata.
    manifest_path, manifest, now = visual_fixture(tmp_path)
    capture = next(item for item in manifest["captures"] if item.get("viewport") == "mobile")
    capture_path = manifest_path.parent / capture["path"]
    capture["width"] = 1280
    capture["sha256"] = write_png(capture_path, 1280, 800)
    bind_reviewer_receipts(manifest_path, manifest)
    # When: viewport geometry is checked independently from its label.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: desktop geometry cannot pass as mobile evidence.
    assert result.returncode != 0
    assert "visual-qa-error:viewport-geometry:" in result.stderr


def test_visual_manifest_valid_check_is_non_mutating(tmp_path: Path) -> None:
    # Given: a complete visual evidence directory.
    manifest_path, _, now = visual_fixture(tmp_path)
    before = {
        path.relative_to(manifest_path.parent): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in manifest_path.parent.rglob("*")
        if path.is_file()
    }
    # When: the assertion succeeds.
    result = assert_visual(manifest_path, manifest_path.parent / "build-info.json", now)
    # Then: validation publishes or rewrites nothing.
    assert result.returncode == 0, result.stdout + result.stderr
    after = {
        path.relative_to(manifest_path.parent): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in manifest_path.parent.rglob("*")
        if path.is_file()
    }
    assert after == before
