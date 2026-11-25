"""本公司资料接口：不接受客户端指定公司 ID。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import require_admin, require_hr
from backend.dependencies import CurrentUser, get_db
from backend.services.organization_service import get_company, update_company


router = APIRouter()


class CompanyResponse(BaseModel):
    id: str
    name: str
    short_name: str | None
    address: str | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    short_name: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("公司名称不能设为空")
        return value

    @field_validator("short_name", "address", "description")
    @classmethod
    def empty_text_to_null(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def require_changes(self) -> "CompanyUpdate":
        if not self.model_fields_set:
            raise ValueError("请至少提供一个要修改的字段")
        return self


@router.get("/current", response_model=CompanyResponse)
async def read_current_company(
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """HR 和管理员查看账号所属公司，不支持查询其他公司。"""
    return await get_company(db, user["tenant_id"])


@router.patch("/current", response_model=CompanyResponse)
async def patch_current_company(
    request: CompanyUpdate,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """仅管理员可修改本公司名称、简称、地址和介绍；未提交的字段不变。"""
    return await update_company(db, user["tenant_id"], request.model_dump(exclude_unset=True))
