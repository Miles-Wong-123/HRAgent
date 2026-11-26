"""岗位读写：所有查询携带公司范围，人数变更在行锁内校验。"""

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.dependencies import CurrentUser

_COLUMNS = """p.id, p.tenant_id, p.department_id, d.name AS department_name,
    d.is_active AS department_is_active, p.title, p.location, p.description,
    p.target_headcount, p.hired_headcount,
    p.target_headcount - p.hired_headcount AS vacancy_count,
    p.recruitment_status, p.created_at, p.updated_at"""
_JOIN = "FROM public.positions p JOIN public.departments d ON d.id = p.department_id AND d.tenant_id = p.tenant_id"
_EDITABLE = {"department_id", "title", "location", "description", "target_headcount", "hired_headcount", "recruitment_status"}


async def get_position(db: AsyncSession, tenant_id: str, position_id: UUID) -> dict:
    result = await db.execute(text(f"SELECT {_COLUMNS} {_JOIN} WHERE p.tenant_id = :tenant_id AND p.id = :id"),
                              {"tenant_id": tenant_id, "id": position_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "岗位不存在")
    return dict(row)


async def list_positions(db: AsyncSession,
                         tenant_id: str,
                         search: str,
                         department_id: UUID | None,
                         recruitment_status: str | None,
                         limit: int,
                         offset: int) -> dict:
    filters = ["p.tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit, "offset": offset}
    if search:
        filters.append("(strpos(lower(p.title), lower(:search)) > 0 OR strpos(lower(d.name), lower(:search)) > 0)")
        params["search"] = search
    if department_id:
        filters.append("p.department_id = :department_id")
        params["department_id"] = department_id
    if recruitment_status:
        filters.append("p.recruitment_status = :status")
        params["status"] = recruitment_status
    where = " AND ".join(filters)
    count = await db.execute(text(f"SELECT count(*) {_JOIN} WHERE {where}"), params)
    rows = await db.execute(text(f"SELECT {_COLUMNS} {_JOIN} WHERE {where} ORDER BY p.created_at DESC, p.id LIMIT :limit OFFSET :offset"), params)
    return {"items": [dict(row) for row in rows.mappings()], "total": count.scalar_one()}


async def _department(db: AsyncSession, tenant_id: str, department_id: UUID):
    result = await db.execute(text("SELECT id, is_active FROM public.departments WHERE tenant_id = :tenant_id AND id = :id FOR SHARE"),
                              {"tenant_id": tenant_id, "id": department_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "部门不存在")
    return row


def _check_counts(values: dict) -> None:
    if values["hired_headcount"] > values["target_headcount"]:
        raise HTTPException(422, "已招聘人数不能大于计划招聘人数")


def _conflict(exc: IntegrityError) -> None:
    if getattr(exc.orig, "sqlstate", None) == "23505":
        raise HTTPException(409, "该部门已存在同名岗位") from None
    raise exc


async def create_position(db: AsyncSession, user: CurrentUser, values: dict) -> dict:
    department = await _department(db, user["tenant_id"], values["department_id"])
    if not department["is_active"]:
        raise HTTPException(409, "不能在已停用的部门新增岗位")
    _check_counts(values)
    try:
        async with db.begin_nested():
            result = await db.execute(text("""
                INSERT INTO public.positions
                  (tenant_id, department_id, title, location, description, target_headcount,
                   hired_headcount, recruitment_status, created_by)
                VALUES (:tenant_id, :department_id, :title, :location, :description,
                        :target_headcount, :hired_headcount, :recruitment_status, :created_by)
                RETURNING id
            """), {**values, "tenant_id": user["tenant_id"], "created_by": UUID(user["user_id"])})
            position_id = result.scalar_one()
    except IntegrityError as exc:
        _conflict(exc)
    return await get_position(db, user["tenant_id"], position_id)


async def update_position(db: AsyncSession, tenant_id: str, position_id: UUID, changes: dict) -> dict:
    if not changes or not changes.keys() <= _EDITABLE:
        raise ValueError("岗位更新字段无效")
    result = await db.execute(text("SELECT * FROM public.positions WHERE tenant_id = :tenant_id AND id = :id FOR UPDATE"),
                              {"tenant_id": tenant_id, "id": position_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "岗位不存在")
    values = {**row, **changes}
    _check_counts(values)
    department = await _department(db, tenant_id, values["department_id"])
    if not department["is_active"] and (values["department_id"] != row["department_id"] or values["recruitment_status"] == "open"):
        raise HTTPException(409, "部门已停用，请选择启用的部门或将招聘状态改为暂停、关闭")
    assignments = ", ".join(f"{key} = :{key}" for key in sorted(changes))
    try:
        async with db.begin_nested():
            await db.execute(text(f"UPDATE public.positions SET {assignments}, updated_at = NOW() WHERE tenant_id = :tenant_id AND id = :id"),
                             {**changes, "tenant_id": tenant_id, "id": position_id})
    except IntegrityError as exc:
        _conflict(exc)
    return await get_position(db, tenant_id, position_id)
