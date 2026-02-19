from fastapi import FastAPI, Request , UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import json
import uuid
from datetime import datetime
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel

from utils.utils import get_workspace
from provider import GoogleGenai
from utils.utils import get_api_key
from utils.web import generate_character_dictionary, translate_epub_with_dictionary

app = FastAPI()
TASK_EXECUTOR = ThreadPoolExecutor(max_workers=2)
TASK_LOCK = Lock()
TASKS: dict[str, dict] = {}

TITLE = "ERST - EPUB Multitool"
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


class CharacterDictRunRequest(BaseModel):
    epub_filename: str
    provider: str
    model: str
    key: str | None = None
    save_to_file: bool = True


class TranslationRunRequest(BaseModel):
    epub_filename: str
    provider: str
    model: str
    key: str | None = None
    target_lang: str = "ko"
    max_chars: int = 8000
    max_workers: int = 10


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_task(task_type: str) -> str:
    task_id = uuid.uuid4().hex
    with TASK_LOCK:
        TASKS[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "status": "queued",
            "progress": 0,
            "logs": [f"[{_now_iso()}] 작업 대기 중"],
            "result": None,
            "error": None,
            "started_at": _now_iso(),
            "finished_at": None,
        }
    return task_id


def append_task_log(task_id: str, message: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task["logs"].append(f"[{_now_iso()}] {message}")
        task["logs"] = task["logs"][-100:]


def update_task(task_id: str, **kwargs) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.update(kwargs)


def get_task(task_id: str) -> dict | None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return None
        return dict(task)


def _run_character_dict_task(task_id: str, request: CharacterDictRunRequest) -> None:
    update_task(task_id, status="running", progress=5)
    append_task_log(task_id, "캐릭터 사전 생성 시작")

    try:
        epub_path = resolve_upload_epub_path(request.epub_filename)
        result = generate_character_dictionary(
            epub_path=epub_path,
            provider=request.provider,
            model=request.model,
            key=request.key,
            save_to_file=request.save_to_file,
            progress_logger=lambda msg: append_task_log(task_id, msg),
        )
        update_task(
            task_id,
            status="success",
            progress=100,
            result={
                "epub_filename": epub_path.name,
                "dictionary_filename": Path(result["char_dict_path"]).name,
                "provider": result["provider"],
                "model": result["model"],
            },
            finished_at=_now_iso(),
        )
        append_task_log(task_id, "캐릭터 사전 생성 완료")
    except Exception as e:
        update_task(task_id, status="error", error=str(e), finished_at=_now_iso())
        append_task_log(task_id, f"오류: {e}")


def _run_translation_task(task_id: str, request: TranslationRunRequest) -> None:
    update_task(task_id, status="running", progress=5)
    append_task_log(task_id, "번역 작업 시작")

    def progress_logger(message: str) -> None:
        append_task_log(task_id, message)
        if "번역 진행" in message:
            try:
                progress_token = message.split("번역 진행 ", 1)[1].split(":", 1)[0]
                current_text, total_text = progress_token.split("/")
                current = int(current_text)
                total = int(total_text)
                if total > 0:
                    progress_value = min(95, 10 + int((current / total) * 80))
                    update_task(task_id, progress=progress_value)
            except Exception:
                pass

    try:
        epub_path = resolve_upload_epub_path(request.epub_filename)
        result = translate_epub_with_dictionary(
            epub_path=epub_path,
            provider=request.provider,
            model=request.model,
            key=request.key,
            target_lang=request.target_lang,
            max_chars=request.max_chars,
            max_workers=request.max_workers,
            progress_logger=progress_logger,
        )
        update_task(
            task_id,
            status="success",
            progress=100,
            result={
                "epub_filename": epub_path.name,
                "output_epub_filename": Path(result["output_epub_path"]).name,
                "provider": result["provider"],
                "model": result["model"],
            },
            finished_at=_now_iso(),
        )
        append_task_log(task_id, "번역 작업 완료")
    except Exception as e:
        update_task(task_id, status="error", error=str(e), finished_at=_now_iso())
        append_task_log(task_id, f"오류: {e}")


def resolve_upload_epub_path(epub_filename: str) -> Path:
    safe_epub_filename = Path(epub_filename).name
    if not safe_epub_filename.lower().endswith(".epub"):
        raise ValueError("유효한 EPUB 파일명이 아닙니다.")

    epub_path = UPLOAD_DIR / safe_epub_filename
    if not epub_path.exists():
        raise FileNotFoundError("업로드된 EPUB 파일을 찾을 수 없습니다.")

    return epub_path

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


@app.post("/run/character-dictionary")
def run_character_dictionary(request: CharacterDictRunRequest):
    if request.provider not in PROVIDER_OPTIONS:
        return {"status": "error", "message": "유효하지 않은 provider 입니다."}

    try:
        epub_path = resolve_upload_epub_path(request.epub_filename)
        result = generate_character_dictionary(
            epub_path=epub_path,
            provider=request.provider,
            model=request.model,
            key=request.key,
            save_to_file=request.save_to_file,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "success",
        "epub_filename": epub_path.name,
        "dictionary_filename": Path(result["char_dict_path"]).name,
        "provider": result["provider"],
        "model": result["model"],
        "message": "캐릭터 사전 생성 완료",
    }


@app.post("/tasks/character-dictionary")
def start_character_dictionary_task(request: CharacterDictRunRequest):
    if request.provider not in PROVIDER_OPTIONS:
        return {"status": "error", "message": "유효하지 않은 provider 입니다."}

    task_id = create_task("character-dictionary")
    TASK_EXECUTOR.submit(_run_character_dict_task, task_id, request)
    return {"status": "success", "task_id": task_id}


@app.post("/run/translation")
def run_translation(request: TranslationRunRequest):
    if request.provider not in PROVIDER_OPTIONS:
        return {"status": "error", "message": "유효하지 않은 provider 입니다."}

    try:
        epub_path = resolve_upload_epub_path(request.epub_filename)
        result = translate_epub_with_dictionary(
            epub_path=epub_path,
            provider=request.provider,
            model=request.model,
            key=request.key,
            target_lang=request.target_lang,
            max_chars=request.max_chars,
            max_workers=request.max_workers,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "success",
        "epub_filename": epub_path.name,
        "output_epub_filename": Path(result["output_epub_path"]).name,
        "provider": result["provider"],
        "model": result["model"],
        "message": "EPUB 번역 완료",
    }


@app.post("/tasks/translation")
def start_translation_task(request: TranslationRunRequest):
    if request.provider not in PROVIDER_OPTIONS:
        return {"status": "error", "message": "유효하지 않은 provider 입니다."}

    task_id = create_task("translation")
    TASK_EXECUTOR.submit(_run_translation_task, task_id, request)
    return {"status": "success", "task_id": task_id}


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    task = get_task(task_id)
    if task is None:
        return {"status": "error", "message": "작업을 찾을 수 없습니다."}
    return {"status": "success", "task": task}

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