from __future__ import annotations

import pytest
from pydantic import ValidationError

from telco_twin.domain.scenario import Scenario
from telco_twin.domain.topology import Topology

from .contract_payloads import JsonObject, topology_payload, valid_domain_cases


@pytest.mark.parametrize(
    ("key", "expected_code"),
    [
        ("emailAddress", "pii_shaped_key"),
        ("phone_number", "pii_shaped_key"),
        ("imsiHash", "pii_shaped_key"),
        ("msisdn_value", "pii_shaped_key"),
        ("customer_id", "pii_shaped_key"),
        ("subscriberIdentifier", "pii_shaped_key"),
        ("shellCommand", "authority_shaped_key"),
        ("executeAction", "authority_shaped_key"),
        ("execution_plan", "authority_shaped_key"),
        ("pushPayload", "authority_shaped_key"),
        ("arbitraryURL", "authority_shaped_key"),
        ("revokeReason", "authority_shaped_key"),
        ("revocation_status", "authority_shaped_key"),
        ("apiSecret", "secret_shaped_key"),
        ("accessToken", "secret_shaped_key"),
        ("dbPassword", "secret_shaped_key"),
        ("subscriberid", "pii_shaped_key"),
        ("SubscriberID", "pii_shaped_key"),
        ("customerid", "pii_shaped_key"),
        ("emailaddress", "pii_shaped_key"),
        ("shellcommand", "authority_shaped_key"),
        ("pushpayload", "authority_shaped_key"),
        ("applytonetwork", "authority_shaped_key"),
        ("accesstoken", "secret_shaped_key"),
        ("AccessToken", "secret_shaped_key"),
    ],
)
def test_root_contract_rejects_composite_semantic_keys(
    key: str,
    expected_code: str,
) -> None:
    _, payload = next(case for case in valid_domain_cases() if case[0] is Scenario)
    payload[key] = "synthetic"

    with pytest.raises(ValidationError) as caught:
        _ = Scenario.model_validate(payload)

    assert expected_code in {item["type"] for item in caught.value.errors()}


def test_extensions_reject_composite_customer_identifier() -> None:
    _, payload = next(case for case in valid_domain_cases() if case[0] is Scenario)
    payload["extensions"] = {
        "schema_version": "1.0",
        "values": {"customerIdentifier": "synthetic"},
    }

    with pytest.raises(ValidationError) as caught:
        _ = Scenario.model_validate(payload)

    assert "pii_shaped_key" in {item["type"] for item in caught.value.errors()}


def test_nested_properties_reject_composite_subscriber_identifier() -> None:
    payload = topology_payload()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    first = nodes[0]
    assert isinstance(first, dict)
    first["attributes"] = {"subscriberIdentifier": "synthetic"}

    with pytest.raises(ValidationError) as caught:
        _ = Topology.model_validate(payload)

    assert "pii_shaped_key" in {item["type"] for item in caught.value.errors()}


def test_extensions_reject_separator_free_customer_identifier() -> None:
    _, payload = next(case for case in valid_domain_cases() if case[0] is Scenario)
    payload["extensions"] = {
        "schema_version": "1.0",
        "values": {"customerid": "synthetic"},
    }

    with pytest.raises(ValidationError) as caught:
        _ = Scenario.model_validate(payload)

    assert "pii_shaped_key" in {item["type"] for item in caught.value.errors()}


def test_nested_properties_reject_separator_free_shell_command() -> None:
    payload = topology_payload()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    first = nodes[0]
    assert isinstance(first, dict)
    first["attributes"] = {"shellcommand": "synthetic"}

    with pytest.raises(ValidationError) as caught:
        _ = Topology.model_validate(payload)

    assert "authority_shaped_key" in {item["type"] for item in caught.value.errors()}


def test_legitimate_synthetic_composite_keys_remain_allowed() -> None:
    payload: JsonObject = topology_payload()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    first = nodes[0]
    assert isinstance(first, dict)
    first["attributes"] = {
        "ue_cohort_id": "ue-cohort-0001",
        "shellfish_count": 1,
        "tokenization_mode": "synthetic",
        "executioner_state": "idle",
    }

    topology = Topology.model_validate(payload)

    assert topology.config_history[0].config_version == "config-0001"
    assert topology.nodes[0].attributes["ue_cohort_id"] == "ue-cohort-0001"
