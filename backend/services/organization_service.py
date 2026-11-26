"""组织资料的数据库操作；公司范围只能由已认证账号传入。"""

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


_COMPANY_COLUMNS = "id, name, short_name, address, description, is_active, created_at, updated_at"
_EDITABLE_COMPANY_FIELDS = frozenset({"name", "short_name", "address", "description"})
_DEPARTMENT_COLUMNS = "id, tenant_id, name, description, is_active, created_at, updated_at"
_EDITABLE_DEPARTMENT_FIELDS = frozenset({"name", "description", "is_active"})


async def get_company(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    result = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM public.companies WHERE id = :tenant_id AND is_active = TRUE"),
        {"tenant_id": tenant_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在或已停用")
    return dict(row)


async def list_departments(
    db: AsyncSession,
    tenant_id: str,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    state_filter = " AND is_active = :is_active" if is_active is not None else ""
    result = await db.execute(
        text(
            f"SELECT {_DEPARTMENT_COLUMNS} FROM public.departments "
            f"WHERE tenant_id = :tenant_id{state_filter} "
            "ORDER BY created_at, id LIMIT :limit OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "is_active": is_active, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings()]


async def get_department(
    db: AsyncSession, tenant_id: str, department_id: UUID
) -> dict[str, Any]:
    result = await db.execute(
        text(
            f"SELECT {_DEPARTMENT_COLUMNS} FROM public.departments "
            "WHERE tenant_id = :tenant_id AND id = :department_id"
        ),
        {"tenant_id": tenant_id, "department_id": department_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    return dict(row)


async def create_department(
    db: AsyncSession, tenant_id: str, values: dict[str, Any]
) -> dict[str, Any]:
    result = await db.execute(
        text(
            "INSERT INTO public.departments (tenant_id, name, description) "
            "VALUES (:tenant_id, :name, :description) "
            "ON CONFLICT (tenant_id, name) DO NOTHING "
            f"RETURNING {_DEPARTMENT_COLUMNS}"
        ),
        {"tenant_id": tenant_id, "name": values["name"], "description": values.get("description")},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="本公司已存在同名部门")
    return dict(row)


async def update_department(
    db: AsyncSession, tenant_id: str, department_id: UUID, changes: dict[str, Any]
) -> dict[str, Any]:
    if not changes or not changes.keys() <= _EDITABLE_DEPARTMENT_FIELDS:
        raise ValueError("部门更新字段无效")
    assignments = ", ".join(f"{field} = :{field}" for field in sorted(changes))
    try:
        # 保存点确保同名冲突能够回滚，事务仍由 get_db 统一处理。
        async with db.begin_nested():
            result = await db.execute(
                text(
                    f"UPDATE public.departments SET {assignments}, updated_at = NOW() "
                    "WHERE tenant_id = :tenant_id AND id = :department_id "
                    f"RETURNING {_DEPARTMENT_COLUMNS}"
                ),
                {"tenant_id": tenant_id, "department_id": department_id, **changes},
            )
            row = result.mappings().one_or_none()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="本公司已存在同名部门"
            ) from None
        raise
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    return dict(row)


async def update_company(
    db: AsyncSession, tenant_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    if not changes or not changes.keys() <= _EDITABLE_COMPANY_FIELDS:
        raise ValueError("公司更新字段无效")

    # 列名只来自固定白名单，所有字段值使用参数绑定。
    assignments = ", ".join(f"{field} = :{field}" for field in sorted(changes))
    result = await db.execute(
        text(
            f"UPDATE public.companies SET {assignments}, updated_at = NOW() "
            f"WHERE id = :tenant_id AND is_active = TRUE RETURNING {_COMPANY_COLUMNS}"
        ),
        {"tenant_id": tenant_id, **changes},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在或已停用")
    # 提交/回滚由 get_db 统一处理。
    return dict(row)
