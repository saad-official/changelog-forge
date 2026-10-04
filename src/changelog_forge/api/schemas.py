"""Request and response models for the HTTP API (spec section 6). These are the contract
the web app and the GitHub Action code against; OpenAPI at /api/docs is generated from them."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from ..models import Audience, ReleaseNotes, RunStatus, Usage, Verification


class RunCreate(BaseModel):
    repo: str = Field(
        description='"owner/name", or a full https://github.com/owner/name/compare/a...b URL',
        examples=["fastapi/fastapi"],
    )
    base: str | None = Field(default=None, description="Base ref (tag, branch or SHA).")
    head: str | None = Field(default=None, description="Head ref (tag, branch or SHA).")
    audiences: list[Audience] = Field(default_factory=lambda: ["user", "dev"])
    github_token: SecretStr | None = Field(
        default=None,
        description="Optional personal token for this run only. Never stored or logged.",
    )

    @field_validator("audiences")
    @classmethod
    def _non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one audience is required")
        return list(dict.fromkeys(value))


class RunCreated(BaseModel):
    id: str
    status: RunStatus
    commit_count: int | None = None
    process: Literal["qstash", "background", "client"] = Field(
        description='"client" means: POST process_url yourself, then subscribe to events_url.'
    )
    process_url: str
    events_url: str


class ProcessResult(BaseModel):
    id: str
    status: str
    resumable: bool = Field(
        description="True when the request's time budget ran out: POST /process again."
    )
    message: str = ""


class AudienceOutput(BaseModel):
    markdown: str
    json_doc: ReleaseNotes = Field(serialization_alias="json", validation_alias="json")

    model_config = {"populate_by_name": True}


class RunView(BaseModel):
    id: str
    status: RunStatus
    repo: str
    base: str
    head: str
    audiences: list[str]
    commit_count: int | None
    group_count: int | None
    usage: Usage | None
    outputs: dict[str, AudienceOutput]
    verified: Verification | None
    error: str | None
    prompt_versions: dict[str, Any]
    routing: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None


class Health(BaseModel):
    ok: bool
    version: str
    providers: dict[str, bool]
    db: bool
    store: Literal["postgres", "memory"]
    dispatch: Literal["qstash", "background", "client"]


class ErrorBody(BaseModel):
    code: str
    message: str
    retry_after: int | None = Field(default=None, description="Seconds; also a header.")
    field: str | None = Field(default=None, description="The request field at fault.")
    reset_at: datetime | None = None
