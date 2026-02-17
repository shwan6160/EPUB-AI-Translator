from fastapi import FastAPI, Request , UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import json

from utils import get_workspace
from provider import GoogleGenai
from utils import get_api_key

app = FastAPI()

TITLE = "Rosetta(Temporary)"
UPLOAD_DIR = get_workspace() / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROVIDER_OPTIONS = ["Google", "OpenRouter", "Copilot"]
OPENROUTER_MODELS = [
    "qwen/qwen3-max-thinking",
    "moonshotai/kimi-k2.5",
    "z-ai/GLM-5",
]
GOOGLE_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def get_character_dictionary_path(epub_filename: str) -> Path:
    return UPLOAD_DIR / f"{Path(epub_filename).stem}_character_dictionary.json"


def get_uploaded_epub_items() -> list[dict[str, str | bool]]:
    items: list[dict[str, str | bool]] = []
    for path in sorted(UPLOAD_DIR.glob("*.epub")):
        items.append(
            {
                "filename": path.name,
                "has_character_dictionary": get_character_dictionary_path(path.name).exists(),
            }
        )
    return items


def get_dashboard_models(provider_name: str) -> list[str]:
    if provider_name == "Google":
        try:
            key = get_api_key("GEMINI_KEY")
            return [model.replace("models/", "") for model in GoogleGenai.list_available_models(key)]
        except Exception:
            return GOOGLE_FALLBACK_MODELS

    if provider_name == "OpenRouter":
        return OPENROUTER_MODELS

    if provider_name == "Copilot":
        return []

    return []

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": TITLE,
            "uploaded_items": get_uploaded_epub_items(),
        },
    )


@app.get("/uploads")
def list_uploads():
    return {"status": "success", "files": get_uploaded_epub_items()}


@app.get("/providers")
def list_providers():
    return {"status": "success", "providers": PROVIDER_OPTIONS}


@app.get("/models")
def list_models(provider: str):
    if provider not in PROVIDER_OPTIONS:
        return {"status": "error", "message": "유효하지 않은 provider 입니다.", "models": []}

    return {"status": "success", "provider": provider, "models": get_dashboard_models(provider)}


@app.get("/character-dictionary")
def get_character_dictionary(epub_filename: str):
    safe_epub_filename = Path(epub_filename).name
    if not safe_epub_filename.lower().endswith(".epub"):
        return {"status": "error", "message": "유효한 EPUB 파일명이 아닙니다."}

    dictionary_path = get_character_dictionary_path(safe_epub_filename)
    if not dictionary_path.exists():
        return {"status": "error", "message": "character_dictionary.json 파일이 없습니다."}

    try:
        with dictionary_path.open("r", encoding="utf-8") as file:
            content = json.load(file)
    except json.JSONDecodeError:
        return {"status": "error", "message": "JSON 파싱에 실패했습니다."}

    return {
        "status": "success",
        "epub_filename": safe_epub_filename,
        "dictionary_filename": dictionary_path.name,
        "content": content,
    }

@app.post("/upload")
async def upload_epub(file: UploadFile = File(...)):
    if file.content_type != "application/epub+zip":
        return {"status": "error", "message": "업로드된 파일이 EPUB 형식이 아닙니다."}
    if not file.filename:
        return {"status": "error", "message": "파일 이름이 없습니다."}
    if file.filename.split(".")[-1].lower() != "epub":
        return {"status": "error", "message": "파일 확장자가 .epub이 아닙니다."}

    file_path = UPLOAD_DIR / Path(file.filename).name
    
    # 3. 파일 디스크에 저장
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"status": "success", "filename": file.filename, "message": "업로드 성공!"}