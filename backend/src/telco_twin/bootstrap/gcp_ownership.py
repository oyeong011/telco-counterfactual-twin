"""Run-scoped ownership fingerprints for reversible GCP mutations."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Final

from telco_twin.bootstrap.gcp_commands import ProvisioningError

MANAGED_BY: Final = "telco-twin-preflight"
MANAGED_BY_MARKER: Final = f"managed-by={MANAGED_BY}"
RUN_ID_BYTES: Final = 32
FINGERPRINT_BYTES: Final = 16
FINGERPRINT_LENGTH: Final = 25
BASE36_ALPHABET: Final = "0123456789abcdefghijklmnopqrstuvwxyz"
FINGERPRINT_PATTERN: Final = re.compile(r"^[0-9a-z]{25}$")


def _base36_fingerprint(value: bytes) -> str:
    number = int.from_bytes(value, byteorder="big", signed=False)
    encoded = ""
    while number:
        number, remainder = divmod(number, len(BASE36_ALPHABET))
        encoded = BASE36_ALPHABET[remainder] + encoded
    return encoded.rjust(FINGERPRINT_LENGTH, "0")


@dataclass(frozen=True, slots=True)
class OperationOwnership:
    """Non-secret operation identifier embedded in provider metadata."""

    fingerprint: str

    def __post_init__(self) -> None:
        """Reject values that cannot fit every supported metadata surface."""
        if FINGERPRINT_PATTERN.fullmatch(self.fingerprint) is None:
            code = "operation-fingerprint-invalid"
            raise ProvisioningError(code)

    @property
    def marker(self) -> str:
        """Return the exact managed-by and current-operation marker."""
        return f"{MANAGED_BY_MARKER};op={self.fingerprint}"

    @property
    def labels(self) -> str:
        """Return the exact Pub/Sub label argument payload."""
        return f"managed-by={MANAGED_BY},operation-fingerprint={self.fingerprint}"

    @classmethod
    def from_marker(cls, marker: str) -> OperationOwnership:
        """Parse only the exact managed-by marker emitted by this package."""
        prefix = f"{MANAGED_BY_MARKER};op="
        if not marker.startswith(prefix):
            code = "operation-marker-invalid"
            raise ProvisioningError(code)
        return cls(marker.removeprefix(prefix))


@dataclass(frozen=True, slots=True)
class RunOwnership:
    """Cryptographically random run identifier used only for derivation."""

    run_id: bytes

    def __post_init__(self) -> None:
        """Require a full 256-bit run identifier."""
        if len(self.run_id) != RUN_ID_BYTES:
            code = "run-id-invalid"
            raise ProvisioningError(code)

    @classmethod
    def generate(cls) -> RunOwnership:
        """Create one run identifier using the operating system CSPRNG."""
        return cls(secrets.token_bytes(RUN_ID_BYTES))

    def for_operation(self, operation: str) -> OperationOwnership:
        """Derive a stable 128-bit fingerprint for one named mutation."""
        if not operation:
            code = "operation-name-invalid"
            raise ProvisioningError(code)
        digest = hashlib.sha256(self.run_id + b"\x00" + operation.encode()).digest()
        return OperationOwnership(_base36_fingerprint(digest[:FINGERPRINT_BYTES]))
