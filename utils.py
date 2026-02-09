import os
from pathlib import Path

def get_workspace() -> Path:
    workspace = Path.home() / ".epub_ai_translator"
    workspace.mkdir(parents=True, exist_ok=True)

    return workspace