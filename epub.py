import re
from urllib.parse import quote, unquote
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
import zipfile
import logging
import concurrent.futures

from tqdm import tqdm

from bs4 import BeautifulSoup, element
from bs4.element import NavigableString, Tag

from exceptions import *

_XHTML_MULTI_VALUED_ATTRS: dict[str, list[str]] = {"*": ["class"]}


@dataclass
class TextSegment:
    """
    블록 요소 하나에서 추출한 텍스트 단위.
    EPUB 텍스트 추출 시 각 블록 요소(p, h1~h6 등)의 텍스트를 TextSegment로 추출하여
    원본 위치에 플레이스홀더를 삽입한 후, 번역 결과를 다시 DOM에 주입할 때 사용.    
    """
    index: int
    element: Tag
    original_text: str
    translated_text: str | None = None


_JP_INLINE_UNWRAP_CLASSES = {'koboSpan', 'tcy', 'upright'}
_PRESERVE_INLINE_CLASSES = {'em-sesame', 'bold', 'italic'}
_BLOCK_TAGS = frozenset({'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li'})
_INLINE_MARKER_RE = re.compile(r'<<([a-zA-Z0-9_-]+):(.+?)>>')
_INLINE_ATTR_SEP = "||"


def _encode_marker_value(value: str) -> str:
    return quote(value, safe="")


def _decode_marker_value(value: str) -> str:
    return unquote(value)


def simplify_dom(body: Tag) -> None:
    """
    body DOM을 in-place로 단순화합니다.
    
    제거 대상 (일본어 서적 전용 인라인 요소):
        - <ruby>base<rt>reading</rt></ruby> → base (후리가나 제거)
        - <rp> (루비 괄호)
        - <span class="koboSpan"> (Kobo 뷰어 전용 래핑)
        - <span class="tcy"> (세로쓰기 text-combine-upright)
        - <span class="upright"> (세로쓰기 단일 문자 정립)
    
    보존 대상:
        - 모든 블록 태그 (p, h1~h6, div 등)와 그 속성 (class, id)
        - 의미적 인라인 서식 (em-sesame, bold, italic)
        - <a> 링크, <br/> 빈 줄
    
    :param body: XHTML의 <body> Tag
    """
    for ruby in body.find_all('ruby'):
        rt = ruby.find('rt')
        if rt:
            rt.decompose()
        for rp in ruby.find_all('rp'):
            rp.decompose()
        ruby.unwrap()

    for cls in _JP_INLINE_UNWRAP_CLASSES:
        for span in body.find_all('span', class_=cls):
            span.unwrap()

    body.smooth()


def _extract_text_with_inline_markers(elem: Tag) -> str:
    """
    블록 요소 내부에서 텍스트를 추출합니다.
    
    _PRESERVE_INLINE_CLASSES에 해당하는 인라인 서식은 <<class:text>> 마커로 변환하여
    번역 후 복원할 수 있도록 합니다.
    
    예: <span class="em-sesame">友達</span> → <<em-sesame:友達>>
    
    :param elem: 텍스트를 추출할 블록 요소
    :returns: 인라인 마커가 포함된 plain text
    """
    parts: list[str] = []
    for child in elem.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == 'a':
                href = child.get('href', '') or ''
                anchor_id = child.get('id', '') or ''
                cls_list = child.get('class', [])
                cls_text = " ".join(cls_list) if isinstance(cls_list, list) else str(cls_list)
                inner_text = child.get_text()
                attrs = [
                    f"href={_encode_marker_value(href)}",
                    f"id={_encode_marker_value(anchor_id)}",
                    f"class={_encode_marker_value(cls_text)}",
                    f"text={_encode_marker_value(inner_text)}",
                ]
                parts.append(f"<<a:{_INLINE_ATTR_SEP.join(attrs)}>>")
                continue

            cls_list = child.get('class', [])
            cls_set = set(cls_list) if isinstance(cls_list, list) else {cls_list} if cls_list else set()
            marker_cls = cls_set & _PRESERVE_INLINE_CLASSES
            inner_text = child.get_text()
            if marker_cls:
                cls_name = next(iter(marker_cls))
                parts.append(f"<<{cls_name}:{inner_text}>>")
            else:
                parts.append(inner_text)
    return "".join(parts)


