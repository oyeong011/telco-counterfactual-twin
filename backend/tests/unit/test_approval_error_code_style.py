from __future__ import annotations

import re

from telco_twin.domain.approval import ContractErrorCode


def test_all_approval_error_codes_use_stable_kebab_case() -> None:
    pattern = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    assert all(pattern.fullmatch(code.value) is not None for code in ContractErrorCode)
