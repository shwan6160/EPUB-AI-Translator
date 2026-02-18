import os

import keyring
from keyring_pass import PasswordStoreBackend

from settings import APP_NAME

keyring.set_keyring(PasswordStoreBackend())

# key utils
def save_keyring(name: str, key: str) -> None:
    keyring.set_password(APP_NAME, name, key)

def get_keyring(name: str) -> str:
    res = keyring.get_password(APP_NAME, name)
    if not res:
        raise ValueError(f"{name}에 해당하는 API 키가 존재하지 않습니다.")
    return res

def load_keyring(name: str) -> None:
    os.environ[name] = get_keyring(name)
