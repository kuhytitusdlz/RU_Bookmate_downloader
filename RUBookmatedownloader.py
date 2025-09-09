import asyncio
import zipfile
import random
import os
import time
import re
import sys
import warnings
import json
import argparse
import shutil
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import httpx
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PIL import Image

# ============
# Graceful exit
# ============
class GracefulExit(SystemExit):
    """Управляемый выход без трейсбеков (например, по Ctrl+C)."""
    pass

def run_async_safely(coro):
    """Запускает корутину и гасит Ctrl+C без трейcбека."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        # Преобразуем в управляемый выход — ниже поймаем и завершимся красиво
        raise GracefulExit(130)


# =========================
# Конфигурация по умолчанию
# =========================

CONFIG = {
    "max_retries": 5,            # всего попыток (включая первую)
    "backoff_initial": 5.0,      # стартовая задержка между ретраями (сек)
    "backoff_cap": 120.0,        # максимум задержки между ретраями (сек)
    "timeout_base_download": 15.0,  # базовый таймаут для download_file (сек, умножается экспоненциально)
    "timeout_base_request": 10.0,   # базовый таймаут для send_request (сек, умножается экспоненциально)
    "throttle": 0.0,             # «вежливая» задержка между скачиванием треков (сек). 0 = выкл
    "force_meta": False,         # перезаписывать jpeg/json/info.txt, даже если существуют
    "proxy_url": None,           # строка прокси: socks5h://127.0.0.1:9050 или http://127.0.0.1:8080
}

UA = {
    1: "Samsung/Galaxy_A51 Android/12 Bookmate/3.7.3",
    2: "Huawei/P40_Lite Android/11 Bookmate/3.7.3",
    3: "OnePlus/Nord_N10 Android/10 Bookmate/3.7.3",
    4: "Google/Pixel_4a Android/9 Bookmate/3.7.3",
    5: "Oppo/Reno_4 Android/8 Bookmate/3.7.3",
    6: "Xiaomi/Redmi_Note_9 Android/10 Bookmate/3.7.3",
    7: "Motorola/Moto_G_Power Android/10 Bookmate/3.7.3",
    8: "Sony/Xperia_10 Android/10 Bookmate/3.7.3",
    9: "LG/Velvet Android/10 Bookmate/3.7.3",
    10: "Realme/6_Pro Android/10 Bookmate/3.7.3",
}
HEADERS = {
    'app-user-agent': random.choice(list(UA.values())),
    'mcc': '',
    'mnc': '',
    'imei': '',
    'subscription-country': '',
    'app-locale': '',
    'bookmate-version': '',
    'bookmate-websocket-version': '',
    'device-idfa': '',
    'onyx-preinstall': 'false',
    'auth-token': '',
    'accept-encoding': '',
    'user-agent': ''
}
BASE_URL = "https://api.bookmate.yandex.net/api/v5"
URLS = {
    "book": {
        "infoUrl": f"{BASE_URL}/books/{{uuid}}",
        "contentUrl": f"{BASE_URL}/books/{{uuid}}/content/v4"
    },
    "audiobook": {
        "infoUrl": f"{BASE_URL}/audiobooks/{{uuid}}",
        "contentUrl": f"{BASE_URL}/audiobooks/{{uuid}}/playlists.json"
    },
    "comicbook": {
        "infoUrl": f"{BASE_URL}/comicbooks/{{uuid}}",
        "contentUrl": f"{BASE_URL}/comicbooks/{{uuid}}/metadata.json"
    },
    "serial": {
        "infoUrl": f"{BASE_URL}/books/{{uuid}}",
        "contentUrl": f"{BASE_URL}/books/{{uuid}}/episodes"
    },
    "series": {
        "infoUrl": f"{BASE_URL}/series/{{uuid}}",
        "contentUrl": f"{BASE_URL}/series/{{uuid}}/parts"
    }
}



# =========================
# Archive support (yt-dlp-style)
# =========================
ARCHIVE_FILE = "archive.txt"
_archive_cache: set[str] | None = None

def init_archive(path: str | None = None):
    """Initialize archive cache and optionally set custom archive file path."""
    global ARCHIVE_FILE, _archive_cache
    if path:
        ARCHIVE_FILE = path
    if _archive_cache is None:
        try:
            with open(ARCHIVE_FILE, 'r', encoding='utf-8') as f:
                _archive_cache = set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            _archive_cache = set()
    return _archive_cache

def is_archived(uid: str) -> bool:
    """Return True if the given resource id is present in archive."""
    return uid.strip() in init_archive()

def add_to_archive(uid: str):
    """Append the given id to the archive file (idempotent)."""
    uid = uid.strip()
    if not uid:
        return
    arc = init_archive()
    if uid not in arc:
        os.makedirs(os.path.dirname(ARCHIVE_FILE) or ".", exist_ok=True)
        with open(ARCHIVE_FILE, 'a', encoding='utf-8') as f:
            f.write(uid + "\n")
        arc.add(uid)
        print(f"[archive] Added {uid} to {ARCHIVE_FILE}")

RETRY_STATUSES = {429, 500, 502, 503, 504}


def get_auth_token(force: bool = False):
    token_file = "token.txt"
    if not force and os.path.isfile(token_file):
        with open(token_file, encoding='utf-8') as file:
            token = file.read().strip()
            if token:
                return token
    if not force and HEADERS.get('auth-token'):
        return HEADERS['auth-token']

    auth_token = run_auth_webview()
    if not auth_token:
        raise RuntimeError("Не удалось получить OAuth токен Яндекса: окно авторизации закрыто или произошла ошибка.")
    with open(token_file, "w", encoding='utf-8') as file:
        file.write(auth_token)
    return auth_token

def run_auth_webview():
    import webview
    import urllib.parse

    def on_loaded(window):
        if "yx4483e97bab6e486a9822973109a14d05.oauth.yandex.ru" in urllib.parse.urlparse(window.get_current_url()).netloc:
            url = urllib.parse.urlparse(window.get_current_url())
            window.auth_token = urllib.parse.parse_qs(url.fragment)['access_token'][0]
            window.destroy()

    window = webview.create_window(
        'Вход в аккаунт',
        'https://oauth.yandex.ru/authorize?response_type=token&client_id=4483e97bab6e486a9822973109a14d05'
    )
    window.events.loaded += on_loaded
    window.auth_token = None
    webview.start()
    return window.auth_token


def replace_forbidden_chars(filename):
    forbidden_chars = '\\/:*?"<>|'
    chars = re.escape(forbidden_chars)
    return re.sub(f'[{chars}]', '', filename)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    # число секунд
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    # HTTP-дата
    try:
        from email.utils import parsedate_to_datetime
        import datetime as dt
        dt_utc = parsedate_to_datetime(value)
        if dt_utc is None:
            return None
        now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
        return max(0.0, (dt_utc - now).total_seconds())
    except Exception:
        return None


def _build_transport(http2: bool = True, verify: bool = False):
    """
    Для httpx>=0.27: прокси задаём на уровне транспорта.
    Поддерживает SOCKS5h при установленном extras 'socks'.
    """
    params = dict(http2=http2, verify=verify)
    if CONFIG["proxy_url"]:
        params["proxy"] = CONFIG["proxy_url"]
    return httpx.AsyncHTTPTransport(**params)


async def download_file(
    url: str,
    file_path: str,
    max_retries: int | None = None,
    base_timeout: float | None = None,
    backoff_initial: float | None = None,
    backoff_cap: float | None = None,
):
    """
    Потоковое скачивание с ретраями, экспоненциальными таймаутами и .part-файлом.
    """
    if max_retries is None:
        max_retries = CONFIG["max_retries"]
    if base_timeout is None:
        base_timeout = CONFIG["timeout_base_download"]
    if backoff_initial is None:
        backoff_initial = CONFIG["backoff_initial"]
    if backoff_cap is None:
        backoff_cap = CONFIG["backoff_cap"]

    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    for attempt in range(max_retries):
        factor = 2 ** attempt
        timeout = httpx.Timeout(
            connect=base_timeout * factor,
            read=base_timeout * factor,
            write=base_timeout * factor,
            pool=base_timeout * factor,
        )
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                transport=_build_transport(http2=True, verify=False),
            ) as client:
                tmp_path = f"{file_path}.part"
                async with client.stream("GET", url, headers=HEADERS) as resp:
                    if resp.status_code != 200:
                        await _print_error_body(resp)
                        raise httpx.HTTPStatusError(
                            f"Bad status {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            if chunk:
                                f.write(chunk)
                os.replace(tmp_path, file_path)
                print(f"File downloaded successfully to {file_path}")
                return

        except asyncio.CancelledError:
            # Отмена ожидания/операции — тихо завершаемся
            print("\nОтмена по запросу пользователя. Выходим…")
            raise GracefulExit(130)

        except (httpx.ReadError,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
                httpx.ConnectError,
                httpx.HTTPStatusError) as e:
            # подчистим .part
            tmp_path = f"{file_path}.part"
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

            # вычислим задержку перед повтором
            retry_after = None
            status = None
            if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                status = e.response.status_code
                if status in RETRY_STATUSES:
                    retry_after = _parse_retry_after(e.response.headers.get("Retry-After"))

            if attempt < max_retries - 1 and (status is None or status in RETRY_STATUSES):
                base_wait = backoff_initial * factor
                wait_s = max(base_wait, retry_after or 0.0)
                wait_s = min(wait_s, backoff_cap) + random.uniform(0, 0.8)
                human = f"HTTP {status}" if status else f"{type(e).__name__}"
                print(
                    f"Download attempt {attempt+1}/{max_retries} failed ({human}). "
                    f"Retrying in {wait_s:.1f}s..."
                )
                try:
                    await asyncio.sleep(wait_s)
                except asyncio.CancelledError:
                    print("\nОтмена по запросу пользователя. Выходим…")
                    raise GracefulExit(130)
            else:
                print("Failed to download the file after several attempts.")
                sys.exit(1)


async def download_file_once(url: str, file_path: str, base_timeout: float | None = None):
    """
    ОДНА попытка скачивания без внутреннего бэкоффа/ретраев.
    Если не 200 — печатает тело ответа и поднимает HTTPStatusError.
    Нужна для логики fallback качества.
    """
    if base_timeout is None:
        base_timeout = CONFIG["timeout_base_download"]

    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    timeout = httpx.Timeout(
        connect=base_timeout,
        read=base_timeout,
        write=base_timeout,
        pool=base_timeout,
    )

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        transport=_build_transport(http2=True, verify=False),
    ) as client:
        tmp_path = f"{file_path}.part"
        async with client.stream("GET", url, headers=HEADERS) as resp:
            if resp.status_code != 200:
                # напечатаем тело и бросим исключение — чтобы снаружи понять статус и принять решение
                await _print_error_body(resp)
                raise httpx.HTTPStatusError(
                    f"Bad status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            with open(tmp_path, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp_path, file_path)
        print(f"File downloaded successfully to {file_path}")


async def send_request(
    url: str,
    max_retries: int | None = None,
    base_timeout: float | None = None,
    backoff_initial: float | None = None,
    backoff_cap: float | None = None,
):
    """
    GET с ретраями. Возвращает успешный Response (200) или падает на неретраибл кодах.
    """
    if max_retries is None:
        max_retries = CONFIG["max_retries"]
    if base_timeout is None:
        base_timeout = CONFIG["timeout_base_request"]
    if backoff_initial is None:
        backoff_initial = CONFIG["backoff_initial"]
    if backoff_cap is None:
        backoff_cap = CONFIG["backoff_cap"]

    for attempt in range(max_retries):
        factor = 2 ** attempt
        timeout = httpx.Timeout(
            connect=base_timeout * factor,
            read=base_timeout * factor,
            write=base_timeout * factor,
            pool=base_timeout * factor,
        )
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                transport=_build_transport(http2=False, verify=False),
            ) as client:
                resp = await client.get(url, headers=HEADERS)
                if resp.status_code == 200:
                    return resp
                # ретраи только на RETRY_STATUSES
                if resp.status_code in RETRY_STATUSES:
                    await _print_error_body(resp)
                    raise httpx.HTTPStatusError(
                        f"Bad status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                await _print_error_body(resp)
                resp.raise_for_status()

        except asyncio.CancelledError:
            print("\nОтмена по запросу пользователя. Выходим…")
            raise GracefulExit(130)

        except (httpx.ReadError,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
                httpx.ConnectError,
                httpx.HTTPStatusError) as e:
            status = None
            retry_after = None
            if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                status = e.response.status_code
                if status not in RETRY_STATUSES:
                    # неретраибл код — падаем сразу
                    raise
                retry_after = _parse_retry_after(e.response.headers.get("Retry-After"))

            if attempt < max_retries - 1:
                base_wait = backoff_initial * factor
                wait_s = max(base_wait, retry_after or 0.0)
                wait_s = min(wait_s, backoff_cap) + random.uniform(0, 0.8)
                human = f"Request attempt {attempt+1}/{max_retries} failed (HTTP {status})."
                print(f"{human} Retrying in {wait_s:.1f}s...")
                try:
                    await asyncio.sleep(wait_s)
                except asyncio.CancelledError:
                    print("\nОтмена по запросу пользователя. Выходим…")
                    raise GracefulExit(130)
            else:
                print("Failed to download the file after several attempts. Check the ID or try again later.")
                sys.exit(1)


def create_pdf_from_images(images_folder, output_pdf):
    c = canvas.Canvas(output_pdf, pagesize=letter)
    width, height = letter

    images = filter(lambda file: file.endswith(".jpeg"), os.listdir(images_folder))

    for image in images:
        img_path = os.path.join(images_folder, image)
        with Image.open(img_path):
            c.drawImage(img_path, 0, 0, width, height)
            c.showPage()
        os.remove(img_path)
    c.save()
    print(f"File downloaded successfully to {output_pdf}")


def epub_to_fb2(epub_path, fb2_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = epub.read_epub(epub_path)

    fb2_content = '<?xml version="1.0" encoding="UTF-8"?>\n<fb2 xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">\n<body>'
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text()
            fb2_content += f'<p>{text_content}</p>'

    fb2_content += '</body>\n</fb2>'

    with open(fb2_path, 'w', encoding='utf-8') as fb2_file:
        fb2.write(fb2_content)

    print(f"fb2 file save to {fb2_path}")


def write_book_info(text, path, overwrite: bool = False):
    """
    Пишет аннотацию в {path}.txt, создает каталог при необходимости.
    При overwrite=False пропускает, если файл уже есть.
    """
    info_path = f"{path}.txt"
    os.makedirs(os.path.dirname(info_path) or ".", exist_ok=True)
    if not overwrite and os.path.exists(info_path):
        print(f"Annotation already exists, skip: {info_path}")
        return info_path
    with open(info_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"Annotation saved successfully to {info_path}")
    return info_path


def get_resource_info(resource_type, uuid, series=''):
    """
    Скачивает метаинформацию и обложку; idempotent — пропускает, если уже скачано,
    кроме случая force_meta.
    """
    info_url = URLS[resource_type]['infoUrl'].format(uuid=uuid)
    info = run_async_safely(send_request(info_url)).json()
    if not info:
        return None

    meta = info.get(resource_type) or {}

    # ---- Обложка (если есть) ----
    cover = meta.get("cover") or {}
    picture_url = cover.get("large") or meta.get("cover_url")

    # ---- Название ----
    name = meta.get("title") or "untitled"
    name = replace_forbidden_chars(name)
    namelist = name.split(". ", 2)[:2]
    name = "_".join(namelist)

    download_dir = f"mybooks/{'series' if series else resource_type}/{series}{name}/"
    path = f'{download_dir}{name}'
    os.makedirs(download_dir, exist_ok=True)

    # --- JPEG (обложка) ---
    if picture_url:
        jpeg_path = f'{path}.jpeg'
        if os.path.isfile(jpeg_path) and not CONFIG["force_meta"]:
            print(f"Cover already exists, skip: {jpeg_path}")
        else:
            run_async_safely(download_file(picture_url, jpeg_path))

    # --- JSON с meta ---
    json_path = f"{path}.json"
    if os.path.isfile(json_path) and not CONFIG["force_meta"]:
        print(f"JSON already exists, skip: {json_path}")
    else:
        with open(json_path, 'w', encoding='utf-8') as file:
            file.write(json.dumps(info, ensure_ascii=False))
        print(f"File downloaded successfully to {json_path}")

    # --- Аннотация info.txt (без KeyError) ---
    parts = []

    annotation = meta.get('annotation') or ''
    if annotation:
        parts.append(annotation)
        parts.append("")  # пустая строка

    # возраст
    age_restriction = meta.get('age_restriction')
    try:
        if age_restriction is not None and int(age_restriction) > 0:
            parts.append(f"Возрастные ограничения: {int(age_restriction)}+")
    except Exception:
        pass

    owner = meta.get('owner_catalog_title')
    if owner:
        parts.append(f"Правообладатель: {owner}")

    # издательства
    publishers = meta.get('publishers') or []
    if isinstance(publishers, list) and publishers:
        pub_names = [p.get('name') for p in publishers if isinstance(p, dict) and p.get('name')]
        if pub_names:
            parts.append("Издательство: " + ", ".join(pub_names))

    # год
    pubdate = meta.get('publication_date')
    if pubdate:
        try:
            import datetime as dt
            year = dt.datetime.fromtimestamp(int(pubdate)).strftime('%Y')
            parts.append(f"Год выхода издания: {year}")
        except Exception:
            s = str(pubdate)
            if len(s) >= 4 and s[:4].isdigit():
                parts.append(f"Год выхода издания: {s[:4]}")

    # длительность (есть у аудиокниг, у книг — обычно нет)
    duration = meta.get('duration')
    if duration:
        try:
            epoch_time = int(duration)
            seconds = epoch_time % 60
            minutes = (epoch_time // 60) % 60
            hours = epoch_time // 3600
            dur_bits = []
            if hours > 0:
                dur_bits.append(f"{hours} ч.")
            dur_bits.append(f"{minutes} мин.")
            dur_bits.append(f"{seconds} сек.")
            parts.append("Длительность: " + " ".join(dur_bits))
        except Exception:
            pass

    # переводчики
    translators = meta.get('translators') or []
    if isinstance(translators, list) and translators:
        tr_names = [t.get('name') for t in translators if isinstance(t, dict) and t.get('name')]
        if tr_names:
            parts.append("Перевод: " + ", ".join(tr_names))

    # дикторы (для аудио)
    narrators = meta.get('narrators') or []
    if isinstance(narrators, list) and narrators:
        nar_names = [n.get('name') for n in narrators if isinstance(n, dict) and n.get('name')]
        if nar_names:
            parts.append("Озвучили: " + ", ".join(nar_names))

    # темы/теги
    topics = meta.get('topics') or []
    if isinstance(topics, list) and topics:
        topic_titles = []
        for t in topics:
            if isinstance(t, dict):
                title = t.get('title')
                if title and title != "Аудио":
                    topic_titles.append(title)
        if topic_titles:
            parts.append("")
            parts.append("Теги: " + ", ".join(topic_titles))

    info_txt = "\n".join(parts)
    write_book_info(info_txt, os.path.join(download_dir, "info"), overwrite=CONFIG["force_meta"])

    return path


def get_resource_json(resource_type, uuid):
    url = URLS[resource_type]['contentUrl'].format(uuid=uuid)
    return run_async_safely(send_request(url)).json()


# ------- Вспомогательные функции для аудио (ДИНАМИКА из playlists.json)

def _available_variants_track(track: dict) -> dict:
    """dict {variant_key: url} для offline-вариантов КОНКРЕТНОГО трека."""
    out = {}
    off = (track or {}).get('offline') or {}
    for k, v in off.items():
        if isinstance(v, dict) and v.get('url'):
            out[k] = v['url']
    return out

def _playlist_variants_order(resp_json: dict, pref: str) -> list[str]:
    """
    Возвращает СПИСОК вариантов в порядке из sorted(set(...)) по всем трекам.
    Если pref='max' -> как есть; если 'min' -> реверс.
    """
    variants = set()
    for t in resp_json.get('tracks', []):
        off = t.get('offline') or {}
        variants |= set(k for k in off.keys() if isinstance(off.get(k), dict) and off.get(k, {}).get('url'))
    ordered = sorted(variants)
    print("Available offline variants:", ", ".join(ordered) or "(none)")
    if pref == 'min':
        ordered = list(reversed(ordered))
    # pref может быть только 'max' или 'min' (по CLI)
    return ordered

def _preferred_key(pref_order: list[str], fallback_to_first_if_empty=True) -> str | None:
    """Берёт первый элемент из списка как предпочитаемый ключ."""
    if pref_order:
        return pref_order[0]
    return pref_order[0] if (fallback_to_first_if_empty and pref_order) else None


def download_book(uuid, series='', serial_path=None):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = serial_path if serial_path else get_resource_info('book', uuid, series)
    run_async_safely(download_file(
        URLS['book']['contentUrl'].format(uuid=uuid), f'{path}.epub'))
    # Extra formats requested: FB2 + simple text-only PDF
    try:
        epub_to_fb2(f"{path}.epub", f"{path}.fb2")
    except Exception as e:
        print(f"WARNING: FB2 conversion failed: {e}")
    try:
        epub_to_plain_pdf(f"{path}.epub", f"{path}.pdf")
    except Exception as e:
        print(f"WARNING: PDF conversion failed: {e}")

    add_to_archive(uuid)


def merge_audiobook_chapters_ffmpeg(audiobook_dir, output_file, metadata=None, cleanup_chapters=True):
    """
    Merge all M4A chapter files in a directory into a single audiobook using ffmpeg.
    Creates chapter markers and embeds cover image when available.
    Returns True on success, False otherwise.
    """
    from pathlib import Path
    import subprocess

    audiobook_path = Path(audiobook_dir)
    # Find all M4A files and sort them naturally by chapter number
    chapter_files = sorted([f for f in audiobook_path.glob("*.m4a") if "Глава_" in f.name],
                           key=lambda x: int(re.search(r'Глава_(\d+)\.m4a', x.name).group(1)) if re.search(r'Глава_(\d+)\.m4a', x.name) else 0)
    if not chapter_files:
        print(f"No chapter files found in {audiobook_path}")
        return False

    print(f"Found {len(chapter_files)} chapters, merging with ffmpeg...")

    # Look for cover image
    cover_image = None
    for ext in ['.jpeg', '.jpg', '.png']:
        potential_cover = audiobook_path / f"{audiobook_path.name}{ext}"
        if potential_cover.exists():
            cover_image = potential_cover
            break

    # Create a temporary file list and chapter metadata file for ffmpeg
    filelist_path = audiobook_path / "chapters_list.txt"
    chapters_metadata_path = audiobook_path / "chapters_metadata.txt"

    try:
        # Get chapter durations first (for proper chapter markers)
        print(" Analyzing chapter durations...")
        chapter_durations = []
        current_time = 0.0
        for chapter_file in chapter_files:
            duration_cmd = [
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', str(chapter_file)
            ]
            duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
            if duration_result.returncode == 0 and duration_result.stdout.strip():
                duration = float(duration_result.stdout.strip())
            else:
                print(f"⚠️ Could not get duration for {chapter_file.name}, assuming 180s")
                duration = 180.0
            chapter_durations.append((current_time, current_time + duration, chapter_file))
            current_time += duration

        # Write ffmpeg concat file list
        with open(filelist_path, 'w', encoding='utf-8') as f:
            for chapter_file in chapter_files:
                abs_path = str(chapter_file.absolute()).replace("'", "'\"'\"'")
                f.write(f"file '{abs_path}'\n")

        # Create chapters metadata file
        with open(chapters_metadata_path, 'w', encoding='utf-8') as f:
            f.write(";FFMETADATA1\n")
            # Add global metadata from dictionary if provided
            if metadata:
                for key, value in metadata.items():
                    if value:
                        escaped_value = str(value).replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\\', '\\\\')
                        f.write(f"{key.upper()}={escaped_value}\n")
            # Add chapter markers
            for i, (start_time, end_time, chapter_file) in enumerate(chapter_durations):
                chapter_num = i + 1
                f.write("\n[CHAPTER]\n")
                f.write("TIMEBASE=1/1000\n")
                f.write(f"START={int(start_time * 1000)}\n")
                f.write(f"END={int(end_time * 1000)}\n")
                f.write(f"title=Глава {chapter_num}\n")

        # Build ffmpeg command
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(filelist_path),
            '-i', str(chapters_metadata_path),
        ]
        if cover_image:
            cmd.extend(['-i', str(cover_image)])
            cmd.extend(['-c:v', 'copy'])
            cmd.extend(['-c:a', 'copy'])
            cmd.extend(['-disposition:v:0', 'attached_pic'])
            cmd.extend(['-map_metadata', '1'])
        else:
            cmd.extend(['-c', 'copy'])
            cmd.extend(['-map_metadata', '1'])

        if metadata:
            for key, value in metadata.items():
                if value:
                    cmd.extend(['-metadata', f'{key}={value}'])
        else:
            cmd.extend(['-metadata', f'title={audiobook_path.name}'])
            cmd.extend(['-metadata', 'genre=Audiobook'])
            cmd.extend(['-metadata', 'media_type=2'])

        cmd.append(str(output_file))

        # Run ffmpeg
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            print(f"✅ Successfully merged audiobook: {output_file}")
            # Clean up individual chapter files after successful merge (if requested)
            if cleanup_chapters:
                print(" Cleaning up chapter files...")
                for chapter_file in chapter_files:
                    try:
                        from pathlib import Path as _P
                        _P(chapter_file).unlink()
                        print(f" Removed: {chapter_file.name}")
                    except OSError as e:
                        print(f" ⚠️ Could not remove {chapter_file.name}: {e}")
            return True
        else:
            print(f"❌ Error merging audiobook with ffmpeg:")
            print(result.stderr)
            return False
    finally:
        # Remove temp files
        try:
            if filelist_path.exists():
                filelist_path.unlink()
            if chapters_metadata_path.exists():
                chapters_metadata_path.unlink()
        except Exception:
            pass

def download_audiobook(uuid, series='', max_bitrate=False, merge_chapters=False, cleanup_chapters=True):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = get_resource_info('audiobook', uuid, series)
    resp = get_resource_json('audiobook', uuid)
    if resp:
        # Сформируем базовый порядок ИСКЛЮЧИТЕЛЬНО из playlists.json
        pref_mode = 'max' if max_bitrate else 'min'
        base_order = _playlist_variants_order(resp, pref=pref_mode)  # печатает Available offline variants
        json_data = resp['tracks']
        book_dir = os.path.dirname(path)
        files = os.listdir(book_dir)
        ntracks = len(json_data)
        width = 1 if ntracks < 10 else (2 if ntracks < 100 else 3)

        # Предпочитаемый ключ (первый в base_order)
        pref_key = _preferred_key(base_order)

        for track in json_data:
            ntrack = f'{track["number"]}'
            while len(ntrack) < width:
                ntrack = '0' + ntrack
            name = f'Глава_{ntrack}.m4a'
            out_path = f"{book_dir}/{name}"

            if name in files:
                continue

            # «вежливая» задержка, если включена
            if CONFIG["throttle"] and CONFIG["throttle"] > 0:
                pause = random.uniform(CONFIG["throttle"] / 2, CONFIG["throttle"])
                print(f"Throttling for {pause:.2f}s before next track...")
                time.sleep(pause)

            av = _available_variants_track(track)
            # Try- ordem: фильтруем ДЛЯ ЭТОГО трека согласно base_order
            try_order = [k for k in base_order if k in av]

            if not try_order:
                print(f"❌ No offline URL for track {ntrack}")
                continue

            success = False

            for idx, key in enumerate(try_order):
                url_try = av[key].replace(".m3u8", ".m4a")
                try:
                    # одна попытка без бэкоффа — если 5xx, пробуем следующий вариант качества
                    run_async_safely(download_file_once(url_try, out_path))
                    if idx > 0:
                        # если это не первый (предпочтительный) — сообщаем о даунгрейде/смене
                        print(f"Fallback to {key} for track {ntrack} (preferred {try_order[0]} was 5xx).")
                    success = True
                    break
                except GracefulExit:
                    raise
                except httpx.HTTPStatusError as e:
                    st = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
                    # если не 5xx — это реальная ошибка, пробрасываем немедленно
                    if not (st and 500 <= st <= 599):
                        raise
                    # 5xx — печать body уже была внутри download_file_once; идём понижать качество
                    continue

            if not success:
                # Все варианты дали 5xx: тело ответа уже показали внутри download_file_once.
                print(f"All variants 5xx for track {ntrack}. Will retry preferred with backoff...")
                # следующая попытка — по обычной схеме (с бэкоффом/ретраями)
                # берём предпочитаемый из try_order; если вдруг пусто — пропускаем
                retry_key = try_order[0] if try_order else None
                if not retry_key:
                    print(f"❌ No usable offline variants for track {ntrack}")
                    continue
                final_url = av[retry_key].replace(".m3u8", ".m4a")
                run_async_safely(download_file(final_url, out_path))

        # Merge chapters if requested
        if merge_chapters:
            try:
                output_file = f"{path}.m4a"
                _meta = {"title": os.path.basename(path)}
                ok = merge_audiobook_chapters_ffmpeg(book_dir, output_file, metadata=_meta, cleanup_chapters=cleanup_chapters)
                if not ok:
                    print("⚠️ Merge failed or was skipped.")
            except Exception as e:
                print(f"⚠️ Merge error: {e}")

    else:
        print(f" Audiobook chapters saved separately in: {os.path.dirname(path)}")

    add_to_archive(uuid)

def download_comicbook(uuid, series=''):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = get_resource_info('comicbook', uuid, series)
    resp = get_resource_json('comicbook', uuid)
    if resp:
        download_url = resp["uris"]["zip"]
        namelist = path.split(". ", 2)[:2]
        name = "_".join(namelist)
        download_dir = os.path.dirname(path)
        run_async_safely(download_file(download_url, f'{name}.cbr'))
        with zipfile.ZipFile(f'{name}.cbr', 'r') as zip_ref:
            zip_ref.extractall(download_dir)
        shutil.rmtree(download_dir + "/preview", ignore_errors=False, onerror=None)
        create_pdf_from_images(download_dir, f"{name}.pdf")

    add_to_archive(uuid)

def download_serial(uuid):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = get_resource_info('book', uuid)
    resp = get_resource_json('serial', uuid)
    if resp:
        for episode_index, episode in enumerate(resp["episodes"]):
            name = f"{episode_index+1}. {episode['title']}"
            download_dir = f'{os.path.dirname(path)}/{name}'
            os.makedirs(download_dir, exist_ok=True)
            download_book(episode['uuid'], serial_path=f'{download_dir}/{name}')

    add_to_archive(uuid)

def download_series(uuid):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = get_resource_info('series', uuid)
    resp = get_resource_json('series', uuid)
    name = os.path.basename(path)
    print(name)
    for part_index, part in enumerate(resp['parts']):
        print(part['resource_type'], part['resource']['uuid'])
        func = FUNCTION_MAP[part['resource_type']]
        func(part['resource']['uuid'], f"{name}/{part_index+1}. ")

    add_to_archive(uuid)

# =========================
# Helpers for URL parsing & conversions
# =========================
_YA_AUDIO_RE = re.compile(r"https?://(?:www\.)?books\.yandex\.ru/audiobooks/([A-Za-z0-9_-]+)", re.IGNORECASE)
_YA_BOOK_RE  = re.compile(r"https?://(?:www\.)?books\.yandex\.ru/books/([A-Za-z0-9_-]+)", re.IGNORECASE)

def extract_id_and_type_from_url(url: str) -> tuple[str | None, str | None]:
    """Return (id, type) where type is 'audiobook' or 'book'; otherwise (None, None)."""
    url = url.strip()
    if not url or url.startswith("#") or url.startswith(";"):
        return (None, None)
    # strip query
    url_wo_q = url.split("?", 1)[0]
    m = _YA_AUDIO_RE.search(url_wo_q)
    if m:
        return (m.group(1), 'audiobook')
    m = _YA_BOOK_RE.search(url_wo_q)
    if m:
        return (m.group(1), 'book')
    return (None, None)


def epub_to_plain_pdf(epub_path: str, pdf_path: str):
    """Create a very simple text-only PDF from EPUB contents.
    This is basic: formatting/images are not preserved.
    """
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = epub.read_epub(epub_path)

    # Collect plain text from HTML documents
    paragraphs: list[str] = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text = soup.get_text(separator="\n")
            # Normalize newlines
            parts = [p.strip() for p in text.splitlines()]
            paragraphs.extend([p for p in parts if p])

    # Build PDF
    page_w, page_h = A4
    left = 20 * mm
    right = 20 * mm
    top = 20 * mm
    bottom = 20 * mm
    max_width = page_w - left - right

    c = _canvas.Canvas(pdf_path, pagesize=A4)
    text_obj = c.beginText(left, page_h - top)
    # Use default font, wrap manually
    from textwrap import wrap
    # rough characters-per-line estimation
    cpl = int(max_width / 6.0)  # ~6pt per char at default font

    for para in paragraphs:
        lines = wrap(para, cpl) or [""]
        for line in lines:
            text_obj.textLine(line)
            if text_obj.getY() < bottom:
                c.drawText(text_obj)
                c.showPage()
                text_obj = c.beginText(left, page_h - top)
        # paragraph spacing
        text_obj.textLine("")
        if text_obj.getY() < bottom:
            c.drawText(text_obj)
            c.showPage()
            text_obj = c.beginText(left, page_h - top)

    c.drawText(text_obj)
    c.save()
    print(f"PDF saved to {pdf_path}")


def process_batch_file(batch_path: str, merge_audio_default: bool = False, quality_default: str = 'max', cleanup_chapters_default: bool = True):
    """
    Process URLs from a text file (yt-dlp style). For each URL:
    - If it's an audiobook => download with defaults: merge=merge_audio_default, quality=quality_default
    - If it's a book => download EPUB and additionally produce FB2 and a plain-text PDF
    - Duplicate URLs/IDs are handled by archive.txt automatically
    """
    if not os.path.exists(batch_path):
        print(f"ERROR: Batch file not found: {batch_path}")
        sys.exit(1)

    print(f"Reading URLs from: {batch_path}")
    with open(batch_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    seen: set[str] = set()
    processed = 0
    for ln in lines:
        uid, rtype = extract_id_and_type_from_url(ln)
        if not uid or not rtype:
            print(f"[skip] Unrecognized URL: {ln}")
            continue
        key = f"{rtype}:{uid}"
        if key in seen:
            print(f"[skip] duplicate in batch: {ln}")
            continue
        seen.add(key)

        if rtype == "audiobook":
            print(f"--> Audiobook {uid}: quality={quality_default}, merge_chapters={merge_audio_default}")
            download_audiobook(uid,
                               max_bitrate=(quality_default == 'max'),
                               merge_chapters=merge_audio_default,
                               cleanup_chapters=cleanup_chapters_default)
        elif rtype == "book":
            print(f"--> Book {uid}: downloading EPUB + FB2 + PDF")
            download_book(uid)

        processed += 1
    print(f"Batch done. Processed entries: {processed}")


async def _print_error_body(resp, limit: int = 4000) -> None:
    """Безопасно печатает фрагмент тела ответа (до limit символов)."""
    try:
        # В stream-контексте тело может быть не прочитано — дочитаем
        body = await resp.aread()
        if not body:
            return
        text = body.decode('utf-8', 'replace')
        print("---- Response body (truncated) ----")
        print(text[:limit])
        print("---- end body ----")
    except Exception:
        # Не мешаем основной логике ретраев
        pass


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument("-a", "--batch-file", type=str, default=None,
                           help="Read URLs from a text file (yt-dlp style). Each line is a URL from books.yandex.ru.")
    # Single-run positional: could be a resource command ('book', 'audiobook', etc.), 'auth', a UUID, or a URL
    argparser.add_argument("target", nargs="?",
                           help="Resource type ('book', 'audiobook', 'comicbook', 'serial', 'series'), 'auth', a resource UUID, or a full URL.")
    argparser.add_argument("uuid", nargs="?",
                           help="Resource UUID (when target is a resource type). Ignored if target is a URL or 'auth'.")

    # Оставляем ровно два режима CLI: max и min.
    # Порядок вариантов внутри берём из playlists.json:
    #   max -> как напечатает "Available offline variants"
    #   min -> реверс этого списка
    argparser.add_argument("--quality", choices=["max", "min"], default="max",
                           help="Audio quality preference (default: max). The exact variants are taken from playlists.json.")
    # Network behaviour
    argparser.add_argument("--proxy", type=str, default=None, help="Proxy URL, e.g. socks5h://127.0.0.1:9050 or http://127.0.0.1:8080")
    argparser.add_argument("--throttle", type=float, default=None, help="Polite delay (seconds) between track downloads (e.g. 1.5)")
    argparser.add_argument("--max-retries", type=int, default=None, help="Total retries for requests/downloads (default 5)")
    argparser.add_argument("--backoff-initial", type=float, default=None, help="Initial backoff seconds (default 5)")
    argparser.add_argument("--timeout-base-req", type=float, default=None, help="Base timeout for metadata requests (default 10)")
    argparser.add_argument("--timeout-base-dl", type=float, default=None, help="Base timeout for file downloads (default 15)")
    argparser.add_argument("--force-meta", action="store_true", help="Overwrite meta files (jpeg/json/info.txt) even if they exist")
    argparser.add_argument("--archive", type=str, default="archive.txt", help="Path to archive file with downloaded IDs")
    argparser.add_argument("--no-merge", action="store_true", help="(Legacy, default is no-merge)")
    argparser.add_argument("--keep-chapters", action="store_true", help="Keep individual chapter files after merging")
    argparser.add_argument("--merge-chapters", action="store_true", help="Merge audiobook chapters into a single file (default: do not merge)")
    args = argparser.parse_args()

    # Merge behavior: default is DO NOT merge
    merge_flag = True if getattr(args, 'merge_chapters', False) else False

    # Archive initialization
    init_archive(args.archive)

    # Authorization token
    HEADERS['auth-token'] = get_auth_token()

    # Proxy: arg or env
    proxy_url = args.proxy or os.environ.get("BOOKMATE_PROXY")
    if proxy_url:
        CONFIG["proxy_url"] = proxy_url
        print(f"Using proxy: {proxy_url}")

    # Networking tweaks
    if args.throttle is not None:
        CONFIG["throttle"] = max(0.0, args.throttle)
    if args.max_retries is not None:
        CONFIG["max_retries"] = max(1, args.max_retries)
    if args.backoff_initial is not None:
        CONFIG["backoff_initial"] = max(0.1, args.backoff_initial)
    if args.timeout_base_req is not None:
        CONFIG["timeout_base_request"] = max(1.0, args.timeout_base_req)
    if args.timeout_base_dl is not None:
        CONFIG["timeout_base_download"] = max(1.0, args.timeout_base_dl)
    if args.force_meta:
        CONFIG["force_meta"] = True

    # Auth-only command
    if args.target == "auth":
        token = get_auth_token(force=True)
        print("✅ Токен получен и сохранён в token.txt")
        return

    # Batch mode
    if args.batch_file:
        process_batch_file(
            args.batch_file,
            merge_audio_default=merge_flag,
            quality_default=args.quality,
            cleanup_chapters_default=not args.keep_chapters,
        )
        return

    # No batch: target can be URL, resource type + uuid, or just uuid
    if not args.target:
        # Backward-compatible behavior: open auth window if no args at all
        token = get_auth_token(force=False)
        print("✅ Токен получен и сохранён в token.txt" if token else "❌ Не удалось получить токен")
        return

    # URL mode (auto-detect resource type)
    if isinstance(args.target, str) and args.target.startswith(("http://", "https://")):
        uid, rtype = extract_id_and_type_from_url(args.target)
        if not uid or not rtype:
            print(f"❌ Unrecognized URL: {args.target}")
            sys.exit(2)
        if rtype == "audiobook":
            download_audiobook(uid,
                               max_bitrate=(args.quality == 'max'),
                               merge_chapters=merge_flag,
                               cleanup_chapters=not args.keep_chapters)
        elif rtype == "book":
            download_book(uid)
        else:
            print(f"❌ URL type '{rtype}' is not supported for direct URL mode.")
            sys.exit(2)
        return

    # Resource type + UUID
    if args.target in FUNCTION_MAP:
        if not args.uuid:
            argparser.error("the following arguments are required for this command: uuid")
        func = FUNCTION_MAP[args.target]
        if args.target == "audiobook":
            func(args.uuid,
                 max_bitrate=(args.quality == 'max'),
                 merge_chapters=merge_flag,
                 cleanup_chapters=not args.keep_chapters)
        else:
            func(args.uuid)
        return

    # If user passed only UUID (no explicit type) — try as book first, then audiobook
    guess = args.target
    if re.match(r"^[A-Za-z0-9_-]+$", guess):
        try:
            download_book(guess)
            return
        except SystemExit:
            raise
        except Exception:
            download_audiobook(guess,
                               max_bitrate=(args.quality == 'max'),
                               merge_chapters=merge_flag,
                               cleanup_chapters=not args.keep_chapters)
            return

    print(f"❌ Unknown target: {args.target}")
    sys.exit(2)


FUNCTION_MAP = {
    'book': download_book,
    'audiobook': download_audiobook,
    'comicbook': download_comicbook,
    'serial': download_serial,
    'series': download_series
}

if __name__ == "__main__":
    try:
        # If run without arguments: open auth flow (backward-compatible behavior)
        if len(sys.argv) == 1:
            tok = get_auth_token(force=False)
            print("✅ Токен получен и сохранён в token.txt" if tok else "❌ Не удалось получить токен")
            sys.exit(0)
        main()
    except GracefulExit as e:
        code = e.code if isinstance(e.code, int) else 130
        print("Завершено.")
        sys.exit(code)
    except KeyboardInterrupt:
        print("\nЗавершено по Ctrl+C.")
        sys.exit(130)
