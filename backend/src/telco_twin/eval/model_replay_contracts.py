"""Typed contracts for exact offline recorded-model replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from telco_twin.domain._contract import Sha256Hex
    from telco_twin.eval.rules_baseline import DiagnosisCase


class SnapshotFilePin(Protocol):
    """One manifest file identity consumed by the offline model loader."""

    @property
    def path(self) -> str:
        """Return the revision-relative filename."""
        ...

    @property
    def sha256(self) -> Sha256Hex:
        """Return the exact expected content digest."""
        ...


class ReplayRuntime(Protocol):
    """Exact package-version fields needed for replay readiness."""

    @property
    def transformers(self) -> str:
        """Return the exact Transformers version."""
        ...

    @property
    def torch(self) -> str:
        """Return the exact Torch version."""
        ...

    @property
    def huggingface_hub(self) -> str:
        """Return the exact Hub client version."""
        ...


class ReplayInferenceProtocol(Protocol):
    """Deterministic worker fields needed by replay."""

    @property
    def threads(self) -> int:
        """Return the exact CPU thread count."""
        ...

    @property
    def max_output_units(self) -> int:
        """Return the exact generation bound."""
        ...


class ReplayManifest(Protocol):
    """Read-only model pins consumed without importing artifact contracts."""

    @property
    def revision(self) -> str:
        """Return the exact model revision."""
        ...

    @property
    def snapshot_files(self) -> Sequence[SnapshotFilePin]:
        """Return every loader-consumed file pin."""
        ...

    @property
    def runtime(self) -> ReplayRuntime:
        """Return exact package pins."""
        ...

    @property
    def inference(self) -> ReplayInferenceProtocol:
        """Return exact deterministic decoding pins."""
        ...


@dataclass(frozen=True, slots=True)
class ModelReplayResult:
    """Exact prompts, raw outputs, and verified model snapshot from one replay."""

    prompts: tuple[str, ...]
    raw_outputs: tuple[str, ...]
    model_snapshot_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class ModelWorkerRequest:
    """Exact local worker inputs with no acquisition authority."""

    cache_directory: Path
    prompts: tuple[str, ...]
    threads: int
    max_output_units: int


@dataclass(frozen=True, slots=True)
class ModelAvailability:
    """Truthful exact snapshot/runtime readiness without generation authority."""

    ready: bool
    reason: str
    model_snapshot_hash: Sha256Hex | None


@dataclass(frozen=True, slots=True)
class ModelSnapshotError(Exception):
    """The local model snapshot differs from its complete pinned manifest."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"model-snapshot-invalid: {self.detail}"


@dataclass(frozen=True, slots=True)
class ModelReplayUnavailableError(Exception):
    """Exact offline deterministic inference could not be replayed."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"model-replay-unavailable: {self.detail}"


class ModelReplayVerifier(Protocol):
    """Replay exact deterministic inference without acquiring dependencies or bytes."""

    def replay(
        self,
        manifest: ReplayManifest,
        cases: tuple[DiagnosisCase, ...],
        cache_root: Path,
    ) -> ModelReplayResult:
        """Return exact replayed prompts, outputs, and content-addressed snapshot."""
        ...


class ModelInferenceWorker(Protocol):
    """One isolated deterministic inference runner supplied by a CLI boundary."""

    def infer(self, request: ModelWorkerRequest) -> tuple[str, ...]:
        """Return raw decoded model outputs in prompt order."""
        ...
