import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.api.attachment_router import router as attachment_router
from backend.api.admin_router import router as admin_router
from backend.api.student_router import router as student_router
from backend.api.teacher_router import router as teacher_router
from backend.api.auth_router import router as auth_router
from backend.api.book_router import router as book_router
from backend.api.chat_router import router as chat_router
from backend.api.digitization_router import router as digitization_router
from backend.api.interactive_router import router as interactive_router
from backend.bot.bot_instance import bot, dp
from backend.digitization_books.queue import start_digitization_worker, stop_digitization_worker
from backend.web.request_logging import log_http_request
from backend.web.schema_migrations import ensure_runtime_schema
from config import settings
from database import db
from logger_config import logger

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    await ensure_runtime_schema(db.pool)
    await start_digitization_worker()
    logger.info("application_started")
    try:
        yield
    finally:
        await stop_digitization_worker()
        await db.disconnect()
        logger.info("application_stopped")


app = FastAPI(title="Umnix API Platform", version="2.0.0", lifespan=lifespan)
app.middleware("http")(log_http_request)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount(
    "/digitization-books",
    StaticFiles(directory=str(FRONTEND_DIR / "digitization_books")),
    name="digitization-books",
)

for api_router in (
    auth_router,
    student_router,
    teacher_router,
    admin_router,
    chat_router,
    attachment_router,
    book_router,
    interactive_router,
    digitization_router,
):
    app.include_router(api_router)

templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))


def render_page(request: Request, template_name: str, **context):
    return templates.TemplateResponse(request, template_name, context)


@app.get("/", response_class=HTMLResponse)
@app.get("/auth", response_class=HTMLResponse)
@app.get("/auth.html", response_class=HTMLResponse)
@app.get("/parent/auth", response_class=HTMLResponse)
@app.get("/parent/auth.html", response_class=HTMLResponse)
async def auth_page(request: Request):
    return render_page(request, "auth.html")


@app.get("/student", response_class=HTMLResponse)
@app.get("/student.html", response_class=HTMLResponse)
async def student_page(request: Request):
    return render_page(request, "student.html")


@app.get("/parent", response_class=HTMLResponse)
@app.get("/parent/dashboard", response_class=HTMLResponse)
@app.get("/parent/create-test", response_class=HTMLResponse)
@app.get("/parent.html", response_class=HTMLResponse)
async def parent_page(request: Request):
    return render_page(request, "parent.html")


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin.html", response_class=HTMLResponse)
async def admin_page(request: Request):
    return render_page(request, "admin.html")


@app.get("/files", response_class=HTMLResponse)
@app.get("/files.html", response_class=HTMLResponse)
async def files_page(request: Request):
    return render_page(request, "files.html")


@app.get("/interactive/{app_id}", response_class=HTMLResponse)
async def interactive_page(request: Request, app_id: str):
    return render_page(request, "interactive.html", app_id=app_id)


def build_api_server() -> uvicorn.Server:
    server_config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        loop="asyncio",
    )
    return uvicorn.Server(server_config)


async def run_api(server: uvicorn.Server) -> None:
    await server.serve()


async def main() -> None:
    api_server = build_api_server()
    api_task = asyncio.create_task(run_api(api_server))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        api_server.should_exit = True
        try:
            await asyncio.wait_for(api_task, timeout=15)
        except asyncio.TimeoutError:
            api_task.cancel()
            try:
                await api_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("application_stopped_by_user")
