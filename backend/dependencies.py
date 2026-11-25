"""接口共用依赖：数据库会话与经过验证的当前用户。"""

from typing import AsyncGenerator
from uuid import UUID

from typing_extensions import TypedDict

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.config import get_settings
from backend.core.exceptions import AuthenticationError
from backend.core.security import decode_access_token

settings = get_settings()

# 创建异步引擎（连接池）
engine = create_async_engine(
    settings.database_url,        # 来自 config.py，最终来自 .env.local
    pool_size=10,                 # 连接池基础大小
    max_overflow=20,              # 高峰时最多再额外开 20 个连接
    echo=False,                   # True 会打印所有 SQL，调试时可临时打开
)

# 会话工厂
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖：获取异步数据库会话，自动提交 / 回滚 / 关闭
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session            # 把会话交给接口使用
            await session.commit()   # 接口正常结束 → 自动提交
        except Exception:
            await session.rollback() # 出错 → 自动回滚
            raise


# 自己处理缺失或错误的认证头，统一返回 401 和 Bearer 响应头。
bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(TypedDict):
    user_id: str
    role: str
    tenant_id: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    验证 Token 并查询账号的当前状态，返回可信的用户、角色和公司信息。

    用户被删除、停用、调离原公司或移除 HR 权限后，旧 Token 不再具有原权限。
    角色以数据库当前值为准，不用 Token 中可能已经过时的角色授权。
    业务接口仍需用 tenant_id 限定岗位、简历等数据的查询和修改范围。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise credentials_exception

    try:
        payload = decode_access_token(credentials.credentials)
        # users.id 是 UUID，先校验格式，避免非法 ID 触发数据库类型错误。
        user_id = str(UUID(payload["sub"]))
    except (AuthenticationError, ValueError):
        raise credentials_exception from None

    result = await db.execute(
        text(
            "SELECT u.id, u.role, u.tenant_id, u.is_active, "
            "c.is_active AS company_is_active "
            "FROM public.users AS u "
            "LEFT JOIN public.companies AS c ON c.id = u.tenant_id "
            "WHERE u.id = :user_id AND u.tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": payload["tenant_id"]},
    )
    row = result.fetchone()
    if row is None:
        raise credentials_exception

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

    return {"user_id": str(row.id), "role": row.role, "tenant_id": row.tenant_id}
