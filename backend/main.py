"""后端启动入口：在项目根目录运行 python -m backend.main。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.v1.auth import router as auth_router
from backend.api.v1.companies import router as companies_router
from backend.api.v1.departments import router as departments_router
from backend.config import PROJECT_ROOT, get_settings
from backend.core.logger import configure_logging
from backend.dependencies import CurrentUser, engine, get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="HRAgent API",
    description="HR 系统接口：登录、当前用户查询、公司资料和部门管理。",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(companies_router, prefix="/api/v1/companies", tags=["公司管理"])
app.include_router(departments_router, prefix="/api/v1/departments", tags=["部门管理"])
app.mount("/ui", StaticFiles(directory=PROJECT_ROOT / "backend" / "frontend", html=True), name="frontend")


@app.get("/", include_in_schema=False)
async def frontend():
    return RedirectResponse(url="/ui/")


@app.get("/health", tags=["健康检查"])
async def health() -> dict[str, str]:
    """仅检查应用是否运行，不代表数据库或模型已就绪。"""
    return {"status": "ok"}


@app.get("/api/v1/auth/me", tags=["认证"])
async def current_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """需要 Bearer Token；返回数据库中当前有效的账号身份。"""
    return user


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
