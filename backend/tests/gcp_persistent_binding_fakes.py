"""Policy transformations for persistent binding transaction fakes."""

from __future__ import annotations

from telco_twin.bootstrap.gcp_iam_contract import IamBinding, IamCondition, IamPolicy


def _condition(arguments: tuple[str, ...]) -> IamCondition:
    payload = next(
        argument.removeprefix("--condition=")
        for argument in arguments
        if argument.startswith("--condition=")
    )
    return IamCondition.model_validate(
        {part.split("=", 1)[0]: part.split("=", 1)[1] for part in payload.split(",")}
    )


def add_binding(policy: str, arguments: tuple[str, ...]) -> str:
    """Append the exact conditional edge represented by one fake argv."""
    parsed = IamPolicy.model_validate_json(policy)
    member = next(part.split("=", 1)[1] for part in arguments if part.startswith("--member="))
    binding = IamBinding(
        role="roles/iam.workloadIdentityUser",
        members=(member,),
        condition=_condition(arguments),
    )
    return parsed.model_copy(update={"bindings": (*parsed.bindings, binding)}).model_dump_json()


def remove_binding(policy: str, arguments: tuple[str, ...]) -> str:
    """Remove only the role/member/condition edge represented by fake argv."""
    parsed = IamPolicy.model_validate_json(policy)
    member = next(part.split("=", 1)[1] for part in arguments if part.startswith("--member="))
    condition = _condition(arguments)
    return parsed.model_copy(
        update={
            "bindings": tuple(
                binding
                for binding in parsed.bindings
                if not (member in binding.members and binding.condition == condition)
            )
        }
    ).model_dump_json()