def _has_nested_block(elem: Tag) -> bool:
    """elem 자손 중 블록 태그가 있는지 확인."""
    for child in elem.descendants:
        if isinstance(child, Tag) and child.name in _BLOCK_TAGS:
            return True
    return False


def extract_segments(body: Tag) -> list[TextSegment]:
    """
    body에서 블록 요소별로 텍스트를 추출하고, 원본 위치에 플레이스홀더를 삽입합니다.
    
    각 블록 요소(p, h1~h6 등)의 텍스트를 TextSegment로 추출하고,
    원본 DOM의 해당 위치를 ``{{SEG:<index>}}`` 플레이스홀더로 치환하여
    스켈레톤 DOM을 생성합니다.
    
    빈 요소(<p><br/></p> 등)는 스킵하여 구조를 그대로 유지합니다.
    중첩 블록(div > p)이 있으면 최하위 블록만 처리합니다.
    
    :param body: simplify_dom() 처리가 완료된 <body> Tag
    :returns: 추출된 TextSegment 리스트
    """
    segments: list[TextSegment] = []
    index = 0

    for elem in list(body.descendants):
        if not isinstance(elem, Tag):
            continue
        if elem.name not in _BLOCK_TAGS:
            continue
        if _has_nested_block(elem):
            continue

        text = _extract_text_with_inline_markers(elem).strip()
        if not text:
            continue

        seg = TextSegment(index=index, element=elem, original_text=text)
        segments.append(seg)

        elem.clear()
        elem.string = f"{{{{SEG:{index}}}}}"
        index += 1

    return segments


def chunk_segments(
    segments: list[TextSegment],
    max_chars: int = 2000,
) -> list[list[TextSegment]]:
    """
    연속된 세그먼트를 번역기가 한 번에 처리 가능한 크기로 그룹화합니다.
    
    단일 세그먼트가 max_chars를 초과하더라도 최소 1개는 chunk에 포함됩니다.
    
    :param segments: 전체 TextSegment 리스트
    :param max_chars: chunk 최대 글자 수
    :returns: chunk 리스트 (각 chunk는 TextSegment 리스트)
    """
    chunks: list[list[TextSegment]] = []
    current_chunk: list[TextSegment] = []
    current_size = 0

    for seg in segments:
        seg_len = len(seg.original_text)
        if current_chunk and current_size + seg_len > max_chars:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(seg)
        current_size += seg_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def build_chunk_text(chunk: list[TextSegment]) -> str:
    """
    chunk 내 세그먼트를 ``[index] text`` 형태의 번호 마커와 함께 결합하여
    번역기 입력 텍스트를 생성합니다.
    
    번호 마커를 통해 번역 후 줄 수가 변동되더라도 세그먼트 매핑을 보장합니다.
    
    :param chunk: 하나의 chunk에 속한 TextSegment 리스트
    :returns: 번역기에 전달할 텍스트
    """
    return "\n".join(f"[{seg.index}] {seg.original_text}" for seg in chunk)


def parse_translated_chunk(translated_text: str, chunk: list[TextSegment]) -> dict[int, str]:
    """
    번역기 출력에서 [index] 마커를 파싱하여 {index: 번역문} 매핑을 반환합니다.
    
    파싱 우선순위:
        1. [index] 마커 기반 매핑
        2. 마커 실패 시, 비어있지 않은 줄 수가 chunk 크기와 일치하면 순서 매핑
        3. 최후 수단으로 전체 텍스트를 균등 분할하여 매핑
    
    :param translated_text: 번역기가 반환한 텍스트
    :param chunk: 원본 chunk의 TextSegment 리스트
    :returns: {segment_index: 번역문} 매핑
    """
    result: dict[int, str] = {}
    marker_pattern = re.compile(r'^\[(\d+)\]\s*(.*)$')
    lines = translated_text.strip().split('\n')

    current_index: int | None = None
    current_lines: list[str] = []

    for line in lines:
        m = marker_pattern.match(line)
        if m:
            if current_index is not None:
                result[current_index] = "\n".join(current_lines).strip()
            current_index = int(m.group(1))
            current_lines = [m.group(2)]
        else:
            if current_index is not None:
                current_lines.append(line)

    if current_index is not None:
        result[current_index] = "\n".join(current_lines).strip()

    expected_indices = {seg.index for seg in chunk}
    if result.keys() >= expected_indices:
        return {k: v for k, v in result.items() if k in expected_indices}

    cleaned_lines = []
    for line in lines:
        m = marker_pattern.match(line)
        cleaned_lines.append(m.group(2) if m else line)

    non_empty = [l for l in cleaned_lines if l.strip()]
    if len(non_empty) == len(chunk):
        return {seg.index: text.strip() for seg, text in zip(chunk, non_empty)}

    logging.warning(
        f"번역 결과 줄 수 불일치: 기대 {len(chunk)}줄, 수신 {len(non_empty)}줄. "
        f"비율 기반 매핑을 시도합니다."
    )
    full_text = translated_text.strip()
    chunk_count = len(chunk)
    avg_len = len(full_text) // chunk_count if chunk_count else 1
    result = {}
    for i, seg in enumerate(chunk):
        start = i * avg_len
        end = (i + 1) * avg_len if i < chunk_count - 1 else len(full_text)
        result[seg.index] = full_text[start:end].strip()
    return result


