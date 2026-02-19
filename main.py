import sys
import subprocess
import signal
import os
from pathlib import Path
from typing import Annotated

import typer

from utils.utils import get_workspace
from utils.cli import RunWorker


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
    worker = RunWorker(
        epub_file_value=epub_file,
        provider_value=provider,
        model_value=model,
        key_value=key,
        yes_value=yes,
    )
    worker.execute()

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
        typer.secho("대시보드가 이미 실행 중인 것 같습니다. (먼저 stop 커맨드를 사용하세요)", fg=typer.colors.YELLOW)
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
    from keyauth import list_keyring
    key_dict = list_keyring()
    for k, v in key_dict.items():
        if v == "(empty)":
            typer.secho(f"{k}: (empty)", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"{k}: {v[:4]}{'*'*(len(v)-4)}", fg=typer.colors.BLUE)

@typer_key.command("rm")
@typer_key.command("remove", hidden=True)
def remove_key(
    name: Annotated[str, typer.Argument(help="삭제할 키 이름")]
):
    """저장된 API 키를 삭제합니다."""
    from keyauth import delete_keyring
    try:
        delete_keyring(name)
        typer.secho(f"{name}이(가) 삭제되었습니다.", fg=typer.colors.GREEN)
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED)



if __name__ == "__main__":
    app(prog_name="erst")
