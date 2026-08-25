import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config
from app.llm import get_provider
from app.sessions import session_store

app = FastAPI(title="Trendly Support Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tickets: list


class ResetRequest(BaseModel):
    session_id: str


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "provider": config.LLM_PROVIDER}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session = session_store.get_or_create(req.session_id)
    provider = get_provider()
    reply = provider.chat(session, req.message)
    return ChatResponse(session_id=session.session_id, reply=reply, tickets=session.tickets)


@app.post("/api/reset")
def reset(req: ResetRequest):
    session_store.reset(req.session_id)
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT, reload=True)
