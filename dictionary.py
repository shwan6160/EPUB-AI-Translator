import json
import dotenv

from epub import *
from provider import *
from prompts.dictionary import *
from utils.utils import *

dotenv.load_dotenv(".env")

# --------------------------------
# 공용 함수
# --------------------------------

def load_full_text_from_epub(epub_extracted: Epub) -> str:
    full_text = text_from_epub(epub_extracted)
    full_text = trim_ruby_text(full_text)
    if not full_text.strip():
        raise ValueError("EPUB에서 추출한 텍스트가 비어 있습니다.")

    return full_text

def parse_dictionary_json(response_text: str) -> dict:
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise AssertionError(f"응답이 유효한 JSON이 아닙니다: {e}\n원문:\n{response_text}") from e

    if not isinstance(parsed, dict):
        raise AssertionError("최상위 JSON은 object여야 합니다.")
    if "characters" not in parsed:
        raise AssertionError("characters 키가 필요합니다.")
    if "groups" not in parsed:
        raise AssertionError("groups 키가 필요합니다.")
    if not isinstance(parsed["characters"], list):
        raise AssertionError("characters는 배열이어야 합니다.")
    if not isinstance(parsed["groups"], list):
        raise AssertionError("groups는 배열이어야 합니다.")

    return parsed
