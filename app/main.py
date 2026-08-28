# app/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

from app.api.routes.text2sql import router as text2sql_router
from app.workflow.graph import compile_graph, set_graph

load_dotenv()

app_name = os.getenv("APP_NAME", "Enterprise Text2SQL")
app_env = os.getenv("APP_ENV", "dev")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：编译 LangGraph 工作流
    graph = compile_graph()
    set_graph(graph)
    yield
    # 关闭时：清理资源（目前无需操作）


app = FastAPI(title=app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok", "app": app_name, "env": app_env}


app.include_router(text2sql_router, prefix="/api")

# 前端静态文件
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/demo")
async def demo_page():
    demo_path = os.path.join(frontend_dir, "index.html")
    with open(demo_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
