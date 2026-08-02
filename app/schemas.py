from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WeekIn(BaseModel):
    id: str | None = None
    week: int | None = None
    session: int | None = None
    session_no: int | None = None
    unit: str = ""
    unit_title: str = ""
    week_title: str = ""
    title: str | None = None
    author: str = ""
    author_role: str = ""
    updatedAt: str | None = None


class FolderIn(BaseModel):
    id: str | None = None
    name: str = ""
    parentId: str | None = None
    parent_id: str | None = None
    sort: int | None = None
    sort_order: int | None = None
    updatedAt: str | None = None


class CourseIn(BaseModel):
    id: str | None = None
    vendor: str = ""
    course: str = ""
    name: str | None = None
    edu: str = ""
    edu_type: str | None = None
    target: str = ""
    weekCount: int | None = None
    week_count: int | None = None
    folderId: str | None = None
    folder_id: str | None = None
    prompt: str = ""
    sharedSetup: dict[str, Any] | None = None
    units: list[WeekIn] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class CourseLibIn(BaseModel):
    v: int = 1
    folders: list[FolderIn] = Field(default_factory=list)
    courses: list[CourseIn] = Field(default_factory=list)


class CourseLibOut(BaseModel):
    v: int = 1
    folders: list[dict[str, Any]] = Field(default_factory=list)
    courses: list[dict[str, Any]]
    source: str = "db"
