import os
import sys
import re
from pathlib import Path
import zipfile
import logging
import json

import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup, element

import colorama

import utils
from exceptions import *
 

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
    log_path: Path = output_dir / "log.txt"

    # unzip epub
    with zipfile.ZipFile(epub_path, 'r') as f:
        root = zipfile.Path(f)

        def get_file_by_suffix(suffix: str) -> list[zipfile.Path]:
            return [p for p in root.rglob(f"*.{suffix}") if p.is_file()]
        
        def get_xhtml_files_from_opf(opf_path: zipfile.Path) -> list[element.Tag]:
            """
            OPF 파일에서 xhtml 파일 목록을 추출하고 올바른 순서로 정렬합니다.
            
            :param opf_path: OPF 파일 경로
            :type opf_path: zipfile.Path
            :return: xhtml 파일 목록
            :rtype: ResultSet[Tag]
            """
            
            with opf_path.open('r', encoding='utf-8') as f:
                opf_soup = BeautifulSoup(f, 'xml')
            
            # OPF 파일에서 manifest와 spine 가져오기
            manifest: element.Tag | None = opf_soup.find('manifest')
            if not manifest:
                raise NotValidOPFError("OPF 파일에 manifest 태그가 없습니다.")
            spine: element.Tag | None = opf_soup.find('spine')
            if not spine:
                raise NotValidOPFError("OPF 파일에 spine 태그가 없습니다.")

            # manifest 파일 목록 중 xhtml 파일 가져오기
            media_type_pattern = re.compile(r'application/(xhtml\+xml|x-dtbook\+xml)', re.IGNORECASE)
            xhtml_files: element.ResultSet[element.Tag] = manifest.find_all('item', attrs={'media-type': media_type_pattern})
            if not xhtml_files:
                raise NotValidOPFError("OPF 파일의 manifest에 xhtml 파일이 없습니다.")

            # spine에 정의된 순서대로 정렬하고, spine에 없는 항목은 manifest 순서로 뒤에 추가
            idref_order = [item['idref'] for item in spine.find_all('itemref')]
            id_to_item = {item.get('id'): item for item in xhtml_files}

            ordered_items: list[element.Tag] = []
            added_ids = set()
            for item_id in idref_order:
                item = id_to_item.get(item_id)
                if item is not None:
                    ordered_items.append(item)
                    added_ids.add(item_id)

            for item in xhtml_files:
                item_id = item.get('id')
                if item_id not in added_ids:
                    ordered_items.append(item)

            return ordered_items

        # opf 파일 가져오기
        opf_path = get_file_by_suffix("opf")[0]
        if not opf_path: raise FileNotFoundError("OPF 파일을 찾을 수 없습니다.")
        logging.info(f"Found OPF file: {opf_path}")

        # opf 파일 파싱
        with opf_path.open('r', encoding='utf-8') as f:
            opf_soup = BeautifulSoup(f, 'xml')
        
        xhtml_files = get_xhtml_files_from_opf(opf_path)
        if not xhtml_files: 
            raise FileNotFoundError("OPF 파일에서 xhtml 파일 목록을 추출할 수 없습니다.")

        logging.info(f"Found {len(xhtml_files)} XHTML files in OPF.")

    data: dict = {
        "output_dir": output_dir
    }

    return data


