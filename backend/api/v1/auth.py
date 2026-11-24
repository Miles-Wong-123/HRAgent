# Todo 0 导入依赖
# 异步编程相关
import asyncio
from datetime import datetime, timedelta, timezone
# 服务器相关
import uvicorn
# 接口相关
from fastapi import APIRouter, HTTPException, status, Depends
# 数据结构相关
from pydantic import BaseModel, Field
# 数据库相关
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
# jwt鉴权相关
from jose import jwt
# 加密相关
from passlib.context import CryptContext
# 自定义依赖
from backend.config import get_settings
from backend.dependencies import get_db
from backend.core.logger import get_logger

router = APIRouter()                                               # 本模块的路由集合
logger = get_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")  # 密码哈希上下文

class LoginRequest(BaseModel):
    """登录请求体。"""
    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """登录成功的响应体。"""
    access_token: str                 # JWT 令牌
    token_type:   str = "bearer"      # 令牌类型，固定 bearer
    expires_in:   int                 # 有效期（秒）
    role:         str                 # 用户角色
    user_id:      str                 # 用户ID


def _create_access_token(data: dict, expires_minutes: int) -> str:
    """把身份信息 + 过期时间打包，用密钥签名成 JWT 字符串。"""
    settings = get_settings()
    payload = data.copy()                                            # 拷一份，避免改到原字典
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload["exp"] = expire                                          # exp 是 JWT 标准的过期字段
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,                            # 请求体自动解析为 LoginRequest
    db: AsyncSession = Depends(get_db),           # 注入数据库会话
    ):
    """用户登录，返回 JWT Access Token（支持用户名或邮箱登录）。"""

    settings = get_settings()

    # 查用户：用户名或邮箱都行（:val 同时匹配两列），参数化查询防注入（回顾 2.6）
    result = await db.execute(
        text(
            "SELECT id, password_hash, role, tenant_id, is_active "
            "FROM users WHERE username = :val OR email = :val LIMIT 1"
        ),
        {"val": req.username},
    )
    row = result.fetchone()

    if not row:                                   # 用户不存在
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not row.is_active:                         # 账号被禁用
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")

    # 密码校验是 CPU 密集型（~100ms），用线程池避免阻塞事件循环（回顾 2.1.4）
    loop = asyncio.get_running_loop()

    password_ok = await loop.run_in_executor(
        None, pwd_context.verify, req.password, row.password_hash
    )

    # 密码不对
    if not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    # 校验通过，签发 Token（把用户身份装进去）
    token = _create_access_token(
        data={"sub": str(row.id), "role": row.role, "tenant_id": row.tenant_id},
        expires_minutes=settings.jwt_access_token_expire_minutes,
    )

    logger.info("auth.login_success", user_id=str(row.id), role=row.role)

    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,   # 分钟转秒
        role=row.role,
        user_id=str(row.id),
    )

if __name__ == '__main__':
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8000)
