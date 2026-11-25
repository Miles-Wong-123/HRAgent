"""公共权限检查：使用已认证账号的当前角色和公司范围。

接口用 Depends(require_hr) 或 Depends(require_admin) 声明角色要求。
读取或修改具体业务记录时，还需按当前用户的 tenant_id 限定数据库查询。
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import Depends, HTTPException, status

from backend.dependencies import CurrentUser, get_current_user


Role = Literal["hr", "admin"]


def require_roles(*roles: Role) -> Callable[..., Awaitable[CurrentUser]]:
    """生成角色检查依赖；身份验证、停用检查由 get_current_user 先完成。

    示例：user: CurrentUser = Depends(require_roles("admin"))。
    管理员不会自动绕过角色限制，需要允许时应显式包含 admin。
    """
    allowed_roles = frozenset(roles)
    if not allowed_roles or not allowed_roles.issubset({"hr", "admin"}):
        raise ValueError("必须指定至少一个有效角色：hr 或 admin")

    async def check_role(
        user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前账号无权执行此操作",
            )
        return user

    return check_role


# HR 业务：允许本公司的 HR 和管理员。
require_hr = require_roles("hr", "admin")

# 管理业务：仅管理员；仍然不能跨公司访问。
require_admin = require_roles("admin")


def ensure_same_tenant(user: CurrentUser, resource_tenant_id: str | None) -> None:
    """检查已读取资源是否属于当前公司，不提供管理员跨公司豁免。

    resource_tenant_id 必须来自数据库记录，不能取自客户端声明。
    此函数不能代替列表查询、更新和删除语句中的 tenant_id 条件。
    """
    current_tenant_id = user.get("tenant_id")
    if (
        not isinstance(current_tenant_id, str)
        or not current_tenant_id.strip()
        or not isinstance(resource_tenant_id, str)
        or not resource_tenant_id.strip()
        or current_tenant_id != resource_tenant_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该公司的数据",
        )
