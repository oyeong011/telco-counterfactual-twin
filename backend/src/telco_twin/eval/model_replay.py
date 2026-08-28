"""Exact-cache model replay contracts and complete snapshot verification."""

from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from telco_twin.eval.model_input import recorded_model_prompts
from telco_twin.eval.model_replay_contracts import (
    ModelAvailability,
    ModelInferenceWorker,
    ModelReplayResult,
    ModelReplayUnavailableError,
    ModelSnapshotError,
    ModelWorkerRequest,
    ReplayManifest,
    SnapshotFilePin,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from telco_twin.domain._contract import Sha256Hex
    from telco_twin.eval.rules_baseline import DiagnosisCase

PASSIVE_REPOSITORY_FILES: Final = frozenset({".gitattributes", "LICENSE", "README.md"})
LOCAL_CACHE_DIRECTORY: Final = ".cache"
QWEN_WORKER_CODE: Final = r"""
import json, sys, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
p = json.load(sys.stdin)
torch.set_num_threads(p["threads"])
t = AutoTokenizer.from_pretrained(p["cache"], local_files_only=True)
m = AutoModelForCausalLM.from_pretrained(
    p["cache"], local_files_only=True, dtype=torch.float32, device_map="cpu"
)
labels = []
for prompt in p["prompts"]:
    text = t.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
    )
    inputs = t([text], return_tensors="pt")
    generated = m.generate(**inputs, do_sample=False, max_new_tokens=p["max_output_units"])
    tail = generated[0][inputs.input_ids.shape[1]:]
    labels.append(t.decode(tail, skip_special_tokens=True).strip())
json.dump({"labels": labels}, sys.stdout, sort_keys=True)
"""


def model_cache_directory(cache_root: Path, revision: str) -> Path:
    """Resolve one shared cache-root contract to its exact revision directory."""
    return cache_root / revision


def _file_sha256(path: Path) -> Sha256Hex:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_digest(pins: Sequence[SnapshotFilePin]) -> Sha256Hex:
    digest = hashlib.sha256()
    for pin in pins:
        for value in (pin.path, pin.sha256):
            encoded = value.encode()
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def verify_model_snapshot(
    cache_directory: Path,
    pins: Sequence[SnapshotFilePin],
) -> Sha256Hex:
    """Verify every loader-consumed file and reject any unpinned top-level input."""
    names = tuple(pin.path for pin in pins)
    if len(set(names)) != len(names):
        detail = "duplicate pinned file"
        raise ModelSnapshotError(detail)
    allowed = set(names) | set(PASSIVE_REPOSITORY_FILES) | {LOCAL_CACHE_DIRECTORY}
    try:
        entries = tuple(cache_directory.iterdir())
    except OSError as error:
        detail = "revision directory missing"
        raise ModelSnapshotError(detail) from error
    if any(entry.is_symlink() for entry in entries):
        detail = "top-level symlink present"
        raise ModelSnapshotError(detail)
    unexpected = sorted(entry.name for entry in entries if entry.name not in allowed)
    if unexpected:
        detail = f"unpinned top-level entries: {','.join(unexpected)}"
        raise ModelSnapshotError(detail)
    for pin in pins:
        path = cache_directory / pin.path
        if not path.is_file():
            detail = f"required file missing: {pin.path}"
            raise ModelSnapshotError(detail)
        if _file_sha256(path) != pin.sha256:
            detail = f"file hash mismatch: {pin.path}"
            raise ModelSnapshotError(detail)
    return _snapshot_digest(pins)


def inspect_model_availability(
    manifest: ReplayManifest,
    cache_root: Path,
) -> ModelAvailability:
    """Verify complete snapshot and exact installed runtime without loading the model."""
    cache_directory = model_cache_directory(cache_root, manifest.revision)
    try:
        snapshot_hash = verify_model_snapshot(cache_directory, manifest.snapshot_files)
    except ModelSnapshotError:
        return ModelAvailability(
            ready=False,
            reason="exact-model-snapshot-unavailable",
            model_snapshot_hash=None,
        )
    required = (
        ("transformers", manifest.runtime.transformers),
        ("torch", manifest.runtime.torch),
        ("huggingface-hub", manifest.runtime.huggingface_hub),
    )
    versions: list[bool] = []
    for package, expected in required:
        try:
            versions.append(importlib.metadata.version(package) == expected)
        except importlib.metadata.PackageNotFoundError:
            versions.append(False)
    runtime_ready = sys.version_info[:2] == (3, 12) and all(versions)
    return ModelAvailability(
        ready=runtime_ready,
        reason="exact-cache-and-runtime-ready" if runtime_ready else "runtime-pin-missing",
        model_snapshot_hash=snapshot_hash,
    )


@dataclass(frozen=True, slots=True)
class ExactModelReplayVerifier:
    """Replay all fixed prompts through an injected offline inference worker."""

    worker: ModelInferenceWorker

    def replay(
        self,
        manifest: ReplayManifest,
        cases: tuple[DiagnosisCase, ...],
        cache_root: Path,
    ) -> ModelReplayResult:
        """Require exact runtime/snapshot and reject drift across generation."""
        availability = inspect_model_availability(manifest, cache_root)
        snapshot_before = availability.model_snapshot_hash
        if not availability.ready or snapshot_before is None:
            raise ModelReplayUnavailableError(availability.reason)
        cache_directory = model_cache_directory(cache_root, manifest.revision)
        prompts = recorded_model_prompts(cases)
        raw_outputs = self.worker.infer(
            ModelWorkerRequest(
                cache_directory=cache_directory,
                prompts=prompts,
                threads=manifest.inference.threads,
                max_output_units=manifest.inference.max_output_units,
            )
        )
        try:
            snapshot_after = verify_model_snapshot(cache_directory, manifest.snapshot_files)
        except ModelSnapshotError as error:
            raise ModelReplayUnavailableError(error.detail) from error
        if len(raw_outputs) != len(cases) or snapshot_before != snapshot_after:
            detail = "model-worker-evidence-drift"
            raise ModelReplayUnavailableError(detail)
        return ModelReplayResult(
            prompts=prompts,
            raw_outputs=raw_outputs,
            model_snapshot_hash=snapshot_after,
        )
