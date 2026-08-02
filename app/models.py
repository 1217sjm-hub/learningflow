"""SQLAlchemy 모델 — 브라우저 JSON/localStorage 정본을 DB로 옮기기 위한 스키마.

매핑 상세: server/MAPPING.md
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """간단 계정 (테스트용 회원가입·로그인)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessLog(Base):
    """로그인·로그아웃 등 접속 기록."""

    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(80), default="")
    action: Mapped[str] = mapped_column(String(40), default="login")  # login|logout
    ip: Mapped[str] = mapped_column(String(80), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UsageEvent(Base):
    """Claude 호출 토큰·비용 (클라이언트가 보고)."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(40), default="claude")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_create_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usd: Mapped[float] = mapped_column(Float, default=0.0)
    krw: Mapped[int] = mapped_column(Integer, default=0)
    usd_krw_rate: Mapped[float] = mapped_column(Float, default=1350.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CourseFolder(Base):
    """과정 폴더. ← lf_course_lib folders[] (년도·개인명 등 사용자 지정, 중첩 가능)"""

    __tablename__ = "course_folders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    courses: Mapped[list["Course"]] = relationship(back_populates="folder")


class Course(Base):
    """과정 메타. ← lf_course_lib_v1.courses[]"""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vendor: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(300), default="")
    edu_type: Mapped[str] = mapped_column(String(120), default="")
    target: Mapped[str] = mapped_column(String(300), default="")
    week_count: Mapped[int] = mapped_column(Integer, default=0)
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 레거시 기타 필드(프롬프트 백업 등). 과정 셋팅 본문은 course_setups / course_page_rows.
    overrides_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    folder: Mapped[CourseFolder | None] = relationship(back_populates="courses")
    weeks: Mapped[list[Week]] = relationship(back_populates="course", cascade="all, delete-orphan")
    cases: Mapped[list[Case]] = relationship(back_populates="course")
    setup: Mapped["CourseSetup | None"] = relationship(
        back_populates="course", uselist=False, cascade="all, delete-orphan"
    )
    page_rows: Mapped[list["CoursePageRow"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CoursePageRow.sort_order",
    )


class CourseSetup(Base):
    """과정 공통 셋팅(톤·실행설정·과정 프롬프트). ← sharedSetup.vars / course_rules"""

    __tablename__ = "course_setups"

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    author: Mapped[str] = mapped_column(String(200), default="")
    author_role: Mapped[str] = mapped_column(String(200), default="")
    narr_len: Mapped[str] = mapped_column(String(200), default="")
    tone: Mapped[str] = mapped_column(String(400), default="")
    forbidden: Mapped[str] = mapped_column(String(500), default="")
    img_style: Mapped[str] = mapped_column(String(400), default="")
    extra_prompt: Mapped[str] = mapped_column(Text, default="")
    pages_text: Mapped[str] = mapped_column(Text, default="")  # m_pages 호환 텍스트
    tpl_name: Mapped[str] = mapped_column(String(300), default="")
    tpl_analysis: Mapped[str] = mapped_column(Text, default="")
    tpl_meta: Mapped[str] = mapped_column(Text, default="[]")
    set_split_first: Mapped[bool] = mapped_column(Boolean, default=True)
    set_merge_dup_only: Mapped[bool] = mapped_column(Boolean, default=True)
    set_no_overcompress: Mapped[bool] = mapped_column(Boolean, default=True)
    set_keep_wording: Mapped[bool] = mapped_column(Boolean, default=True)
    set_no_scene_cap: Mapped[bool] = mapped_column(Boolean, default=True)
    set_bullets_wide: Mapped[bool] = mapped_column(Boolean, default=True)
    course_prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    course: Mapped[Course] = relationship(back_populates="setup")


class CoursePageRow(Base):
    """과정 공통 페이지 구성 한 줄. ← sharedSetup.pageRows[]"""

    __tablename__ = "course_page_rows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(40), default="고정")  # 고정|이미지|가변
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    course: Mapped[Course] = relationship(back_populates="page_rows")


class Week(Base):
    """주차·차시. ← course.units[] (week, session, unit, unit_title, week_title)
    한 주차에 여러 차시(session_no)를 둘 수 있다.
    """

    __tablename__ = "weeks"
    __table_args__ = (
        UniqueConstraint("course_id", "week_no", "session_no", name="uq_course_week_session"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    week_no: Mapped[int] = mapped_column(Integer)
    session_no: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(400), default="")
    week_title: Mapped[str] = mapped_column(String(400), default="")
    # 표시용 "2주차 1차시" 등
    label: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    course: Mapped[Course] = relationship(back_populates="weeks")
    unit_setup: Mapped[UnitSetup | None] = relationship(
        back_populates="week", uselist=False, cascade="all, delete-orphan"
    )


class UnitSetup(Base):
    """차시 셋팅·초안. ← lf_unit_draft_* / lf_setup_draft / lf_course_vars_* / lf_course_rules_*"""

    __tablename__ = "unit_setups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"), unique=True, index=True)
    pages_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vars_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    course_prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(String(400), default="")
    # 원고 문단(용량 큼) — 테스트 단계 허용
    source_paras_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    draft_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    week: Mapped[Week] = relationship(back_populates="unit_setup")


class PromptVersion(Base):
    """공통 분할 프롬프트 버전. ← lf_ai_rules (+ 수동 버전 태그)"""

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Case(Base):
    """원고 케이스(+기대결과). 하네스 단위. ← case_*.json meta / jsonl __meta"""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    week_id: Mapped[str | None] = mapped_column(ForeignKey("weeks.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_paras_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    course: Mapped[Course | None] = relationship(back_populates="cases")
    runs: Mapped[list[Run]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Run(Base):
    """한 번의 분할 실행."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    prompt_version: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    ai_scene_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(40), default="done")  # pending|running|done|error
    mode: Mapped[str] = mapped_column(String(20), default="cmp")  # tag|cmp|generate
    board_version: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 보드 롤링 버전(v1,v2…)
    revisions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # meta._revisions
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="runs")
    scenes: Mapped[list[Scene]] = relationship(back_populates="run", cascade="all, delete-orphan")
    score: Mapped[Score | None] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    decisions: Mapped[list[Decision]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Scene(Base):
    """AI 분할 화면. ← W.scenes / cmp ais[]"""

    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("run_id", "no", name="uq_run_scene_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500), default="")
    screen_json: Mapped[list | str | None] = mapped_column(JSON, nullable=True)
    narration: Mapped[str] = mapped_column(Text, default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")
    objective_json: Mapped[list | str | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | list | None] = mapped_column(JSON, nullable=True)
    page_slot: Mapped[str] = mapped_column(String(80), default="")
    page_kind: Mapped[str] = mapped_column(String(40), default="")
    feedback_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship(back_populates="scenes")
    feedback_reviews: Mapped[list[FeedbackReview]] = relationship(
        back_populates="scene", cascade="all, delete-orphan"
    )


class Score(Base):
    """자동 채점 결과."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    density: Mapped[float | None] = mapped_column(Float, nullable=True)
    sim_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    kind_counts_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    format_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="score")


class FeedbackReview(Base):
    """사람이 피드백 카드를 판정한 결과."""

    __tablename__ = "feedback_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    feedback_index: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(10), default="")  # ok|no
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scene: Mapped[Scene] = relationship(back_populates="feedback_reviews")


class Decision(Base):
    """레거시 태깅/대조 행. ← .jsonl 본문 줄 / case_*_decisions.json decisions[]"""

    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("run_id", "decision_key", name="uq_run_decision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_key: Mapped[str] = mapped_column(String(80), default="")  # d_001 등
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(40), default="")  # keep|merge|add|...
    kind: Mapped[str] = mapped_column(String(40), default="")  # cmp kind
    sim: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="decisions")
