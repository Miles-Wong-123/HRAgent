"""后端启动入口：在项目根目录运行 python -m backend.main。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.v1.auth import router as auth_router
from backend.api.v1.companies import router as companies_router
from backend.api.v1.departments import router as departments_router
from backend.api.v1.positions import router as positions_router
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
    description="HR 系统接口：登录、公司、部门与岗位管理。",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(companies_router, prefix="/api/v1/companies", tags=["公司管理"])
app.include_router(departments_router, prefix="/api/v1/departments", tags=["部门管理"])
app.include_router(positions_router, prefix="/api/v1/positions", tags=["岗位管理"])
frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/ui", StaticFiles(directory=frontend_dist, html=True), name="frontend")


@app.get("/", include_in_schema=False)
async def frontend():
    if frontend_dist.is_dir():
        return RedirectResponse(url="/ui/")
    return {"message": "开发前端请运行 npm run dev 并打开 http://127.0.0.1:5173；或 npm run build 后重启后端。"}


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
