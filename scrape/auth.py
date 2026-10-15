from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from shutil import copy2
from typing import TypedDict

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
CHROME_REFRESH_TIMEOUT_SECONDS = 15.0
CHROME_REFRESH_POLL_SECONDS = 1.0


class CookieEntry(TypedDict):
    name: str
    value: str
    domain: str
    path: str


def refresh_cookies_via_chrome(
    url: str = LOGIN_URL,
    wait_seconds: float = 5.0,
    *,
    cookies_db: Path = DEFAULT_CHROME_COOKIES,
    timeout_seconds: float = CHROME_REFRESH_TIMEOUT_SECONDS,
    poll_seconds: float = CHROME_REFRESH_POLL_SECONDS,
) -> bool:
    """Chrome でページを開き Cookie を更新させる。"""
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome is None:
        logger.warning("Chrome バイナリが見つかりません。Cookie の自動更新をスキップします。")
        return False
    subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Chrome で %s を開きました。Cookie 更新を待機します。", url)

    deadline = time.monotonic() + max(wait_seconds, timeout_seconds)
    next_attempt_at = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while True:
        now = time.monotonic()
        if now >= next_attempt_at:
            try:
                load_toyokeizai_cookies(cookies_db)
            except (FileNotFoundError, OSError, sqlite3.Error) as exc:
                last_error = exc
            else:
                return True
            next_attempt_at = now + poll_seconds

        if now >= deadline:
            break
        time.sleep(min(poll_seconds, max(deadline - now, 0.1)))

    if last_error is not None:
        logger.warning("Chrome 起動後も Cookie DB を利用できませんでした: %s", last_error)
    return False


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
    entries = load_toyokeizai_cookie_entries(cookies_db)
    jar = httpx.Cookies()
    for entry in entries:
        jar.set(
            entry["name"],
            entry["value"],
            domain=entry["domain"],
            path=entry["path"],
        )
    return jar


def load_toyokeizai_cookie_entries(
    cookies_db: Path = DEFAULT_CHROME_COOKIES,
) -> list[CookieEntry]:
    """Chromeプロファイルからtoyokeizai向けCookieをJSON向け形式で読み込む。"""
    rows = _load_toyokeizai_cookie_rows(cookies_db)

    entries: list[CookieEntry] = []
    for host_key, name, encrypted_value in rows:
        value = decrypt_chrome_cookie(encrypted_value)
        if not value:
            continue
        entries.append(
            {
                "name": name,
                "value": value,
                "domain": host_key.lstrip("."),
                "path": "/",
            }
        )
    return entries


def write_cookie_json(cookie_file: Path, cookies: list[CookieEntry]) -> None:
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def refresh_cookie_source(
    cookie_file: Path = DEFAULT_CHROME_COOKIES,
    *,
    chrome_cookies_db: Path = DEFAULT_CHROME_COOKIES,
    url: str = LOGIN_URL,
    wait_seconds: float = 5.0,
    timeout_seconds: float = CHROME_REFRESH_TIMEOUT_SECONDS,
    poll_seconds: float = CHROME_REFRESH_POLL_SECONDS,
) -> bool:
    """Cookieソースを更新する。JSON指定時はChrome Cookie DBから再生成する。"""
    if cookie_file.suffix != ".json":
        return refresh_cookies_via_chrome(
            url=url,
            wait_seconds=wait_seconds,
            cookies_db=cookie_file,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

    refreshed = refresh_cookies_via_chrome(
        url=url,
        wait_seconds=wait_seconds,
        cookies_db=chrome_cookies_db,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )
    if not refreshed:
        return False

    try:
        cookies = load_toyokeizai_cookie_entries(chrome_cookies_db)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("Chrome Cookie DB から JSON Cookie を再生成できませんでした: %s", exc)
        return False

    write_cookie_json(cookie_file, cookies)
    logger.info("Chrome Cookie DB から %s を更新しました。", cookie_file)
    return True


def is_http_auth_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response is not None and exc.response.status_code in {401, 403}
    )


def _load_toyokeizai_cookie_rows(
    cookies_db: Path,
) -> list[tuple[str, str, bytes]]:
    if not cookies_db.exists():
        raise FileNotFoundError(
            f"Chrome Cookie DBが見つかりません: {cookies_db}\n"
            "Google Chromeで四季報オンラインにログインしてください。"
        )

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
    return rows
