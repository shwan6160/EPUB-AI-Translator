import os

import keyring

from settings import APP_NAME


def _setup_keyring() -> None:
    """환경에 따라 적절한 keyring 백엔드를 선택합니다.

    우선순위:
    1. KEYRING_BACKEND 환경변수로 강제 지정 ("pass" 또는 "system")
    2. GUI 세션 감지 (DISPLAY / WAYLAND_DISPLAY) → 시스템 기본 백엔드
    3. headless → pass 백엔드
    """
    forced = os.environ.get("KEYRING_BACKEND", "").lower()

    if forced == "pass" or (not forced and not _is_gui_session()):
        from keyring_pass import PasswordStoreBackend
        keyring.set_keyring(PasswordStoreBackend())


def _is_gui_session() -> bool:
    """X11 또는 Wayland 세션이 활성화되어 있는지 확인합니다."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


_setup_keyring()

keyname_list = [
    "GEMINI_KEY",
    "OPENROUTER_KEY",
    "COPILOT_KEY"
]

# key utils
def save_keyring(name: str, key: str) -> None:
    if name not in keyname_list:
        raise ValueError(f"지원하지 않는 키 이름입니다. 지원되는 키: {', '.join(keyname_list)}")
    
    keyring.set_password(APP_NAME, name, key)

def get_keyring(name: str) -> str:
    res = keyring.get_password(APP_NAME, name)
    if not res:
        raise ValueError(f"{name}에 해당하는 API 키가 존재하지 않습니다.")
    return res

def load_keyring(name: str) -> None:
    os.environ[name] = get_keyring(name)

def list_keyring() -> dict[str, str]:
    key_list = {}
    
    def _get_key(name: str) -> None:
        try:
            key_list[name] = get_keyring(name)
        except ValueError:
            key_list[name] = "(empty)"

    for keyname in keyname_list:
        _get_key(keyname)
    
    return key_list

def delete_keyring(name: str) -> None:
    if name not in keyname_list:
        raise ValueError(f"지원하지 않는 키 이름입니다. 지원되는 키: {', '.join(keyname_list)}")

    keyring.delete_password(APP_NAME, name)


