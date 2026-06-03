# app/main.py

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

app = FastAPI(title=app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    graph = compile_graph()
    set_graph(graph)


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
