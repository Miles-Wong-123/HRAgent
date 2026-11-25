"""公共认证工具：密码哈希、密码验证和登录 Token 的签发、解析。

本模块不操作数据库，也不判断用户是否停用或是否有业务权限。
接口接入时，还需根据 Token 中的用户 ID 查询当前账号及公司信息。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import get_settings
from backend.core.exceptions import AuthenticationError


# 沿用现有 bcrypt 密码格式，便于验证已有账号的密码。
# bcrypt 最多处理 72 个字节；禁止静默截断，避免不同密码被当作相同密码。
_PASSWORD_CONTEXT = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=True
)
_BCRYPT_MAX_BYTES = 72
_TOKEN_ERROR_MESSAGE = "无效或已过期的登录凭证"


def _valid_password_length(password: str) -> bool:
    return (
        isinstance(password, str)
        and 0 < len(password.encode("utf-8")) <= _BCRYPT_MAX_BYTES
    )


def hash_password(password: str) -> str:
    """将密码转成含随机盐的 bcrypt 哈希；不保存或记录明文密码。"""
    if not _valid_password_length(password):
        raise ValueError("密码不能为空，且 UTF-8 编码长度不能超过 72 字节")
    return _PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码；输入过长、哈希无效或密码不匹配时返回 False。

    此函数和 hash_password 均为同步的 CPU 密集操作，异步接口应在线程池中调用。
    """
    if not _valid_password_length(password):
        return False
    if not isinstance(password_hash, str) or not password_hash:
        return False
    try:
        return _PASSWORD_CONTEXT.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    user_id: str,
    tenant_id: str,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """签发登录 Token；保留 tenant_id 字段表示账号所属公司范围。

    身份信息必须来自服务端查询的账号，不能直接使用客户端提交的角色或公司。
    不传有效期时，使用配置中的 jwt_access_token_expire_minutes。
    """
    for name, value in (("user_id", user_id), ("tenant_id", tenant_id), ("role", role)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} 不能为空")

    settings = get_settings()
    minutes = (
        settings.jwt_access_token_expire_minutes
        if expires_minutes is None
        else expires_minutes
    )
    if type(minutes) is not int or minutes <= 0:
        raise ValueError("Token 有效期必须是正整数分钟")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "token_type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """验证登录 Token，返回声明；失败时统一抛出 AuthenticationError。

    仅接受配置指定的签名算法；必须有用户、公司、角色、签发及过期时间。
    不补默认公司或默认角色，防止缺失身份信息被误当成有效登录。
    验证成功仅代表凭证有效，账号状态和数据访问权限由上层继续检查。
    """
    if not isinstance(token, str) or not token.strip():
        raise AuthenticationError(_TOKEN_ERROR_MESSAGE)

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_iat": True, "require_sub": True},
        )
        for name in ("sub", "tenant_id", "role"):
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise JWTError("Missing or invalid identity claim")
        if payload.get("token_type") != "access":
            raise JWTError("Invalid token type")
        if type(payload.get("iat")) is not int or type(payload.get("exp")) is not int:
            raise JWTError("Invalid token timestamps")
        return payload
    except (JWTError, ValueError, TypeError):
        raise AuthenticationError(_TOKEN_ERROR_MESSAGE) from None
