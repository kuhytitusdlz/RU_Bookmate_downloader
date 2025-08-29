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

            if attempt < max_retries - 1 and (status in (None, RETRY_STATUSES)):
                base_wait = backoff_initial * factor
                wait_s = max(base_wait, retry_after or 0.0)
                wait_s = min(wait_s, backoff_cap) + random.uniform(0, 0.8)
                human = f"HTTP {status}" if status else f"{type(e).__name__}"
                print(
                    f"Download attempt {attempt+1}/{max_retries} failed ({human}). "
                    f"Retrying in {wait_s:.1f}s..."
                )
                await asyncio.sleep(wait_s)
            else:
                print("Failed to download the file after several attempts.")
                sys.exit(1)


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
                    raise httpx.HTTPStatusError(
                        f"Bad status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()

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
                human = f"HTTPStatusError: Bad status {status}" if status else f"{type(e).__name__}"
                print(
                    f"Request attempt {attempt+1}/{max_retries} failed ({human}). "
                    f"Retrying in {wait_s:.1f}s..."
                )
                await asyncio.sleep(wait_s)
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
        fb2_file.write(fb2_content)

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
    info = asyncio.run(send_request(info_url)).json()
    if not info:
        return None

    picture_url = info[resource_type]["cover"]["large"]
    name = info[resource_type]["title"]
    name = replace_forbidden_chars(name)
    namelist = name.split(". ", 2)[:2]
    name = "_".join(namelist)

    download_dir = f"mybooks/{'series' if series else resource_type}/{series}{name}/"
    path = f'{download_dir}{name}'
    os.makedirs(download_dir, exist_ok=True)

    # --- JPEG (обложка) ---
    jpeg_path = f'{path}.jpeg'
    if os.path.isfile(jpeg_path) and not CONFIG["force_meta"]:
        print(f"Cover already exists, skip: {jpeg_path}")
    else:
        asyncio.run(download_file(picture_url, jpeg_path))

    # --- JSON с meta ---
    json_path = f"{path}.json"
    if os.path.isfile(json_path) and not CONFIG["force_meta"]:
        print(f"JSON already exists, skip: {json_path}")
    else:
        with open(json_path, 'w', encoding='utf-8') as file:
            file.write(json.dumps(info, ensure_ascii=False))
        print(f"File downloaded successfully to {json_path}")

    # --- Аннотация info.txt ---
    book_info = info[resource_type]['annotation']
    book_info += "\n\n"

    if info[resource_type]['age_restriction']:
        if int(info[resource_type]['age_restriction']) > 0:
            book_info += "\nВозрастные ограничения: "
            book_info += info[resource_type]['age_restriction'] + "+"

    if info[resource_type]['owner_catalog_title']:
        book_info += "\nПравообладатель: "
        book_info += info[resource_type]['owner_catalog_title']

    if info[resource_type]['publishers']:
        i = 0
        for publisher in info[resource_type]['publishers']:
            if i > 0:
                book_info += ", "
            else:
                book_info += "\nИздательство: "
            book_info += publisher['name']
            i += 1

    if info[resource_type]['publication_date']:
        book_info += "\nГод выхода издания: "
        import datetime as dt
        epoch_time = int(info[resource_type]['publication_date'])
        book_info += dt.datetime.fromtimestamp(epoch_time).strftime('%Y')

    if info[resource_type]['duration']:
        book_info += "\nДлительность: "
        epoch_time = int(info[resource_type]['duration'])
        seconds = epoch_time % 60
        minutes = int(epoch_time / 60) % 60
        hours = int(epoch_time / 3600)
        if hours > 0:
            book_info += str(hours) + " ч. "
        book_info += str(minutes) + " мин. "
        book_info += str(seconds) + " сек. "

    if info[resource_type]['translators']:
        i = 0
        for translator in info[resource_type]['translators']:
            if i > 0:
                book_info += ", "
            else:
                book_info += "\nПеревод: "
            book_info += translator['name']
            i += 1

    if info[resource_type]['narrators']:
        i = 0
        for narrator in info[resource_type]['narrators']:
            if i > 0:
                book_info += ", "
            else:
                book_info += "\nОзвучили: "
            book_info += narrator['name']
            i += 1

    if info[resource_type]['topics']:
        i = 0
        for topic in info[resource_type]['topics']:
            if topic['title'] != "Аудио":
                if i > 0:
                    book_info += ", "
                else:
                    book_info += "\n\nТеги: "
                book_info += topic['title']
            i += 1

    # write_book_info сама пропустит запись, если info.txt уже есть (если не force_meta)
    write_book_info(book_info, os.path.join(download_dir, "info"), overwrite=CONFIG["force_meta"])

    return path


def get_resource_json(resource_type, uuid):
    url = URLS[resource_type]['contentUrl'].format(uuid=uuid)
    return asyncio.run(send_request(url)).json()


def download_book(uuid, series='', serial_path=None):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = serial_path if serial_path else get_resource_info('book', uuid, series)
    asyncio.run(download_file(
        URLS['book']['contentUrl'].format(uuid=uuid), f'{path}.epub'))
    # epub_to_fb2(f"{path}.epub", f"{path}.fb2")

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
                        Path(chapter_file).unlink()
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
def download_audiobook(uuid, series='', max_bitrate=False, merge_chapters=True, cleanup_chapters=True):
    if is_archived(uuid):
        print(f"[archive] Skipping already downloaded: {uuid}")
        return
    path = get_resource_info('audiobook', uuid, series)
    resp = get_resource_json('audiobook', uuid)
    if resp:
        bitrate = 'max_bit_rate' if max_bitrate else 'min_bit_rate'
        json_data = resp['tracks']
        book_dir = os.path.dirname(path)
        files = os.listdir(book_dir)
        ntracks = len(json_data)
        if ntracks < 10:
            width = 1
        elif 10 <= ntracks < 100:
            width = 2
        else:
            width = 3

        for track in json_data:
            ntrack = f'{track["number"]}'
            i = len(ntrack)
            while i < width:
                ntrack = '0' + ntrack
                i = i + 1
            name = 'Глава_' + ntrack + '.m4a'
            if name not in files:
                download_url = track['offline'][bitrate]['url'].replace(".m3u8", ".m4a")
                # «вежливая» задержка, если включена
                if CONFIG["throttle"] and CONFIG["throttle"] > 0:
                    pause = random.uniform(CONFIG["throttle"] / 2, CONFIG["throttle"])
                    print(f"Throttling for {pause:.2f}s before next track...")
                    time.sleep(pause)
                asyncio.run(download_file(download_url, f"{book_dir}/{name}"))
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
        asyncio.run(download_file(download_url, f'{name}.cbr'))
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

def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument("command", choices=list(FUNCTION_MAP.keys()) + ["auth"])
    argparser.add_argument("uuid", nargs="?")
    # ИСТОРИЧЕСКИЙ ФЛАГ: при наличии флага используем max_bitrate=False -> берём 'min_bit_rate'
    argparser.add_argument("--max-bitrate", action='store_false', help="Use min_bit_rate if flag is present (legacy behavior).")
    # Новые параметры управления сетевым поведением
    argparser.add_argument("--proxy", type=str, default=None, help="Proxy URL, e.g. socks5h://127.0.0.1:9050 or http://127.0.0.1:8080")
    argparser.add_argument("--throttle", type=float, default=None, help="Polite delay (seconds) between track downloads (e.g. 1.5)")
    argparser.add_argument("--max-retries", type=int, default=None, help="Total retries for requests/downloads (default 5)")
    argparser.add_argument("--backoff-initial", type=float, default=None, help="Initial backoff seconds (default 5)")
    argparser.add_argument("--timeout-base-req", type=float, default=None, help="Base timeout for metadata requests (default 10)")
    argparser.add_argument("--timeout-base-dl", type=float, default=None, help="Base timeout for file downloads (default 15)")
    argparser.add_argument("--force-meta", action="store_true", help="Overwrite meta files (jpeg/json/info.txt) even if they exist")
    argparser.add_argument("--archive", type=str, default="archive.txt", help="Path to archive file with downloaded IDs")
    argparser.add_argument("--no-merge", action='store_true', help="Keep audiobook chapters as separate files (don't merge)")
    argparser.add_argument("--keep-chapters", action='store_true', help="Keep individual chapter files after merging")
    args = argparser.parse_args()

    # Archive initialization
    init_archive(args.archive)

    # Early archive check to avoid unnecessary auth/network if already downloaded
    if is_archived(args.uuid):
        print(f"[archive] Skipping already downloaded: {args.uuid}")
        return

    # Токен авторизации
    HEADERS['auth-token'] = get_auth_token()

    # Прокси: из аргумента или переменной окружения BOOKMATE_PROXY
    proxy_url = args.proxy or os.environ.get("BOOKMATE_PROXY")
    if proxy_url:
        CONFIG["proxy_url"] = proxy_url
        print(f"Using proxy: {proxy_url}")

    # Параметры сетевого поведения
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


    # Обработка команды авторизации и валидация uuid
    if args.command == "auth":
        token = get_auth_token(force=True)
        print("✅ Токен получен и сохранён в token.txt")
        return
    if args.command != "auth" and not args.uuid:
        argparser.error("the following arguments are required for this command: uuid")

    # Вызов команды
    func = FUNCTION_MAP[args.command]
    if args.command == 'audiobook':
        func(args.uuid, max_bitrate=args.max_bitrate, merge_chapters=not args.no_merge, cleanup_chapters=not args.keep_chapters)
    else:
        func(args.uuid)


FUNCTION_MAP = {
    'book': download_book,
    'audiobook': download_audiobook,
    'comicbook': download_comicbook,
    'serial': download_serial,
    'series': download_series
}

if __name__ == "__main__":
    # If run without arguments: open auth flow (backward-compatible behavior)
    if len(sys.argv) == 1:
        tok = get_auth_token(force=False)
        print("✅ Токен получен и сохранён в token.txt" if tok else "❌ Не удалось получить токен")
        sys.exit(0)
    main()
