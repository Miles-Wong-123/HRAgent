"""岗位管理：HR 与管理员均可维护本公司岗位。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import require_hr
from backend.dependencies import CurrentUser, get_db
from backend.services.position_service import create_position, get_position, list_positions, update_position

router = APIRouter()
RecruitmentStatus = Literal["open", "paused", "closed"]


class PositionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    department_id: UUID
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=10000)
    target_headcount: int = Field(default=1, ge=1, le=100000, strict=True)
    hired_headcount: int = Field(default=0, ge=0, le=100000, strict=True)
    recruitment_status: RecruitmentStatus = "open"

    @field_validator("location", "description")
    @classmethod
    def empty_to_null(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_counts(self) -> "PositionCreate":
        if self.hired_headcount > self.target_headcount:
            raise ValueError("已招聘人数不能大于计划招聘人数")
        return self


class PositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    department_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=10000)
    target_headcount: int | None = Field(default=None, ge=1, le=100000, strict=True)
    hired_headcount: int | None = Field(default=None, ge=0, le=100000, strict=True)
    recruitment_status: RecruitmentStatus | None = None

    @field_validator("department_id", "title", "target_headcount", "hired_headcount", "recruitment_status")
    @classmethod
    def required_value(cls, value):
        if value is None:
            raise ValueError("该字段不能为 null")
        return value

    @field_validator("location", "description")
    @classmethod
    def empty_to_null(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def nonempty(self) -> "PositionUpdate":
        if not self.model_fields_set:
            raise ValueError("请至少提交一个修改字段")
        return self


class PositionResponse(BaseModel):
    id: UUID
    tenant_id: str
    department_id: UUID
    department_name: str
    department_is_active: bool
    title: str
    location: str | None
    description: str | None
    target_headcount: int
    hired_headcount: int
    vacancy_count: int
    recruitment_status: RecruitmentStatus
    created_at: datetime
    updated_at: datetime


class PositionList(BaseModel):
    items: list[PositionResponse]
    total: int


@router.get("", response_model=PositionList)
async def read_positions(
    user: CurrentUser                               = Depends(require_hr),
    db: AsyncSession                                = Depends(get_db),
    search: str                                     = Query(default="", max_length=200),
    department_id: UUID | None                      = None,
    recruitment_status: RecruitmentStatus | None    = None,
    limit: int                                      = Query(default=10, ge=1, le=100),
    offset: int                                     = Query(default=0, ge=0),
):
    return await list_positions(db, user["tenant_id"], search.strip(), department_id, recruitment_status, limit, offset)


@router.post("", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def add_position(
        request: PositionCreate,
        user: CurrentUser = Depends(require_hr),
        db: AsyncSession = Depends(get_db)
):

    return await create_position(db, user, request.model_dump())


@router.get("/{position_id}", response_model=PositionResponse)
async def read_position(
        position_id: UUID,
        user: CurrentUser = Depends(require_hr),
        db: AsyncSession = Depends(get_db)
):
    return await get_position(db, user["tenant_id"], position_id)


@router.patch("/{position_id}", response_model=PositionResponse)
async def patch_position(
        position_id: UUID,
        request: PositionUpdate,
        user: CurrentUser = Depends(require_hr),
        db: AsyncSession = Depends(get_db)
):
    return await update_position(db, user["tenant_id"], position_id, request.model_dump(exclude_unset=True))
