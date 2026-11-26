"""部门管理接口：所有数据限定在当前登录账号所属公司。"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import require_admin, require_hr
from backend.dependencies import CurrentUser, get_db
from backend.services.organization_service import (
    create_department, get_department, list_departments, update_department,
)


router = APIRouter()


class DepartmentResponse(BaseModel):
    id: UUID
    tenant_id: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def empty_description_to_null(cls, value: str | None) -> str | None:
        return value or None


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: StrictBool | None = None

    @field_validator("name", "is_active")
    @classmethod
    def required_values_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("部门名称和启用状态不能设为 null")
        return value

    @field_validator("description")
    @classmethod
    def empty_description_to_null(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def require_changes(self) -> "DepartmentUpdate":
        if not self.model_fields_set:
            raise ValueError("请至少提供一个要修改的字段")
        return self


@router.get("", response_model=list[DepartmentResponse])
async def read_departments(
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
    is_active: bool | None = Query(default=None, description="不填则包含已停用部门"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """查看本公司部门，支持按启用状态筛选及分页。"""
    return await list_departments(db, user["tenant_id"], is_active, limit, offset)


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def add_department(
    request: DepartmentCreate,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员新增本公司部门；同公司部门名称不能重复。"""
    return await create_department(db, user["tenant_id"], request.model_dump())


@router.get("/{department_id}", response_model=DepartmentResponse)
async def read_department(
    department_id: UUID,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询本公司指定部门；不存在或属于其他公司均返回 404。"""
    return await get_department(db, user["tenant_id"], department_id)


@router.patch("/{department_id}", response_model=DepartmentResponse)
async def patch_department(
    department_id: UUID,
    request: DepartmentUpdate,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员修改、停用或重新启用部门；未提交的字段不变。"""
    return await update_department(
        db, user["tenant_id"], department_id, request.model_dump(exclude_unset=True)
    )
