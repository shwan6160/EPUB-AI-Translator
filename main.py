import csv, json
import os
import zipfile
import re

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

from epub import *
from provider import *
from prompts.dictionary import *

#epub 함수 사용 작업중
epub_file_path = input("EPUB 파일 경로를 입력하세요: ")

epub = extract_epub(Path(epub_file_path))

full_text = trim_ruby_text(text_from_epub(epub["output_dir"], epub["xhtml_files"]))

# 캐릭터 사전 생성 코드(제미나이)
gemini_key = dotenv.get_key(".env", "GEMINI_KEY")
if not gemini_key:
    raise ValueError("GEMINI_KEY가 설정되지 않았습니다.")
char_dict_generator = GoogleGenai(
    config = GoogleGenaiConfig(
        api_key = gemini_key,
        model_name = "gemini-3-pro-preview",
        generation_config = genai.types.GenerateContentConfig(
            system_instruction = CHARACTER_DICT_SYSTEM_PROMPT,
            temperature = 0.2,
            top_p = 0.8,
            top_k = 40,
            response_mime_type = "application/json"
        )
    )
)