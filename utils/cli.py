import json
import os
from pathlib import Path

from google import genai

from utils.utils import get_api_key, get_workspace
from epub import Epub
from dictionary import parse_dictionary_json, load_full_text_from_epub

from provider import GoogleGenai, GoogleGenaiConfig, OpenRouter, OpenRouterConfig
from prompts.dictionary import (
    CHARACTER_DICT_SYSTEM_PROMPT,
    CHARACTER_DICT_USER_PROMPT,
    CHARACTER_DICT_SYSTEM_PROMPT_QWEN,
    CHARACTER_DICT_USER_PROMPT_QWEN
)
from prompts.translation import base_prompt_instructions, base_prompt_text

# cli utils
def select_provider(provider_select: str|None = None) -> str:
    provider_list = ["Google", "OpenRouter", "Copilot"]
    if provider_select in provider_list:
        return provider_select

    print("사용할 모델 제공자를 선택하세요:")
    for p in enumerate(provider_list, start=1):
        print(f"{p[0]}. {p[1]}")

    while True:
        provider_select = input("Provider: ")
        if provider_select.isdigit() and 1 <= int(provider_select) <= len(provider_list):
            return provider_list[int(provider_select)-1]
        elif provider_select in provider_list:
            return provider_select
        else:
            print("잘못된 입력입니다. 다시 입력하십시오.")

def select_model(available_models: list[str]) -> str:
    print("사용 가능한 모델 목록:")
    for m in enumerate(available_models, start=1):
        print(f"{m[0]}. {m[1]}")
    while True:
        model_select = input("모델: ")
        if model_select.isdigit() and 1 <= int(model_select) <= len(available_models):
            return available_models[int(model_select)-1]
        else:
            print("잘못된 입력입니다. 다시 입력하십시오.")

def yn_check(yes: bool, prompt: str) -> bool:
    if yes:
        return True
    while True:
        user_input = input(prompt + " (y/n):").strip().lower()
        if user_input in ['y', 'yes']:
            return True
        elif user_input in ['n', 'no']:
            return False
        else:
            print("'y' 또는 'n'을 입력하십시오.")


