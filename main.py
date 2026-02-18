import json
import os
import sys
import subprocess
import signal
from pathlib import Path
from typing import Annotated

import typer

from utils import get_workspace


app = typer.Typer(
    context_settings={
        "help_option_names": ["-h", "--help"]
    }
)
dashboard = typer.Typer(help="웹 대시보드 서버 관리")
app.add_typer(dashboard, name="dashboard", help="FastAPI 대시보드를 백그라운드에서 실행/종료하는 커맨드 alias: dash", hidden=False)
app.add_typer(dashboard, name="dash", hidden=True)

typer_key = typer.Typer(help="API 키 관리")
app.add_typer(typer_key, name="key", help="API 키를 저장/조회하는 커맨드")

PID_FILE = get_workspace() / Path(".dashboard.pid")

@app.command()
def run(
        epub_file: Annotated[str, typer.Argument(help="번역할 EPUB 파일 경로")],
        provider: Annotated[str|None, typer.Option("--provider", "-p", help="모델 제공자 선택 (Google 또는 OpenRouter)")] = None,
        model: Annotated[str|None, typer.Option("--model", "-m", help="사용할 모델 이름 (Ex: gemini-2.5-flash, qwen/qwen3-max-thinking)")] = None,
        key: Annotated[str|None, typer.Option("--key", "-k", help="API 키")] = None,
        yes: Annotated[bool, typer.Option("-y")] = False
    ) -> None:
    # 지연로드: run 커맨드에서만 필요한 import들
    from google import genai
    from provider import GoogleGenai, GoogleGenaiConfig, OpenRouter, OpenRouterConfig
    from utils import select_provider, select_model, yn_check, get_workspace, get_api_key
    from epub import extract_epub, translate_epub, repackage_epub
    from dictionary import load_full_text_from_epub, parse_dictionary_json
    from prompts.dictionary import (
        CHARACTER_DICT_SYSTEM_PROMPT,
        CHARACTER_DICT_USER_PROMPT,
        CHARACTER_DICT_SYSTEM_PROMPT_QWEN,
        CHARACTER_DICT_USER_PROMPT_QWEN
    )
    from prompts.translation import base_prompt_instructions, base_prompt_text

    epub_file_path = Path(epub_file)
    char_dict_path = epub_file_path.with_name(f"{Path(epub_file_path).stem}_character_dictionary.json")

    epub_extracted = extract_epub(Path(epub_file_path), get_workspace())
    full_text = load_full_text_from_epub(epub_extracted)
    
    provider_select = provider
    dict_provider = None
    dict_model = None

    translate_provider = None
    translate_model = None
    
    char_dict = None

    # 캐릭터 사전 있는지 확인하고 있으면 검증 후 로드, 없으면 경로 묻기
    if char_dict_path.exists():
        print(f"기존 캐릭터 사전이 발견되었습니다: {char_dict_path}")
        load_dict = yn_check(yes, "기존 캐릭터 사전을 로드하시겠습니까?")

        if load_dict:
            try:
                with open(char_dict_path, "r", encoding="utf-8") as f:
                    char_dict = json.load(f)
                # dictionary JSON 검증 로직 재활용
                parse_dictionary_json(json.dumps(char_dict, ensure_ascii=False))
                print(f"기존 캐릭터 사전을 로드했습니다: {char_dict_path}")
            except Exception as e:
                print(f"기존 캐릭터 사전 로드 실패: {e}")
                char_dict = None
    
    if char_dict is None:
        print("캐릭터 사전 파일을 찾을 수 없습니다.")
        if not yn_check(yes, "캐릭터 사전을 새로 생성하시겠습니까?"):
            print("프로그램을 종료합니다.")
            os._exit(1)

        dict_provider = select_provider(provider_select)
        dict_model = None

        # dict_model 선택
        if dict_provider == "Google":
            key = get_api_key("GEMINI_KEY") if key is None else key
            if not key:
                print("GEMINI_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
                key = input("GEMINI_KEY: ").strip()
                if not key:
                    raise ValueError("API 키가 설정되지 않았습니다.")
            
            available_models = []
            try:
                for m in GoogleGenai.list_available_models(key):
                    available_models.append(m.replace("models/", ""))
            except Exception as e:
                print(f"모델 목록을 불러오는 중 오류가 발생했습니다: {e}")
                raise

            dict_model = select_model(available_models)
        
        elif dict_provider == "OpenRouter":
            key = get_api_key("OPENROUTER_KEY") if key is None else key
            if not key:
                print("OPENROUTER_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
                key = input("OPENROUTER_KEY: ").strip()
                if not key:
                    raise ValueError("API 키가 설정되지 않았습니다.")

            available_models = [
                "qwen/qwen3-max-thinking",
                "moonshotai/kimi-k2.5",
                "z-ai/GLM-5"
            ]
            dict_model = select_model(available_models)
        
        elif dict_provider == "Copilot":
            print("Copilot 모델 제공자는 아직 구현되지 않았습니다.")
        
        else:
            print("알 수 없는 모델 제공자입니다.")
            os._exit(1)
        
        print("선택을 확인합니다.")
        print(f"EPUB 파일: {epub_file_path}")
        print(f"모델 제공자: {dict_provider}")
        print(f"모델 이름: {dict_model}")

        if not yn_check(yes, "위 선택으로 캐릭터 사전을 생성하시겠습니까?"):
            print("프로그램을 종료합니다.")
            os._exit(1)
        
        # 캐릭터 사전 생성
        if dict_provider == "Google":
            instance = GoogleGenai(
                config = GoogleGenaiConfig(
                    api_key = key,
                    model_name = dict_model,
                    generation_config = genai.types.GenerateContentConfig(
                        system_instruction = CHARACTER_DICT_SYSTEM_PROMPT,
                        temperature = 0.2,
                        top_p = 0.8,
                        top_k = 40,
                        response_mime_type = "application/json"
                    )
                )
            )

            response_text = instance.generate_content(
                user_prompt=CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)
            )
            char_dict = parse_dictionary_json(response_text)
        
        elif dict_provider == "OpenRouter":
            system_prompt = CHARACTER_DICT_SYSTEM_PROMPT
            user_prompt = CHARACTER_DICT_USER_PROMPT.format(novel_text=full_text)

            if dict_model == "qwen/qwen3-max-thinking":
                system_prompt = CHARACTER_DICT_SYSTEM_PROMPT_QWEN
                user_prompt = CHARACTER_DICT_USER_PROMPT_QWEN.format(novel_text=full_text)

            instance = OpenRouter(
                config=OpenRouterConfig(
                    api_key=key,
                    model_name=dict_model,
                    system_prompt=system_prompt,
                    temperature=0.2,
                    top_p=0.8,
                    response_format={"type": "json_object"},
                    app_name="EPUB-AI-Translator",
                )
            )

            response_text = instance.generate_content(
                user_prompt=user_prompt
            )
            char_dict = parse_dictionary_json(response_text)
        
        if yn_check(yes, "캐릭터 사전이 새로 생성되었습니다.\n사전을 파일로 저장하겠습니까?"):
            with open(char_dict_path, "w", encoding="utf-8") as f:
                json.dump(char_dict, f, ensure_ascii=False, indent=2)
    
    # 번역 진행
    if dict_provider is not None and dict_model is not None:
        if yn_check(yes, "캐릭터 사전 모델 설정을 그대로 사용하겠습니까?"):
            translate_provider = dict_provider
            translate_model = dict_model
        else:
            translate_provider = select_provider(provider_select)
            translate_model = None

            if translate_provider == "Google":
                key = get_api_key("GEMINI_KEY") if key is None else key
                if not key:
                    print("GEMINI_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
                    key = input("GEMINI_KEY: ").strip()
                    if not key:
                        raise ValueError("API 키가 설정되지 않았습니다.")
                available_models = []
                try:
                    for m in GoogleGenai.list_available_models(key):
                        available_models.append(m.replace("models/", ""))
                except Exception as e:
                    print(f"모델 목록을 불러오는 중 오류가 발생했습니다: {e}")
                    raise
                translate_model = select_model(available_models)
            elif translate_provider == "OpenRouter":
                key = get_api_key("OPENROUTER_KEY") if key is None else key
                if not key:
                    print("OPENROUTER_KEY가 설정되지 않았습니다. API 키를 입력해 주십시오.")
                    key = input("OPENROUTER_KEY: ").strip()
                    if not key:
                        raise ValueError("API 키가 설정되지 않았습니다.")
                available_models = [
                    "qwen/qwen3-max-thinking",
                    "moonshotai/kimi-k2.5",
                    "z-ai/GLM-5"
                ]
                translate_model = select_model(available_models)
            elif translate_provider == "Copilot":
                print("Copilot 모델 제공자는 아직 구현되지 않았습니다.")
            else:
                print("알 수 없는 모델 제공자입니다.")
                os._exit(1)
        
        if translate_provider == "Google":
            # 캐릭터 사전 내용 시스템 프롬프트에 포함
            char_dict_text = json.dumps(char_dict, ensure_ascii=False, indent=2)
            translation_system_prompt = base_prompt_instructions.format(char_dict_text=char_dict_text)
            
            translate_instance = GoogleGenai(
                config = GoogleGenaiConfig(
                    api_key = key,
                    model_name = translate_model,
                    generation_config = genai.types.GenerateContentConfig(
                        system_instruction = translation_system_prompt,
                        temperature = 0.7,
                        top_p = 0.9,
                        top_k = 40,
                    )
                )
            )

            # translate_fn: 파일 내 chunk간 prev_context는 translate_and_inject에서 자동 관리
            def translate_fn(chunk_text: str, prev_context: str) -> str:
                user_prompt = base_prompt_text.format(
                    prev_context=prev_context,
                    current_text=chunk_text
                )
                result = translate_instance.generate_content(user_prompt=user_prompt)
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
            
        elif translate_provider == "OpenRouter":
            print("OpenRouter 번역이 아직 구현되지 않았습니다.")

@dashboard.command("start")
def dashboard_start(
    port: Annotated[int, typer.Option("--port", "-p", help="대시보드 포트")] = 8000
):
    """FastAPI 대시보드를 백그라운드에서 실행합니다."""
    from keyauth import load_keyring
    
    typer.echo(f"포트 {port}에서 백그라운드 서버 시작을 준비합니다...")
    typer.echo("API 키를 환경 변수로 로드합니다...")
    try:
        load_keyring("GEMINI_KEY")
        load_keyring("OPENROUTER_KEY")
        typer.secho("API 키가 성공적으로 로드되었습니다.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"API 키 로드 중 오류 발생: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


    if PID_FILE.exists():
        typer.secho("⚠️ 대시보드가 이미 실행 중인 것 같습니다. (먼저 stop 커맨드를 사용하세요)", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    cmd = [sys.executable, "-m", "uvicorn", "web.app:app", "--port", str(port)]

    try:
        if os.name == 'nt':
            raise Exception("Fuck windows")
        else:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            PID_FILE.write_text(str(process.pid))
        typer.secho(f"대시보드가 백그라운드에서 실행되었습니다! (PID: {process.pid})", fg=typer.colors.GREEN)
        typer.echo(f"접속 주소: http://127.0.0.1:{port}")
        
    except Exception as e:
        typer.secho(f"서버 실행 실패: {e}", fg=typer.colors.RED)

@dashboard.command("stop")
def dashboard_stop():
    """백그라운드에서 실행 중인 대시보드를 종료합니다."""

    if not PID_FILE.exists():
        typer.secho("실행 중인 대시보드 백그라운드 프로세스를 찾을 수 없습니다.", fg=typer.colors.BLUE)
        return

    pid = int(PID_FILE.read_text().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        typer.secho(f"대시보드 서버(PID: {pid})를 성공적으로 종료했습니다.", fg=typer.colors.GREEN)
    except ProcessLookupError:
        typer.secho("프로세스가 이미 종료되어 있습니다.", fg=typer.colors.YELLOW)
    except Exception as e:
        typer.secho(f"프로세스 종료 중 오류 발생: {e}", fg=typer.colors.RED)
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()

@typer_key.command("set")
def set_key(
    name: Annotated[str, typer.Argument(help="키 이름 (예: GEMINI_KEY, OPENROUTER_KEY)")],
    key: Annotated[str|None, typer.Argument(help="저장할 API 키 값")] = None
):
    """API 키를 안전하게 저장합니다."""
    from keyauth import save_keyring

    if key is None:
        key = input("저장할 API 키 값을 입력하세요: ").strip()
        if not key:
            typer.secho("API 키 값이 비어 있습니다. 저장을 취소합니다.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

    save_keyring(name, key)
    typer.secho(f"{name}이(가) 안전하게 저장되었습니다.", fg=typer.colors.GREEN)

@typer_key.command("list")
@typer_key.command("ls", hidden=True)
def list_keys():
    """저장된 API 키 이름을 나열합니다."""
    import keyring
    typer.secho("아직 구현되지 않음", fg=typer.colors.YELLOW)

@typer_key.command("rm")
@typer_key.command("remove", hidden=True)
def remove_key(
    name: Annotated[str, typer.Argument(help="삭제할 키 이름")]
):
    """저장된 API 키를 삭제합니다."""
    import keyring

    keyring.delete_password("erst", name)
    typer.secho(f"{name}이(가) 삭제되었습니다.", fg=typer.colors.GREEN)

if __name__ == "__main__":
    app(prog_name="erst")
