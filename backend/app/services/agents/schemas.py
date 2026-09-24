"""Schemas for multi-agent code review orchestration."""

from typing import Optional

from pydantic import BaseModel, Field


class ReviewContext(BaseModel):
    """Shared pull request context passed to every review agent."""

    pr_title: str
    pr_body: Optional[str] = None
    diff: str
    language: str = "text"


class AgentComment(BaseModel):
    """Single specialist-agent finding."""

    file_path: str = ""
    line_number: Optional[int] = None
    severity: str = "info"
    category: str = "general"
    body: str = ""
    suggestion: Optional[str] = None


class AgentResult(BaseModel):
    """Specialist-agent output contract."""

    agent: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    comments: list[AgentComment] = Field(default_factory=list)


class ReviewStatistics(BaseModel):
    """Statistics included in the final review result."""

    files_reviewed: int = 0
    issues_found: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)


class ReviewResult(BaseModel):
    """Final review result matching the existing GeminiService contract."""

    summary: str = ""
    overall_severity: str = "info"
    comments: list[AgentComment] = Field(default_factory=list)
    statistics: ReviewStatistics = Field(default_factory=ReviewStatistics)
    usage: Optional[dict[str, int]] = None
