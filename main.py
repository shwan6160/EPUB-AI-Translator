import csv, json
import os
import zipfile
import re
from pathlib import Path

import time, datetime
from xml.dom import minidom

import io, shutil, posixpath
import logging

import concurrent.futures
import copy
import uuid
import traceback

import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

from PIL import Image, ImageDraw, ImageFont

from tqdm import tqdm
import colorama

import dotenv
from google import genai

from provider import GoogleGenai, GoogleGenaiConfig, OpenRouter, OpenRouterConfig
from utils import get_workspace, get_api_key
from epub import extract_epub, translate_epub, repackage_epub
from dictionary import load_full_text_from_epub, parse_dictionary_json

from prompts.dictionary import *
from prompts.translation import base_prompt_instructions, base_prompt_text

provider_select = "Google"  # "Google" 또는 "OpenRouter" 중 선택

# epub 파일 경로 확인 및 텍스트 추출
epub_file_path = input("EPUB 파일 경로를 입력하세요: ")
epub_extracted = extract_epub(Path(epub_file_path), get_workspace())
full_text = load_full_text_from_epub(epub_extracted)

key = ""
model = ""
char_dict = None
char_dict_path = get_workspace() / Path(epub_file_path).with_name(f"{Path(epub_file_path).stem}_character_dictionary.json")

# 기존 캐릭터 사전 JSON이 있으면 로드 시도
if char_dict_path.exists():
    try:
        with open(char_dict_path, "r", encoding="utf-8") as f:
            char_dict = json.load(f)
        # parse_dictionary_json 검증 로직 재활용 (characters, groups 키 확인)
        parse_dictionary_json(json.dumps(char_dict, ensure_ascii=False))
        print(f"기존 캐릭터 사전을 로드했습니다: {char_dict_path}")
    except Exception as e:
        print(f"기존 캐릭터 사전 로드 실패: {e}")
        char_dict = None

if char_dict is None:
    provider_select = input("provider: ")

if char_dict is None and provider_select == "Google":
    key = get_api_key("GEMINI_KEY")
    if not key:
        print("GEMINI_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
        key = input("GEMINI_KEY: ").strip()
        if not key:
            raise ValueError("API 키가 설정되지 않았습니다.")

    try:
        available_models = GoogleGenai.list_available_models(key)
    except Exception as e:
        print(f"모델 목록을 불러오는 중 오류가 발생했습니다: {e}")
        raise

    print("사용 가능한 모델 목록:")
    for model in available_models:
        print(f"  - {model}")

    model = input("사용할 모델 이름을 입력하세요: ")

    provider = GoogleGenai(
        config = GoogleGenaiConfig(
            api_key = key,
            model_name = model,
            generation_config = genai.types.GenerateContentConfig(
                system_instruction = CHARACTER_DICT_SYSTEM_PROMPT,
                temperature = 0.2,
                top_p = 0.8,
                top_k = 40,
                response_mime_type = "application/json"
            )
        )
    )

    response_text = provider.generate_content(
        user_prompt=CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)
    )
    char_dict = parse_dictionary_json(response_text)

    with open(char_dict_path, "w", encoding="utf-8") as f:
        json.dump(char_dict, f, ensure_ascii=False, indent=2)

elif char_dict is None and provider_select == "OpenRouter":
    key = get_api_key("OPENROUTER_KEY")
    if not key:
        print("OPENROUTER_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
        key = input("OPENROUTER_KEY: ").strip()
        if not key:
            raise ValueError("API 키가 설정되지 않았습니다.")
    
    model = input("사용할 모델 이름을 입력하세요: ")
    system_prompt = CHARACTER_DICT_SYSTEM_PROMPT
    user_prompt = CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)

    if model == "qwen/qwen3-max-thinking":
        system_prompt = CHARACTER_DICT_SYSTEM_PROMPT_QWEN
        user_prompt = CHARACTER_DICT_USER_PROMPT_QWEN.format(novel_text=full_text)

    provider = OpenRouter(
        config=OpenRouterConfig(
            api_key=key,
            model_name=model,
            system_prompt=system_prompt,
            temperature=0.2,
            top_p=0.8,
            response_format={"type": "json_object"},
            app_name="EPUB-AI-Translator",
        )
    )

    response_text = provider.generate_content(
        user_prompt=user_prompt
    )
    char_dict = parse_dictionary_json(response_text)
    with open(char_dict_path, "w", encoding="utf-8") as f:
        json.dump(char_dict, f, ensure_ascii=False, indent=2)

elif char_dict is None:
    print("알 수 없는 모델 제공자입니다.")
    char_dict = None

# EPUB 번역
if char_dict is not None:
    proceed = input("\njson 파일을 검토 후 번역하십시오.\nEPUB 번역을 진행하시겠습니까? (y/n): ").strip().lower()
    if proceed == 'y':
        char_dict = json.load(open(char_dict_path, "r", encoding="utf-8"))
        # Gemini API 키 확인 (Google provider 사용 시 재사용, 아니면 별도 입력)
        if provider_select == "Google":
            gemini_key = key
        else:
            try:
                gemini_key = get_api_key("GEMINI_KEY")
            except ValueError:
                print("번역에 사용할 GEMINI_KEY가 설정되지 않았습니다.")
                gemini_key = input("GEMINI_KEY: ").strip()
                if not gemini_key:
                    raise ValueError("API 키가 설정되지 않았습니다.")

        translate_model = input("번역에 사용할 Gemini 모델 이름을 입력하세요 (기본: gemini-2.5-flash): ").strip()
        if not translate_model:
            translate_model = "gemini-2.5-flash"

        # 캐릭터 사전을 시스템 프롬프트에 포함
        char_dict_text = json.dumps(char_dict, ensure_ascii=False, indent=2)
        translation_system_prompt = base_prompt_instructions.format(char_dict_text=char_dict_text)

        translation_provider = GoogleGenai(
            config=GoogleGenaiConfig(
                api_key=gemini_key,
                model_name=translate_model,
                generation_config=genai.types.GenerateContentConfig(
                    system_instruction=translation_system_prompt,
                    temperature=0.7,
                    top_p=0.9,
                    top_k=40,
                )
            )
        )

        # translate_fn: 파일 내 chunk간 prev_context는 translate_and_inject에서 자동 관리
        def translate_fn(chunk_text: str, prev_context: str) -> str:
            user_prompt = base_prompt_text.format(
                prev_context=prev_context,
                current_text=chunk_text
            )
            result = translation_provider.generate_content(user_prompt=user_prompt)
            return result

        max_workers_input = input("병렬 워커 수를 입력하세요 (기본: 10): ").strip()
        max_workers = int(max_workers_input) if max_workers_input.isdigit() and int(max_workers_input) > 0 else 10

        print(f"\nEPUB 번역을 시작합니다... (chunk 최대 8000자, 병렬 워커 {max_workers}개)")
        output_dir = translate_epub(
            epub_path=Path(epub_file_path),
            workspace=get_workspace(),
            translate_fn=translate_fn,
            target_lang="ko",
            max_chars=8000,
            max_workers=max_workers,
        )

        # EPUB 리패키징
        output_epub_path = Path(epub_file_path).with_name(f"{Path(epub_file_path).stem}_ko.epub")
        repackage_epub(output_dir, output_epub_path)
        print(f"\n번역 완료! 출력 파일: {output_epub_path}")
    else:
        print("번역을 건너뜁니다.")

