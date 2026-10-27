from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from options_scout.core.models import UserProfile


class ScreenRequest(BaseModel):
    request_text: str | None = Field(default=None, max_length=4000)
    profile: UserProfile | None = None
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-]*$")


class ScreenResponse(BaseModel):
    thread_id: str
    status: Literal["running", "interrupted", "completed", "failed"]


class ResumeRequest(BaseModel):
    answer: dict[str, Any]


class RunStatus(BaseModel):
    thread_id: str
    status: Literal["running", "interrupted", "completed", "failed", "unknown"]
    current_node: str | None
    nodes_visited: list[str]
    interrupt: dict[str, Any] | None
    errors: list[str]
    partial: dict[str, Any]


class Health(BaseModel):
    status: str
    data_mode: str
    llm_mode: str
    sources: dict[str, str]
    version: str