def translate_and_inject(
    segments: list[TextSegment],
    translate_fn: Callable[[str, str], str],
    max_chars: int = 8000,
) -> None:
    """
    세그먼트를 청킹하여 번역하고, 스켈레톤 DOM에 번역문을 재삽입합니다.
    
    내부적으로 chunk_segments → build_chunk_text → translate_fn →
    parse_translated_chunk → _inject_translations 순서로 진행됩니다.
    파일 내 chunk간 이전 문맥(prev_context)을 자동으로 전달합니다.
    
    :param segments: extract_segments()로 추출된 전체 세그먼트 리스트
    :param translate_fn: def translation(text_chunk: str, prev_context: str) -> str 형태의 번역 함수
    :param max_chars: chunk 최대 글자 수
    """
    chunks = chunk_segments(segments, max_chars)
    prev_context = ""

    for chunk in chunks:
        chunk_text = build_chunk_text(chunk)
        translated = translate_fn(chunk_text, prev_context)
        mapping = parse_translated_chunk(translated, chunk)

        for seg in chunk:
            seg.translated_text = mapping.get(seg.index, seg.original_text)

        prev_context = chunk_text

    _inject_translations(segments)


def _inject_translations(segments: list[TextSegment]) -> None:
    """
    스켈레톤 DOM의 ``{{SEG:<index>}}`` 플레이스홀더를 번역문으로 치환합니다.
    
    번역문에 ``<<class:text>>`` 인라인 마커가 포함되어 있으면
    ``<span class="class">text</span>``으로 복원합니다.
    
    :param segments: translated_text가 채워진 TextSegment 리스트
    """
    for seg in segments:
        text = seg.translated_text if seg.translated_text else seg.original_text
        seg.element.clear()

        parts = _INLINE_MARKER_RE.split(text)
        if len(parts) == 1:
            seg.element.string = text
        else:
            i = 0
            while i < len(parts):
                if i % 3 == 0:
                    if parts[i]:
                        seg.element.append(NavigableString(parts[i]))
                elif i % 3 == 1:
                    cls_name = parts[i]
                    inner = parts[i + 1] if i + 1 < len(parts) else ""
                    if cls_name == 'a':
                        attrs = {}
                        for item in inner.split(_INLINE_ATTR_SEP):
                            if "=" not in item:
                                continue
                            key, value = item.split("=", 1)
                            attrs[key] = _decode_marker_value(value)
                        anchor_text = attrs.pop("text", "")
                        anchor = BeautifulSoup("", 'html.parser').new_tag("a")
                        if attrs.get("href"):
                            anchor["href"] = attrs["href"]
                        if attrs.get("id"):
                            anchor["id"] = attrs["id"]
                        if attrs.get("class"):
                            anchor["class"] = attrs["class"].split()
                        if anchor_text:
                            anchor.append(NavigableString(anchor_text))
                        seg.element.append(anchor)
                    else:
                        span_soup = BeautifulSoup(
                            f'<span class="{cls_name}">{inner}</span>', 'html.parser'
                        )
                        new_span = span_soup.find('span')
                        if new_span:
                            seg.element.append(new_span)
                    i += 1
                i += 1


