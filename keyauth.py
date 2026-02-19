import os

import keyring
from keyring_pass import PasswordStoreBackend

from settings import APP_NAME

keyring.set_keyring(PasswordStoreBackend())

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