class RunWorker:
    """
    CLI에서 번역 파이프라인 자체를 다루는 객체
    """
    def __init__(
        self,
        epub_file_value: str,
        provider_value: str | None,
        model_value: str | None,
        key_value: str | None,
        yes_value: bool,
    ):
        self.epub_file_path = Path(epub_file_value)
        self.char_dict_path = self.epub_file_path.with_name(f"{self.epub_file_path.stem}_character_dictionary.json")

        self.provider_select = provider_value
        self.model = model_value
        self.key = key_value
        self.yes = yes_value

        self.dict_provider = None
        self.dict_model = None
        self.translate_provider = None
        self.translate_model = None
        self.char_dict = None
        self.epub_extracted = None

        self.full_text = ""

    def _load_full_text(self) -> None:
        self.epub_extracted = Epub(self.epub_file_path, get_workspace())
        self.full_text = load_full_text_from_epub(self.epub_extracted)

    def _ensure_key(self, env_name: str) -> str:
        self.key = get_api_key(env_name) if self.key is None else self.key
        if not self.key:
            print(f"{env_name}가 설정되지 않았습니다. API 키를 입력해 주십시오.")
            self.key = input(f"{env_name}: ").strip()
            if not self.key:
                raise ValueError("API 키가 설정되지 않았습니다.")
        return self.key

    def prepare_character_dictionary(self) -> None:
        self._load_full_text()

        if self.char_dict_path.exists():
            print(f"기존 캐릭터 사전이 발견되었습니다: {self.char_dict_path}")
            load_dict = yn_check(self.yes, "기존 캐릭터 사전을 로드하시겠습니까?")

            if load_dict:
                try:
                    with open(self.char_dict_path, "r", encoding="utf-8") as f:
                        self.char_dict = json.load(f)
                    parse_dictionary_json(json.dumps(self.char_dict, ensure_ascii=False))
                    print(f"기존 캐릭터 사전을 로드했습니다: {self.char_dict_path}")
                except Exception as e:
                    print(f"기존 캐릭터 사전 로드 실패: {e}")
                    self.char_dict = None

        if self.char_dict is None:
            print("캐릭터 사전 파일을 찾을 수 없습니다.")
            if not yn_check(self.yes, "캐릭터 사전을 새로 생성하시겠습니까?"):
                print("프로그램을 종료합니다.")
                os._exit(1)

            self.dict_provider = select_provider(self.provider_select)
            self.dict_model = None

            if self.dict_provider == "Google":
                key_value = self._ensure_key("GEMINI_KEY")

                available_models = []
                try:
                    for m in GoogleGenai.list_available_models(key_value):
                        if "gemini" in m or "gemma" in m:
                            available_models.append(m.replace("models/", ""))
                except Exception as e:
                    print(f"모델 목록을 불러오는 중 오류가 발생했습니다: {e}")
                    raise

                self.dict_model = select_model(available_models)

            elif self.dict_provider == "OpenRouter":
                self._ensure_key("OPENROUTER_KEY")
                available_models = [
                    "qwen/qwen3-max-thinking",
                    "moonshotai/kimi-k2.5",
                    "z-ai/GLM-5",
                ]
                self.dict_model = select_model(available_models)

            elif self.dict_provider == "Copilot":
                print("Copilot 모델 제공자는 아직 구현되지 않았습니다.")

            else:
                print("알 수 없는 모델 제공자입니다.")
                os._exit(1)

            print("선택을 확인합니다.")
            print(f"EPUB 파일: {self.epub_file_path}")
            print(f"모델 제공자: {self.dict_provider}")
            print(f"모델 이름: {self.dict_model}")

            if not yn_check(self.yes, "위 선택으로 캐릭터 사전을 생성하시겠습니까?"):
                print("프로그램을 종료합니다.")
                os._exit(1)

            if self.dict_provider == "Google":
                if self.key is None or self.dict_model is None:
                    raise ValueError("캐릭터 사전 생성을 위한 모델/키 설정이 올바르지 않습니다.")

                instance = GoogleGenai(
                    config=GoogleGenaiConfig(
                        api_key=self.key,
                        model_name=self.dict_model,
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
                    user_prompt=CHARACTER_DICT_USER_PROMPT.format(novel_text=self.full_text)
                )
                self.char_dict = parse_dictionary_json(response_text)

            elif self.dict_provider == "OpenRouter":
                if self.key is None or self.dict_model is None:
                    raise ValueError("캐릭터 사전 생성을 위한 모델/키 설정이 올바르지 않습니다.")

                system_prompt = CHARACTER_DICT_SYSTEM_PROMPT
                user_prompt = CHARACTER_DICT_USER_PROMPT.format(novel_text=self.full_text)

                if self.dict_model == "qwen/qwen3-max-thinking":
                    system_prompt = CHARACTER_DICT_SYSTEM_PROMPT_QWEN
                    user_prompt = CHARACTER_DICT_USER_PROMPT_QWEN.format(novel_text=self.full_text)

                instance = OpenRouter(
                    config=OpenRouterConfig(
                        api_key=self.key,
                        model_name=self.dict_model,
                        system_prompt=system_prompt,
                        temperature=0.2,
                        top_p=0.8,
                        response_format={"type": "json_object"},
                        app_name="EPUB-AI-Translator",
                    )
                )

                response_text = instance.generate_content(user_prompt=user_prompt)
                self.char_dict = parse_dictionary_json(response_text)

            if yn_check(self.yes, "캐릭터 사전이 새로 생성되었습니다.\n사전을 파일로 저장하겠습니까?"):
                with open(self.char_dict_path, "w", encoding="utf-8") as f:
                    json.dump(self.char_dict, f, ensure_ascii=False, indent=2)

    def setup_translation_model(self) -> None:
        if self.dict_provider is None or self.dict_model is None:
            return

        if yn_check(self.yes, "캐릭터 사전 모델 설정을 그대로 사용하겠습니까?"):
            self.translate_provider = self.dict_provider
            self.translate_model = self.dict_model
        else:
            self.translate_provider = select_provider(self.provider_select)
            self.translate_model = None

            if self.translate_provider == "Google":
                key_value = self._ensure_key("GEMINI_KEY")
                available_models = []
                try:
                    for m in GoogleGenai.list_available_models(key_value):
                        available_models.append(m.replace("models/", ""))
                except Exception as e:
                    print(f"모델 목록을 불러오는 중 오류가 발생했습니다: {e}")
                    raise
                self.translate_model = select_model(available_models)
            elif self.translate_provider == "OpenRouter":
                self._ensure_key("OPENROUTER_KEY")
                available_models = [
                    "qwen/qwen3-max-thinking",
                    "moonshotai/kimi-k2.5",
                    "z-ai/GLM-5",
                ]
                self.translate_model = select_model(available_models)
            elif self.translate_provider == "Copilot":
                print("Copilot 모델 제공자는 아직 구현되지 않았습니다.")
            else:
                print("알 수 없는 모델 제공자입니다.")
                os._exit(1)

    def run_translation(self) -> None:
        from epub import repackage_epub, translate_epub as run_translate_epub

        if self.translate_provider == "Google":
            if self.key is None or self.translate_model is None:
                raise ValueError("번역을 위한 모델/키 설정이 올바르지 않습니다.")
            if self.epub_extracted is None:
                raise ValueError("EPUB 추출 정보가 없습니다.")

            char_dict_text = json.dumps(self.char_dict, ensure_ascii=False, indent=2)
            translation_system_prompt = base_prompt_instructions.format(char_dict_text=char_dict_text)

            translate_instance = GoogleGenai(
                config=GoogleGenaiConfig(
                    api_key=self.key,
                    model_name=self.translate_model,
                    generation_config=genai.types.GenerateContentConfig(
                        system_instruction=translation_system_prompt,
                        temperature=0.7,
                        top_p=0.9,
                        top_k=40,
                    ),
                )
            )

            def translate_fn(chunk_text: str, prev_context: str) -> str:
                user_prompt = base_prompt_text.format(
                    prev_context=prev_context,
                    current_text=chunk_text,
                )
                result = translate_instance.generate_content(user_prompt=user_prompt)
                return result

            max_workers_input = input("병렬 워커 수를 입력하세요 (기본: 10): ").strip()
            max_workers = int(max_workers_input) if max_workers_input.isdigit() and int(max_workers_input) > 0 else 10

            print(f"\nEPUB 번역을 시작합니다... (chunk 최대 8000자, 병렬 워커 {max_workers}개)")
            output_dir = run_translate_epub(
                epub=self.epub_extracted,
                translate_fn=translate_fn,
                target_lang="ko",
                max_chars=8000,
                max_workers=max_workers,
            )

            output_epub_path = self.epub_file_path.with_name(f"{self.epub_file_path.stem}_ko.epub")
            repackage_epub(output_dir, output_epub_path)
            print(f"\n번역 완료! 출력 파일: {output_epub_path}")

        elif self.translate_provider == "OpenRouter":
            print("OpenRouter 번역이 아직 구현되지 않았습니다.")

    def execute(self) -> None:
        self.prepare_character_dictionary()
        self.setup_translation_model()
        self.run_translation()

