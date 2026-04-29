from __future__ import annotations

import logging
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from shutil import copy2

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

DEFAULT_CHROME_COOKIES = Path.home() / ".config/google-chrome/Default/Cookies"
COOKIE_DOMAINS = (".toyokeizai.net", "shikiho.toyokeizai.net", "pa.toyokeizai.net")
LOGIN_URL = "https://shikiho.toyokeizai.net/stocks/"
CHROME_V10_PREFIX = b"v10"
CHROME_SALT = b"saltysalt"
CHROME_PASSWORD = b"peanuts"
CHROME_IV = b" " * 16
HOST_KEY_HASH_BYTES = 32


def refresh_cookies_via_chrome(url: str = LOGIN_URL, wait_seconds: float = 5.0) -> None:
    """Chrome でページを開き Cookie を更新させる。"""
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome is None:
        logger.warning("Chrome バイナリが見つかりません。Cookie の自動更新をスキップします。")
        return
    subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Chrome で %s を開きました。%s 秒待機します。", url, wait_seconds)
    time.sleep(wait_seconds)


def decrypt_chrome_cookie(encrypted_value: bytes) -> str:
    """ChromeのCookie DBに保存されたv10形式Cookieを復号する。"""
    if not encrypted_value:
        return ""
    if not encrypted_value.startswith(CHROME_V10_PREFIX):
        return encrypted_value.decode("utf-8", "ignore")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=CHROME_SALT,
        iterations=1,
    )
    key = kdf.derive(CHROME_PASSWORD)
    cipher = Cipher(algorithms.AES(key), modes.CBC(CHROME_IV))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted_value[len(CHROME_V10_PREFIX):]) + decryptor.finalize()

    pad_length = decrypted[-1]
    plaintext = decrypted[:-pad_length]
    # 新しいChromeはhost_keyのSHA-256を先頭に付けて保存する。
    if len(plaintext) > HOST_KEY_HASH_BYTES:
        plaintext = plaintext[HOST_KEY_HASH_BYTES:]
    return plaintext.decode("utf-8", "ignore")


def load_toyokeizai_cookies(
    cookies_db: Path = DEFAULT_CHROME_COOKIES,
) -> httpx.Cookies:
    """Chromeプロファイルからtoyokeizai向けCookieを読み込む。"""
    if not cookies_db.exists():
        raise FileNotFoundError(
            f"Chrome Cookie DBが見つかりません: {cookies_db}\n"
            "Google Chromeで四季報オンラインにログインしてください。"
        )

    jar = httpx.Cookies()
    with tempfile.NamedTemporaryFile() as tmp:
        copy2(cookies_db, tmp.name)
        con = sqlite3.connect(tmp.name)
        try:
            cur = con.cursor()
            placeholders = ",".join("?" for _ in COOKIE_DOMAINS)
            cur.execute(
                f"""
                SELECT host_key, name, encrypted_value
                FROM cookies
                WHERE host_key IN ({placeholders})
                ORDER BY host_key, name
                """,
                COOKIE_DOMAINS,
            )
            rows = cur.fetchall()
        finally:
            con.close()

    if not rows:
        raise FileNotFoundError(
            "toyokeizai向けCookieがChromeに見つかりません。\n"
            "Google Chromeで四季報オンラインにログインしてください。"
        )

    for host_key, name, encrypted_value in rows:
        value = decrypt_chrome_cookie(encrypted_value)
        if not value:
            continue
        jar.set(name, value, domain=host_key.lstrip("."), path="/")
    return jar
