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
from epub import extract_epub
from dictionary import load_full_text_from_epub, parse_dictionary_json

from prompts.dictionary import *

provider_select = "Google"  # "Google" 또는 "OpenRouter" 중 선택

# epub 파일 경로 확인 및 텍스트 추출
epub_file_path = input("EPUB 파일 경로를 입력하세요: ")
epub_extracted = extract_epub(Path(epub_file_path), get_workspace())
full_text = load_full_text_from_epub(epub_extracted)

if provider_select == "Google":
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

    with open(get_workspace() / Path(epub_file_path).with_name(f"{Path(epub_file_path).stem}_character_dictionary.json"), "w", encoding="utf-8") as f:
        json.dump(char_dict, f, ensure_ascii=False, indent=2)

elif provider_select == "OpenRouter":
    key = get_api_key("OPENROUTER_KEY")
    if not key:
        print("OPENROUTER_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
        key = input("OPENROUTER_KEY: ").strip()
        if not key:
            raise ValueError("API 키가 설정되지 않았습니다.")
    
    model = input("사용할 모델 이름을 입력하세요: ")
    provider = OpenRouter(
        config=OpenRouterConfig(
            api_key=key,
            model_name=model,
            system_prompt=CHARACTER_DICT_SYSTEM_PROMPT,
            temperature=0.2,
            top_p=0.8,
            response_format={"type": "json_object"},
            app_name="EPUB-AI-Translator",
        )
    )

    response_text = provider.generate_content(
        user_prompt=CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)
    )
    char_dict = parse_dictionary_json(response_text)

    with open(get_workspace() / Path(epub_file_path).with_name(f"{Path(epub_file_path).stem}_character_dictionary.json"), "w", encoding="utf-8") as f:
        json.dump(char_dict, f, ensure_ascii=False, indent=2)

else:
    print("알 수 없는 모델 제공자입니다.")

