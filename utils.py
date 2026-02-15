import os
from pathlib import Path
import settings

def get_workspace() -> Path:
    workspace = Path.home() / ".epub_ai_translator"
    workspace.mkdir(parents=True, exist_ok=True)

    return workspace

def get_api_key(key_name: str) -> str:
    key = os.getenv(key_name)
    if not key:
        key = getattr(settings, key_name, None)
        if not key:
            raise ValueError(f"{key_name}가 설정되지 않았습니다.")
    return key
