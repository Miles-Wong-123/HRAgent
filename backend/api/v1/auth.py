"""登录接口：验证数据库中的账号，再使用公共认证工具签发 Token。"""

import asyncio

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.core.logger import get_logger
from backend.core.security import create_access_token, verify_password
from backend.dependencies import get_db

router = APIRouter()
logger = get_logger(__name__)


class LoginRequest(BaseModel):
    """登录只接收凭证，公司和角色从数据库中的账号获取。"""

    username: str = Field(..., min_length=1, max_length=254, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=72, description="密码")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("用户名或邮箱不能为空")
        return value


class TokenResponse(BaseModel):
    """登录成功的响应体。"""
    access_token: str                 # JWT 令牌
    token_type:   str = "bearer"      # 令牌类型，固定 bearer
    expires_in:   int                 # 有效期（秒）
    role:         str                 # 用户角色
    user_id:      str                 # 用户ID
    tenant_id:    str                 # 账号所属公司范围，沿用现有字段名


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """用户登录，返回 JWT Access Token（支持用户名或邮箱登录）。"""
    settings = get_settings()
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 当前登录入口不要求用户选择公司，因此必须唯一定位账号。
    # 同名账号或用户名与他人邮箱冲突时拒绝登录，不能随机选择第一条记录。
    result = await db.execute(
        text(
            "SELECT u.id, u.password_hash, u.role, u.tenant_id, u.is_active, "
            "c.is_active AS company_is_active "
            "FROM public.users AS u "
            "LEFT JOIN public.companies AS c ON c.id = u.tenant_id "
            "WHERE u.username = :val OR u.email = :val LIMIT 2"
        ),
        {"val": req.username},
    )
    rows = result.fetchall()
    if len(rows) != 1:
        raise invalid_credentials
    row = rows[0]

    # 密码验证放在线程池运行，避免阻塞其他请求；密码本身不做去空格处理。
    password_ok = await asyncio.to_thread(verify_password, req.password, row.password_hash)
    if not password_ok:
        raise invalid_credentials

    # 先验证密码，再返回账号状态，避免仅凭用户名获知账号是否停用。
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )
    if not row.company_is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="所属公司不存在或已停用，请联系管理员",
        )
    if row.role not in {"hr", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号无权访问 HR 系统",
        )
    if not isinstance(row.tenant_id, str) or not row.tenant_id.strip():
        raise invalid_credentials

    token = create_access_token(
        user_id=str(row.id),
        tenant_id=row.tenant_id,
        role=row.role,
        expires_minutes=settings.jwt_access_token_expire_minutes,
    )

    logger.info("auth.login_success", user_id=str(row.id), role=row.role)

    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,   # 分钟转秒
        role=row.role,
        user_id=str(row.id),
        tenant_id=row.tenant_id,
    )


if __name__ == '__main__':
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8000)
