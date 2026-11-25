"""组织资料的数据库操作；公司范围只能由已认证账号传入。"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_COMPANY_COLUMNS = "id, name, short_name, address, description, is_active, created_at, updated_at"
_EDITABLE_COMPANY_FIELDS = frozenset({"name", "short_name", "address", "description"})


async def get_company(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    result = await db.execute(
        text(f"SELECT {_COMPANY_COLUMNS} FROM public.companies WHERE id = :tenant_id AND is_active = TRUE"),
        {"tenant_id": tenant_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在或已停用")
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
