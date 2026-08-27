#!/usr/bin/env -S uv run --project backend python
"""Plan the exact GitHub-to-GCP WIF boundary and fail closed without authority."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError, run_command
from telco_twin.bootstrap.gcp_wif import CleanupReceipt, apply_wif

POOL_ID: Final = "github-actions"
PROVIDER_ID: Final = "github-oidc"
ISSUER: Final = "https://token.actions.githubusercontent.com"
REPOSITORIES: Final = (
    "oyeong011/telco-counterfactual-twin",
    "oyeong011/mcp-evidence-plane",
)
MAPPINGS: Final = (
    "google.subject=assertion.sub",
    "attribute.repository=assertion.repository",
    "attribute.repository_owner_id=assertion.repository_owner_id",
)


class WifPlan(BaseModel):
    """Persistent WIF configuration without credentials."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    project_number: str = Field(pattern=r"^[0-9]+$")
    deploy_service_account: str
    pool_id: Literal["github-actions"]
    provider_id: Literal["github-oidc"]
    issuer: Literal["https://token.actions.githubusercontent.com"]
    attribute_mappings: tuple[str, ...]
    attribute_condition: str
    principal_sets: tuple[str, str]
    temporary_probe_contract: tuple[str, ...]


def build_plan(project_id: str, project_number: str, owner_id: str) -> WifPlan:
    """Build the exact immutable-owner WIF plan."""
    condition = (
        f"assertion.repository_owner_id=='{owner_id}' && assertion.repository in "
        "['oyeong011/telco-counterfactual-twin','oyeong011/mcp-evidence-plane']"
    )
    principal_prefix = (
        "principalSet://iam.googleapis.com/projects/"
        f"{project_number}/locations/global/workloadIdentityPools/{POOL_ID}/attribute.repository/"
    )
    return WifPlan(
        project_id=project_id,
        project_number=project_number,
        deploy_service_account=f"skt-portfolio-deployer@{project_id}.iam.gserviceaccount.com",
        pool_id=POOL_ID,
        provider_id=PROVIDER_ID,
        issuer=ISSUER,
        attribute_mappings=MAPPINGS,
        attribute_condition=condition,
        principal_sets=(
            f"{principal_prefix}{REPOSITORIES[0]}",
            f"{principal_prefix}{REPOSITORIES[1]}",
        ),
        temporary_probe_contract=(
            "deny-condition-provider-and-binding:delete",
            "pubsub-topic:delete-and-restore-policy",
            "billing-budget-schemaVersion1.0:delete",
            "cloud-billing-publisher-edge:restore",
        ),
    )


def _apply_or_block(
    project_id: str | None,
    project_number: str | None,
    owner_id: str | None,
) -> None:
    blockers: list[str] = []
    if shutil.which("gcloud") is None:
        blockers.append("missing-command:gcloud")
    if shutil.which("gh") is None:
        blockers.append("missing-command:gh")
    required_environment = ("GCP_PROJECT_ID", "GCP_REGION", "GCP_BILLING_ACCOUNT_ID")
    blockers.extend(
        f"missing-env:{name}"
        for name in required_environment
        if not os.environ.get(name)
    )
    if blockers:
        rendered = '{\n  "status": "deployment-blocked",\n  "blockers": [\n'
        rendered += ",\n".join(f'    "{blocker}"' for blocker in blockers)
        rendered += "\n  ]\n}\n"
        typer.echo(rendered, nl=False)
        raise typer.Exit(code=2)
    resolved_project_id = project_id or os.environ["GCP_PROJECT_ID"]
    project_result = run_command(
        (
            "gcloud",
            "projects",
            "describe",
            resolved_project_id,
            "--format=value(projectNumber)",
        )
    )
    owner_result = run_command(("gh", "api", "users/oyeong011", "--jq", ".id"))
    resolved_project_number = project_number or project_result.stdout.strip()
    resolved_owner_id = owner_id or owner_result.stdout.strip()
    if (
        project_result.returncode != 0
        or owner_result.returncode != 0
        or not resolved_project_number.isdigit()
        or not resolved_owner_id.isdigit()
    ):
        typer.echo("authority-identifier-resolution-failed", err=True)
        raise typer.Exit(code=3)
    context = GcpContext(
        project_id=resolved_project_id,
        project_number=resolved_project_number,
        billing_account_id=os.environ["GCP_BILLING_ACCOUNT_ID"],
        owner_id=resolved_owner_id,
    )
    try:
        receipt = apply_wif(context)
    except ProvisioningError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=3) from None
    typer.echo(receipt.model_dump_json(indent=2))


def main(
    plan: Annotated[bool, typer.Option("--plan")] = False,
    apply: Annotated[bool, typer.Option("--apply")] = False,
    validate_cleanup: Annotated[Path | None, typer.Option("--validate-cleanup")] = None,
    project_id: Annotated[str | None, typer.Option("--project-id")] = None,
    project_number: Annotated[str | None, typer.Option("--project-number")] = None,
    owner_id: Annotated[str | None, typer.Option("--owner-id")] = None,
) -> None:
    """Emit a plan, validate cleanup, or apply only with live provider authority."""
    action_count = int(plan) + int(apply) + int(validate_cleanup is not None)
    if action_count != 1:
        typer.echo("exactly-one-action-required", err=True)
        raise typer.Exit(code=3)
    if validate_cleanup is not None:
        try:
            receipt = CleanupReceipt.model_validate_json(
                validate_cleanup.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError):
            typer.echo("invalid-cleanup-receipt", err=True)
            raise typer.Exit(code=3) from None
        if (
            not receipt.cleanup_complete
            or receipt.temporary_resources
            or not receipt.restored_bindings
        ):
            typer.echo("cleanup-incomplete", err=True)
            raise typer.Exit(code=3)
        typer.echo("cleanup-complete")
        return
    if apply:
        _apply_or_block(project_id, project_number, owner_id)
        return
    if project_id is None or project_number is None or owner_id is None:
        typer.echo("plan-identifiers-required", err=True)
        raise typer.Exit(code=3)
    result = build_plan(project_id, project_number, owner_id)
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    typer.run(main)