def postprocess_xhtml(soup: BeautifulSoup, target_lang: str = "ko") -> None:
    """
    번역 완료된 XHTML에 대한 후처리를 수행합니다.
    
    - <html> 태그의 lang/xml:lang을 target_lang으로 변경
    - 세로쓰기 클래스 vrtl → 가로쓰기 hltr로 전환 (CSS 셀렉터 매칭 유지)
    - Kobo 전용 script(kobo.js) 및 style(koboSpanStyle) 제거
    
    :param soup: 번역이 완료된 전체 XHTML의 BeautifulSoup 객체
    :param target_lang: 대상 언어 코드 (기본 "ko")
    """
    html_tag = soup.find('html')
    if html_tag and isinstance(html_tag, Tag):
        html_tag['lang'] = target_lang
        html_tag['xml:lang'] = target_lang

        classes = html_tag.get('class')
        if isinstance(classes, list):
            html_tag['class'] = ['hltr' if c == 'vrtl' else c for c in classes]  # type: ignore[assignment]
        elif isinstance(classes, str) and classes == 'vrtl':
            html_tag['class'] = 'hltr'

    for script in soup.find_all('script', src=re.compile(r'kobo\.js')):
        script.decompose()
    for style in soup.find_all('style', id='koboSpanStyle'):
        style.decompose()


def translate_xhtml(
    xhtml_path: Path,
    translate_fn: Callable[[str, str], str],
    target_lang: str = "ko",
    max_chars: int = 8000,
) -> str:
    """
    단일 XHTML 파일을 번역하여 구조가 보존된 XHTML 문자열을 반환합니다.
    
    simplify_dom → extract_segments → translate_and_inject → postprocess_xhtml
    파이프라인을 순차 실행합니다.
    
    :param xhtml_path: 원본 XHTML 파일 경로
    :param translate_fn: def translation(text_chunk: str, prev_context: str) -> str 형태의 번역 함수
    :param target_lang: 번역 대상 언어 코드
    :param max_chars: 번역기 1회 호출 당 최대 글자 수
    :returns: 번역된 XHTML 문자열
    """
    with open(xhtml_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'xml', multi_valued_attributes=_XHTML_MULTI_VALUED_ATTRS)

    body = soup.find('body')
    if not body:
        logging.warning(f"XHTML 파일에 body 태그가 없습니다: {xhtml_path}")
        return str(soup)

    simplify_dom(body)
    segments = extract_segments(body)

    if not segments:
        logging.info(f"번역 대상 텍스트가 없습니다: {xhtml_path}")
        postprocess_xhtml(soup, target_lang)
        return str(soup)

    translate_and_inject(segments, translate_fn, max_chars)
    postprocess_xhtml(soup, target_lang)

    return str(soup)


def translate_epub(
    epub_path: Path,
    workspace: Path,
    translate_fn: Callable[[str, str], str],
    target_lang: str = "ko",
    max_chars: int = 8000,
    max_workers: int = 10,
) -> Path:
    """
    EPUB 파일 전체를 번역합니다.
    
    extract_epub()으로 추출 후, 각 XHTML 파일에 translate_xhtml()을 적용하고
    번역 결과를 추출 디렉토리에 덮어씁니다.
    max_workers > 1이면 XHTML 파일을 병렬로 번역합니다.
    
    :param epub_path: 원본 EPUB 파일 경로
    :param workspace: 작업 디렉토리
    :param translate_fn: def translation(text_chunk: str, prev_context: str) -> str
    :param target_lang: 대상 언어 코드
    :param max_chars: 번역기 1회 호출 당 최대 글자 수
    :param max_workers: 병렬 처리 워커 수 (기본 10)
    :returns: 번역된 EPUB이 추출된 디렉토리 경로
    """
    data = extract_epub(epub_path, workspace)
    output_dir: Path = data["output_dir"]
    opf_dir: Path = data["opf_dir"]
    xhtml_files: list[element.Tag] = data["xhtml_files"]

    # 유효한 XHTML 경로 목록 수집
    xhtml_paths: list[Path] = []
    for item in xhtml_files:
        href = str(item.get('href', ''))
        if not href:
            continue
        resolved = output_dir / opf_dir / href
        if not resolved.exists():
            logging.warning(f"XHTML 파일을 찾을 수 없습니다: {resolved}")
            continue
        xhtml_paths.append(resolved)

    def _process_one(xhtml_path: Path) -> None:
        """단일 XHTML 파일 번역 후 덮어쓰기."""
        translated_xhtml = translate_xhtml(
            xhtml_path, translate_fn, target_lang, max_chars
        )
        with open(xhtml_path, 'w', encoding='utf-8') as f:
            f.write(translated_xhtml)

    if max_workers <= 1:
        # 순차 처리
        for xhtml_path in tqdm(xhtml_paths, desc="번역 중", unit="file"):
            _process_one(xhtml_path)
    else:
        # 병렬 처리
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_one, p): p for p in xhtml_paths
            }
            with tqdm(total=len(futures), desc="번역 중", unit="file") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    path = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"XHTML 번역 실패: {path} — {e}")
                    pbar.update(1)

    return output_dir


