"""
app/main.py — FastAPI 应用装配

【这个模块做什么】
创建应用、挂中间件、注册全部路由、启动时初始化数据库与种子数据。
这是整条链路唯一的"组装点"，看这一个文件就能知道系统暴露了哪些能力。

【启动】
    cd backend
    .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
    接口文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reliability")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .seed import seed_all

    try:
        seed_all()
        logger.info("数据库初始化与种子数据完成")
    except Exception as e:  # 种子失败不该阻止服务启动（比如只读挂载）
        logger.warning("种子数据初始化失败：%s", e)

    # 默认密钥只适合本机试用。挂到内网或让同事访问前必须换掉，
    # 否则知道这个常量的人可以自己签一个 admin 的 token 直接登进来。
    if settings.jwt_secret == "dev-only-secret-change-me-in-production":
        logger.warning(
            "JWT_SECRET 仍是默认值，仅限本机试用；对外提供服务前请设置随机密钥"
            "（set JWT_SECRET=<32位以上随机串>）"
        )
    logger.info("版本 %s，接口前缀 %s", settings.app_version, settings.api_prefix)
    yield


app = FastAPI(
    title="电子零件可靠性评估系统 API",
    version=settings.app_version,
    description=(
        "BOM 导入 → 零件自动分类 → 可靠性预计（MIL-HDBK-217F / Telcordia SR-332）→ "
        "磨损寿命 → 降额检查 → 敏感性分析 → 评估报告。\n\n"
        "**免责声明**：本系统内置参数为公开标准的示例取值，仅供演示与学习，不得作为产品认证依据。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：不把堆栈直接丢给前端，但日志里留全量信息便于排查。"""
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{type(exc).__name__}"})


from .routers import assess, auth, bom, classify, knowledge, projects, report, system  # noqa: E402

for _router in (
    auth.router,
    projects.router,
    bom.router,
    classify.router,
    knowledge.router,
    assess.router,
    report.router,
    system.router,
):
    app.include_router(_router, prefix=settings.api_prefix)


@app.get("/api/health", tags=["系统"])
def health():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


# ---------------------------------------------------------------------------
# 单端口部署：把「前端构建产物」也交给这个后端托管
#
# 【为什么需要】
#    开发时是「vite dev server(5173) → 代理 /api → 后端(8000)」两个进程两个端口。
#    但把系统搬到另一台机器、或给同事用内网地址访问时，多一个进程就多一个卡点：
#    要么得装 nginx 做反代，要么得记住两个端口、还要改 CORS 白名单。
#
#    所以这里做一个「有就托管、没有就跳过」的逻辑：
#      - 跑过 `npm run build`（存在 frontend/dist）→ 后端顺带把页面发出去，
#        访问 http://<本机或服务器IP>:8000 直接就是完整系统，同源、无 CORS 问题。
#      - 没构建过（只有源码）→ 自动跳过，退回开发模式，不影响 `npm run dev`。
#
# 【为什么不影响 API】
#    /api/v1/* 与 /docs 等具体路由在上面已经注册，匹配优先于这里的通配路由。
#    通配路由只兜「不是 API 的路径」，并把它们统统指回 index.html ——
#    这样前端用前端路由直接刷新 /projects/3 这类地址也不会 404。
# ---------------------------------------------------------------------------
DIST_DIR = Path(settings.dist_dir)

if (DIST_DIR / "index.html").exists():
    if (DIST_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    logger.info("检测到前端构建产物，已启用单端口托管：%s", DIST_DIR)

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        # 未命中的 API 路径必须老实返回 404。
        # 如果这里也回一段 HTML，前端的 fetch 会拿到 HTML 再解析 JSON 失败，
        # 报出来的是"Unexpected token <"，比 404 难查十倍。
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST_DIR / "index.html")

else:

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "app": settings.app_name,
            "docs": "/docs",
            "api_prefix": settings.api_prefix,
            "hint": "未找到前端构建产物（frontend/dist）。开发模式请访问 http://127.0.0.1:5173 ；"
            "或先在 frontend/ 下执行 npm run build 启用单端口托管。",
        }
