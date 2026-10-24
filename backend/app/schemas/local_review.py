"""Schemas for the local-review (VS Code extension) endpoint.

This is intentionally independent of the PR review models: local reviews have
no pull request, no GitHub installation, and (in the dev PoC) no database row.
Line numbers are 1-based inclusive; the extension converts them to VS Code's
0-based half-open ranges.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FileStatus = Literal["added", "modified", "deleted", "renamed"]
FindingSource = Literal["static", "agent"]

MAX_FILES = 25
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_DIFF_BYTES = 1024 * 1024


class LocalReviewSnapshotFile(BaseModel):
    path: str
    old_path: str | None = None
    status: FileStatus
    content_sha256: str | None = None
    size: int = Field(ge=0)

    @field_validator("path", "old_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value or value.startswith("/") or "\x00" in value:
            raise ValueError("file paths must be relative and non-empty")
        if any(part == ".." for part in value.split("/")):
            raise ValueError("file paths must not contain '..'")
        return value


class LocalReviewSnapshot(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    base_revision: str | None = None
    head_sha: str = ""
    branch: str | None = None
    captured_at: str = Field(min_length=1, max_length=100)
    files: list[LocalReviewSnapshotFile] = Field(default_factory=list)


class LocalReviewFile(BaseModel):
    path: str
    old_path: str | None = None
    status: FileStatus
    content: str
    content_sha256: str

    @field_validator("path", "old_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value or value.startswith("/") or "\x00" in value:
            raise ValueError("file paths must be relative and non-empty")
        if any(part == ".." for part in value.split("/")):
            raise ValueError("file paths must not contain '..'")
        return value


class LocalReviewRequest(BaseModel):
    schema_version: Literal[1]
    snapshot: LocalReviewSnapshot
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    diff: str
    language: str = Field(default="text", max_length=50)
    files: list[LocalReviewFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_limits(self) -> "LocalReviewRequest":
        if not self.diff.strip() and not self.files:
            raise ValueError("a review needs a diff or at least one file")

        if len(self.files) > MAX_FILES:
            raise ValueError(f"too many files (maximum {MAX_FILES})")

        total = 0
        for file in self.files:
            size = len(file.content.encode("utf-8"))
            if size > MAX_FILE_BYTES:
                raise ValueError(
                    f"file {file.path!r} exceeds the {MAX_FILE_BYTES}-byte limit"
                )
            total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"source payload exceeds the {MAX_TOTAL_BYTES}-byte limit")

        if len(self.diff.encode("utf-8")) > MAX_DIFF_BYTES:
            raise ValueError(f"diff exceeds the {MAX_DIFF_BYTES}-byte limit")
        return self


class LocalReviewFinding(BaseModel):
    id: str
    source: FindingSource
    native_severity: str
    severity: str
    file_path: str
    old_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    message: str
    body: str
    suggestion: str | None = None
    snippet: str | None = None
    tool: str | None = None
    rule_id: str | None = None
    category: str | None = None
    also_detected_by: list[str] = Field(default_factory=list)
    reason: str | None = None


class LocalReviewStatistics(BaseModel):
    files_reviewed: int = 0
    issues_found: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)


class LocalReviewResult(BaseModel):
    schema_version: Literal[1] = 1
    snapshot: LocalReviewSnapshot
    summary: str
    overall_severity: str
    statistics: LocalReviewStatistics
    findings: list[LocalReviewFinding] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    agent_failures: list[str] = Field(default_factory=list)
    diff_truncated: bool = False
    duration_ms: int = 0