class EPUB:
    def __init__(self, epub_path: Path, output_dir: Path, opf: BeautifulSoup, xhtmls: list[element.Tag]):
        self.epub_path = epub_path
        self.output_dir = output_dir

def extract_epub(epub_path: Path, workspace: Path) -> dict:
    """
    EPUB 파일을 workspace에 추출하고, OPF에서 xhtml 파일 목록을 파싱하여 반환합니다.
    
    :param epub_path: EPUB 파일 경로
    :param workspace: 작업 디렉토리 (extracted_epubs 하위에 추출)
    """
    if not epub_path.exists() or not epub_path.is_file():
        raise FileNotFoundError(f"EPUB 파일을 찾을 수 없습니다: {epub_path}")
    elif epub_path.suffix.lower() != '.epub':
        raise ValueError(f"유효한 EPUB 파일이 아닙니다: {epub_path}")
    
    counter = 1
    output_dir = workspace / "extracted_epubs" / epub_path.stem
    if output_dir.exists():
        while True:
            new_output_dir = workspace / "extracted_epubs" / f"{epub_path.stem}({counter})"
            if not new_output_dir.exists():
                output_dir = new_output_dir
                break
            counter += 1
    else:
        output_dir = output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path: Path = output_dir / "log.txt"

    with zipfile.ZipFile(epub_path, 'r') as f:
        root = zipfile.Path(f)

        def get_file_by_suffix(suffix: str) -> list[zipfile.Path]:
            return [p for p in root.rglob(f"*.{suffix}") if p.is_file()]
        
        def get_xhtml_files_from_opf(opf_path: zipfile.Path) -> list[element.Tag]:
            """
            OPF 파일에서 xhtml 파일 목록을 추출하고 spine 순서로 정렬합니다.
            spine에 없는 항목은 manifest 순서로 뒤에 추가됩니다.
            
            :param opf_path: OPF 파일의 zipfile.Path
            :returns: 정렬된 xhtml item Tag 리스트
            """
            with opf_path.open('r', encoding='utf-8') as opf_file:
                opf_soup = BeautifulSoup(opf_file, 'xml')
            
            manifest: element.Tag | None = opf_soup.find('manifest')
            if not manifest:
                raise NotValidOPFError("OPF 파일에 manifest 태그가 없습니다.")
            spine: element.Tag | None = opf_soup.find('spine')
            if not spine:
                raise NotValidOPFError("OPF 파일에 spine 태그가 없습니다.")

            media_type_pattern = re.compile(r'application/(xhtml\+xml|x-dtbook\+xml)', re.IGNORECASE)
            xhtml_files: element.ResultSet[element.Tag] = manifest.find_all('item', attrs={'media-type': media_type_pattern})
            if not xhtml_files:
                raise NotValidOPFError("OPF 파일의 manifest에 xhtml 파일이 없습니다.")

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

        opf_path = get_file_by_suffix("opf")[0]
        if not opf_path: raise FileNotFoundError("OPF 파일을 찾을 수 없습니다.")
        logging.info(f"Found OPF file: {opf_path}")

        with opf_path.open('r', encoding='utf-8') as opf_file:
            opf_soup = BeautifulSoup(opf_file, 'xml')
        
        xhtml_files = get_xhtml_files_from_opf(opf_path)
        if not xhtml_files: 
            raise FileNotFoundError("OPF 파일에서 xhtml 파일 목록을 추출할 수 없습니다.")

        logging.info(f"Found {len(xhtml_files)} XHTML files in OPF.")

        opf_parent = Path(opf_path.at).parent

        for member in f.namelist():
            member_path = output_dir / member
            if member.endswith('/'):
                member_path.mkdir(parents=True, exist_ok=True)
            else:
                member_path.parent.mkdir(parents=True, exist_ok=True)
                with f.open(member) as source, open(member_path, 'wb') as target:
                    target.write(source.read())

    data: dict = {
        "output_dir": output_dir,
        "opf_dir": opf_parent,
        "xhtml_files": xhtml_files
    }

    return data

