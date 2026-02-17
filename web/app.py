from fastapi import FastAPI, Request , UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import json

from utils import get_workspace

app = FastAPI()

TITLE = "Rosetta(Temporary)"
UPLOAD_DIR = get_workspace() / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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