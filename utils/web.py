import json
from pathlib import Path
from typing import Callable

from google import genai

from dictionary import load_full_text_from_epub, parse_dictionary_json
from epub import Epub, repackage_epub, translate_epub
from prompts.dictionary import (
    CHARACTER_DICT_SYSTEM_PROMPT,
    CHARACTER_DICT_SYSTEM_PROMPT_QWEN,
    CHARACTER_DICT_USER_PROMPT,
    CHARACTER_DICT_USER_PROMPT_QWEN,
)
from prompts.translation import base_prompt_instructions, base_prompt_text
from provider import GoogleGenai, GoogleGenaiConfig, OpenRouter, OpenRouterConfig
from utils.utils import get_api_key, get_workspace

OPENROUTER_MODELS = {
    "qwen/qwen3-max-thinking",
    "moonshotai/kimi-k2.5",
    "z-ai/GLM-5",
}


def _resolve_api_key(provider: str, key: str | None) -> str:
    if key:
        return key

    if provider == "Google":
        return get_api_key("GEMINI_KEY")
    if provider == "OpenRouter":
        return get_api_key("OPENROUTER_KEY")

    raise ValueError(f"지원하지 않는 provider 입니다: {provider}")


def _get_char_dict_path(epub_path: Path) -> Path:
    return epub_path.with_name(f"{epub_path.stem}_character_dictionary.json")


def generate_character_dictionary(
    epub_path: Path,
    provider: str,
    model: str,
    key: str | None = None,
    save_to_file: bool = True,
    progress_logger: Callable[[str], None] | None = None,
) -> dict:
    if provider not in {"Google", "OpenRouter"}:
        raise ValueError("현재 캐릭터 사전 생성은 Google/OpenRouter만 지원합니다.")

    api_key = _resolve_api_key(provider, key)
    if progress_logger is not None:
        progress_logger("EPUB 추출 및 원문 로딩 시작")
    epub_extracted = Epub(epub_path, get_workspace())
    full_text = load_full_text_from_epub(epub_extracted)
    if progress_logger is not None:
        progress_logger("원문 로딩 완료, 캐릭터 사전 생성 요청")

    if provider == "Google":
        instance = GoogleGenai(
            config=GoogleGenaiConfig(
                api_key=api_key,
                model_name=model,
                generation_config=genai.types.GenerateContentConfig(
                    system_instruction=CHARACTER_DICT_SYSTEM_PROMPT,
                    temperature=0.2,
                    top_p=0.8,
                    top_k=40,
                    response_mime_type="application/json",
                ),
            )
        )
        response_text = instance.generate_content(
            user_prompt=CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)
        )
        char_dict = parse_dictionary_json(response_text)
    else:
        system_prompt = CHARACTER_DICT_SYSTEM_PROMPT
        user_prompt = CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)

        if model == "qwen/qwen3-max-thinking":
            system_prompt = CHARACTER_DICT_SYSTEM_PROMPT_QWEN
            user_prompt = CHARACTER_DICT_USER_PROMPT_QWEN.format(novel_text=full_text)

        instance = OpenRouter(
            config=OpenRouterConfig(
                api_key=api_key,
                model_name=model,
                system_prompt=system_prompt,
                temperature=0.2,
                top_p=0.8,
                response_format={"type": "json_object"},
                app_name="EPUB-AI-Translator",
            )
        )
        response_text = instance.generate_content(user_prompt=user_prompt)
        char_dict = parse_dictionary_json(response_text)

    char_dict_path = _get_char_dict_path(epub_path)
    if save_to_file:
        if progress_logger is not None:
            progress_logger("캐릭터 사전 파일 저장")
        with open(char_dict_path, "w", encoding="utf-8") as f:
            json.dump(char_dict, f, ensure_ascii=False, indent=2)

    if progress_logger is not None:
        progress_logger("캐릭터 사전 생성 완료")

    return {
        "char_dict": char_dict,
        "char_dict_path": char_dict_path,
        "provider": provider,
        "model": model,
    }


def translate_epub_with_dictionary(
    epub_path: Path,
    provider: str,
    model: str,
    key: str | None = None,
    char_dict: dict | None = None,
    target_lang: str = "ko",
    max_chars: int = 8000,
    max_workers: int = 10,
    progress_logger: Callable[[str], None] | None = None,
) -> dict:
    if provider not in {"Google", "OpenRouter"}:
        raise ValueError("현재 번역은 Google/OpenRouter만 지원합니다.")

    api_key = _resolve_api_key(provider, key)
    if progress_logger is not None:
        progress_logger("번역 준비 시작")

    if char_dict is None:
        char_dict_path = _get_char_dict_path(epub_path)
        if not char_dict_path.exists():
            raise FileNotFoundError(f"캐릭터 사전 파일이 없습니다: {char_dict_path}")
        with open(char_dict_path, "r", encoding="utf-8") as f:
            char_dict = json.load(f)
        parse_dictionary_json(json.dumps(char_dict, ensure_ascii=False))
        if progress_logger is not None:
            progress_logger("캐릭터 사전 로드 완료")

    char_dict_text = json.dumps(char_dict, ensure_ascii=False, indent=2)
    translation_system_prompt = base_prompt_instructions.format(char_dict_text=char_dict_text)

    if provider == "Google":
        translate_instance = GoogleGenai(
            config=GoogleGenaiConfig(
                api_key=api_key,
                model_name=model,
                generation_config=genai.types.GenerateContentConfig(
                    system_instruction=translation_system_prompt,
                    temperature=0.7,
                    top_p=0.9,
                    top_k=40,
                ),
            )
        )
    else:
        translate_instance = OpenRouter(
            config=OpenRouterConfig(
                api_key=api_key,
                model_name=model,
                system_prompt=translation_system_prompt,
                temperature=0.7,
                top_p=0.9,
                app_name="EPUB-AI-Translator",
            )
        )

    def translate_fn(chunk_text: str, prev_context: str) -> str:
        user_prompt = base_prompt_text.format(
            prev_context=prev_context,
            current_text=chunk_text,
        )
        return translate_instance.generate_content(user_prompt=user_prompt)

    def file_progress(current: int, total: int, file_name: str) -> None:
        if progress_logger is None:
            return
        progress_logger(f"번역 진행 {current}/{total}: {file_name}")

    if progress_logger is not None:
        progress_logger("EPUB 추출 및 번역 시작")
    epub_extracted = Epub(epub_path, get_workspace())
    output_dir = translate_epub(
        epub=epub_extracted,
        translate_fn=translate_fn,
        target_lang=target_lang,
        max_chars=max_chars,
        max_workers=max_workers,
        progress_callback=file_progress,
    )

    output_epub_path = epub_path.with_name(f"{epub_path.stem}_{target_lang}.epub")
    if progress_logger is not None:
        progress_logger("EPUB 재패키징")
    repackage_epub(output_dir, output_epub_path)

    if progress_logger is not None:
        progress_logger("번역 작업 완료")

    return {
        "output_dir": output_dir,
        "output_epub_path": output_epub_path,
        "provider": provider,
        "model": model,
    }