def repackage_epub(extracted_dir: Path, output_path: Path) -> Path:
    """
    추출된 EPUB 디렉토리를 .epub 파일로 다시 패키징합니다.

    EPUB 스펙에 따라 mimetype 파일은 압축하지 않고 ZIP의 첫 번째 엔트리로 저장합니다.
    작업용 log.txt는 제외합니다.

    :param extracted_dir: 추출된 EPUB 파일들이 있는 디렉토리
    :param output_path: 출력할 .epub 파일 경로
    :returns: 생성된 .epub 파일 경로
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # mimetype은 반드시 첫 번째 엔트리, 비압축으로 저장 (EPUB OCF 스펙)
        mimetype_path = extracted_dir / "mimetype"
        if mimetype_path.exists():
            zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

        # 나머지 파일 추가
        for file_path in sorted(extracted_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name == "mimetype":
                continue
            arcname = file_path.relative_to(extracted_dir).as_posix()
            if arcname == "log.txt":
                continue
            zf.write(file_path, arcname)

    logging.info(f"EPUB 패키징 완료: {output_path}")
    return output_path


def trim_ruby_text(text: str) -> str:
    """
    텍스트 문자열에서 ``<ruby>한자<rt>후리가나</rt></ruby>`` 패턴을
    ``한자 (Ruby: 후리가나)`` 형태로 치환합니다.
    
    :param text: Ruby 태그가 포함될 수 있는 텍스트
    :returns: Ruby 주석이 치환된 텍스트
    """
    ruby_pattern = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>')
    def replace_ruby(match: re.Match) -> str:
        kanji = match.group(1)
        furigana = match.group(2)
        return f"{kanji} (Ruby: {furigana})"
    
    return ruby_pattern.sub(replace_ruby, text)

def text_from_epub(output_dir: Path, ordered_xhtml_files: list[element.Tag], opf_dir: Path = Path('.')) -> str:
    """
    EPUB에서 추출한 xhtml 파일 목록에서 전체 텍스트를 추출합니다.
    태그를 무시하고 body의 텍스트만 합쳐서 반환합니다.
    
    :param output_dir: EPUB 추출 디렉토리
    :param ordered_xhtml_files: 정렬된 xhtml item Tag 리스트
    :param opf_dir: OPF 파일의 zip 내 상위 디렉토리 (href 해석 기준)
    :returns: 추출된 전체 텍스트
    """
    full_text = ""

    for item in ordered_xhtml_files:
        href: str = str(item.get('href'))
        if not href:
            logging.warning("XHTML 파일의 href 속성이 없습니다. 건너뜁니다.")
            continue
        
        xhtml_path = output_dir / opf_dir / href
        if not xhtml_path.exists():
            logging.warning(f"XHTML 파일을 찾을 수 없습니다: {xhtml_path}. 건너뜁니다.")
            continue
        
        with xhtml_path.open('r', encoding='utf-8') as f:
            xhtml_soup = BeautifulSoup(f, 'xml', multi_valued_attributes=_XHTML_MULTI_VALUED_ATTRS)
        
        body = xhtml_soup.find('body')
        if not body:
            logging.warning(f"XHTML 파일에 body 태그가 없습니다: {xhtml_path}. 건너뜁니다.")
            continue
        
        text = body.get_text(separator='\n', strip=True)
        text = trim_ruby_text(text)
        full_text += text + "\n\n"
    
    return full_text.strip()

