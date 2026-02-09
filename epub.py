import os
import sys
from pathlib import Path
import zipfile
import logging
import json

import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

import colorama

import utils
 

def extract_epub(epub_path: Path) -> dict:
    if not epub_path.exists() or not epub_path.is_file():
        raise FileNotFoundError(f"EPUB 파일을 찾을 수 없습니다: {epub_path}")
    elif epub_path.suffix.lower() != '.epub':
        raise ValueError(f"유효한 EPUB 파일이 아닙니다: {epub_path}")
    
    # workspace 내에 epub 추출 디렉토리 생성
    counter = 1
    output_dir = utils.get_workspace() / "extracted_epubs" / epub_path.stem
    if output_dir.exists():
        while True:
            new_output_dir = utils.get_workspace() / "extracted_epubs" / f"{epub_path.stem}({counter})"
            if not new_output_dir.exists():
                output_dir = new_output_dir
                break
            counter += 1
    else:
        output_dir = output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # log 파일
    log_filepath = output_dir / "log.txt"

    # unzip
    with zipfile.ZipFile(epub_path, 'r') as f:
        root = zipfile.Path(f)

        def get_file_by_suffix(suffix):
            return [p for p in root.rglob(f"*.{suffix}") if p.is_file()]

        # opf 파일 가져오기
        opf_path = get_file_by_suffix("opf")[0]
        if not opf_path: raise FileNotFoundError("OPF 파일을 찾을 수 없습니다.")
        logging.info(f"Found OPF file: {opf_path}")

        # opf 파일 파싱
        with opf_path.open('r', encoding='utf-8') as f:
            opf_soup = BeautifulSoup(f, 'xml')
        
        manifest = opf_soup.find('manifest')
        xhtml_files = manifest.find_all('item', attrs={'media-type': 'application/xhtml+xml'}) or \
            manifest.find_all('item', attrs={'media-type': 'application/x-dtbook+xml'})
        
        # xhtml 파일 목록 추출 로직 추가해야함 -> legacy 코드 참고


        if not xhtml_files: raise FileNotFoundError("OPF 파일에서 xhtml 파일 목록을 추출할 수 없습니다.")
        logging.info(f"Found {len(xhtml_files)} XHTML files in OPF.")

    data = {}

    return data
    

