import os
import io
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

import settings

# 함수 utils
def get_workspace() -> Path:
    workspace = Path.home() / ".epub_ai_translator"
    workspace.mkdir(parents=True, exist_ok=True)

    return workspace

def get_api_key(key_name: str) -> str:
    key = os.getenv(key_name)
    if not key:
        key = getattr(settings, key_name, None)
        if not key:
            raise ValueError(f"{key_name}가 설정되지 않았습니다.")
    return key

def zip_to_pdf(zip_bytes: bytes) -> bytes:
    zip_data = io.BytesIO(zip_bytes)
    
    with ZipFile(zip_data, 'r') as zip_ref:
        img_files = sorted([
            f for f in zip_ref.namelist() 
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ])
        
        if not img_files:
            raise ValueError("이미지 파일이 ZIP 내에 존재하지 않습니다.")

        def image_generator():
            for file_name in img_files[1:]:
                with zip_ref.open(file_name) as f:
                    with Image.open(f) as img:
                        yield img.convert('RGB')


        with zip_ref.open(img_files[0]) as first_f:
            with Image.open(first_f) as first_img:
                rgb_first = first_img.convert('RGB')
                
                output_buf = io.BytesIO()
                rgb_first.save(
                    output_buf,
                    format='PDF',
                    save_all=True,
                    append_images=image_generator(),
                    resolution=100.0
                )
                
                pdf_data = output_buf.getvalue()
                output_buf.close()
                return pdf_data
