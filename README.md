# RUBookmatedownloader

> **Основной способ — готовая Windows‑сборка `.exe`.** Вариант через Python приведён ниже как альтернативный.  
> В `.exe` уже включён **FFmpeg** (ffmpeg/ffprobe/ffplay), отдельно ставить не нужно.

---

## 🚀 Быстрый старт (Windows, готовый `.exe`)

1. **Скачайте** архив релиза: `RUBookmateDownloader-win64.zip` (в разделе *Releases*).
2. **Распакуйте** в удобную папку (например, `C:\Apps\RUBookmateDownloader\`).  
   Внутри уже есть `RUBookmateDownloader.exe` **и** готовые `ffmpeg.exe / ffprobe.exe / ffplay.exe`.
3. **Первый запуск / вход**  
   Откройте PowerShell в папке программы и выполните:
   ```powershell
   .\RUBookmateDownloader.exe
   ```
   Если `token.txt` отсутствует — откроется окно авторизации (OAuth Яндекс/Bookmate). Токен будет сохранён в `token.txt`.  
   Для принудительной переавторизации используйте команду:
   ```powershell
   .\RUBookmateDownloader.exe auth
   ```
4. **Использование (примеры)**  
   Тип ресурса можно понять по URL: `https://bookmate.ru/<тип>/<id>` — например: `audiobook`, `book`, `comicbook`, `serial`, `series`.

   **Аудиокнига (макс. качество):**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --merge-chapters --max-bitrate
   ```

   **Аудиокнига (обычное качество):**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --merge-chapters
   ```

   **Объединение глав (опционально):**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --merge-chapters --merge-chapters
   ```

   **Оставить отдельные главы после объединения:**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --merge-chapters --keep-chapters
   ```

   **Текстовая книга:**
   ```powershell
   .\RUBookmateDownloader.exe book <id>
   ```

   **Комикс:**
   ```powershell
   .\RUBookmateDownloader.exe comicbook <id>
   ```

   **Сериал (текст из частей):**
   ```powershell
   .\RUBookmateDownloader.exe serial <id>
   ```

   **Серия (подборка):**
   ```powershell
   .\RUBookmateDownloader.exe series <id>
   ```

5. **Прокси (опционально)**  
   - Параметром CLI:
     ```powershell
     .\RUBookmateDownloader.exe audiobook <id> --merge-chapters --proxy "socks5h://127.0.0.1:9050"
     ```
   - Или переменной окружения (PowerShell):
     ```powershell
     $env:BOOKMATE_PROXY = "http://127.0.0.1:8080"
     # или
     $env:BOOKMATE_PROXY = "socks5h://127.0.0.1:9050"
     .\RUBookmateDownloader.exe audiobook <id> --merge-chapters
     ```

6. **Архив скачанных (как у yt-dlp)**  
   Приложение ведёт `archive.txt` в рабочей папке: **каждый скачанный ID** — на новой строке.  
   Перед загрузкой ID проверяется; при совпадении загрузка **пропускается**. Можно указать свой файл:
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --merge-chapters --archive "D:\my-archive.txt"
   ```

7. **Объединение глав аудиокниг**  
   По умолчанию главы **объединяются** в один файл (`ffmpeg` уже включён в `.exe`).  
   Ключи управления: `--merge-chapters`, `--keep-chapters`.

8. **Траблшутинг (Windows)**  
   - **SmartScreen/Defender**: при первом запуске может предупреждать. Откройте свойства файла → «Разблокировать», либо «Дополнительно → Всё равно выполнить».
   - **Сеть/блокировки**: используйте `--proxy` или переменную `BOOKMATE_PROXY`; при необходимости увеличьте паузы `--throttle 1.5`.
   - **Повторная авторизация**: `auth` или удалите `token.txt`.

---

## 🐍 Альтернативный запуск через Python

1. **Установите зависимости**
   ```bash
   pip install -r requirements.txt
   ```

2. **Авторизация**  
   Запуск без аргументов открывает окно входа (если нет `token.txt`):
   ```bash
   python RUBookmatedownloader.py
   ```
   Принудительная переавторизация:
   ```bash
   python RUBookmatedownloader.py auth
   ```

3. **Примеры команд**
   ```bash
   # Аудиокнига (макс. качество)
   python RUBookmatedownloader.py audiobook <id> --merge-chapters --max-bitrate

   # Аудиокнига (обычное качество)
   python RUBookmatedownloader.py audiobook <id> --merge-chapters

   # Не объединять главы
   python RUBookmatedownloader.py audiobook <id> --merge-chapters --merge-chapters

   # Оставить отдельные главы после объединения
   python RUBookmatedownloader.py audiobook <id> --merge-chapters --keep-chapters

   # Текстовая книга
   python RUBookmatedownloader.py book <id>

   # Комикс
   python RUBookmatedownloader.py comicbook <id>

   # Сериал (текст из частей)
   python RUBookmatedownloader.py serial <id>

   # Серия (подборка)
   python RUBookmatedownloader.py series <id>
   ```

4. **Параметры CLI (выдержка)**
   - `--proxy <url>` — HTTP/SOCKS5(h) прокси (например, `socks5h://127.0.0.1:9050`).  
   - `--throttle <sec>` — задержка между запросами/треками (по умолчанию разумная).  
   - `--max-retries <n>` — число повторов при ошибках сети.  
   - `--backoff-initial <sec>` — стартовая пауза экспоненциального backoff.  
   - `--timeout-base-req <sec>`, `--timeout-base-dl <sec>` — базовые таймауты для запросов/скачиваний.  
   - `--force-meta` — принудительно сохранять метаданные обложек/глав при наличии.  
   - `--archive <path>` — путь к файлу со списком уже скачанных ID.  
   - `--merge-chapters`, `--keep-chapters` — управление склейкой глав аудио.

5. **Нюансы FFmpeg**
   - В `.exe`‑версии **FFmpeg уже включён**.  
   - В Python‑варианте нужен `ffmpeg` в `PATH` (Linux: `apt install ffmpeg`, macOS: `brew install ffmpeg`, Windows: используйте готовые сборки, например BtbN, и добавьте `bin` в `PATH`).

6. **Примечания по авторизации (OAuth)**
   - Приложение использует implicit flow в окне `pywebview`.  
   - Необязательно, но можно задать свой OAuth **`client_id`** через переменную окружения **`YANDEX_CLIENT_ID`**. Если не задана — используется дефолтный ID, прошитый в коде.  
   - Токен хранится локально в `token.txt`. Удалите файл для «выхода» либо выполните команду `auth`.  
   - Windows: при проблемах с окном авторизации установите **WebView2 Runtime** (обычно ставится с Microsoft Edge).  
     Linux/macOS: `pywebview` использует QtWebEngine — пакет `pywebview[qt]` уже учтён в `requirements.txt`.

---

## 🔧 Сборка `.exe` (для контрибьюторов)
- GitHub Actions (`build-exe.yml`) собирает однофайловый EXE и подтягивает **готовую сборку FFmpeg** (BtbN, `win64 gpl-shared`), копируя весь `bin` рядом с EXE.

---

## 📜 Изменения (2025-08-29)
- Улучшена авторизация: запуск без аргументов открывает окно входа (если нет `token.txt`); добавлена команда `auth`.
- Убран хардкод поддомена `yx<client_id>…` — принимаются редиректы с `*.oauth.yandex.ru`, добавлена проверка `state`.
- В `.exe` включён FFmpeg; для Python оставлены инструкции по установке.
- Поддержка `archive.txt` (как у yt-dlp), `--merge-chapters` и `--keep-chapters`.


### 📄 Загрузка списка URL из файла (как в yt-dlp)

Можно передать файл со списком ссылок (по одной в строке), например `1.txt`:

```
https://books.yandex.ru/audiobooks/xxxxxxx?utm_place=post_slider
https://books.yandex.ru/audiobooks/yyyyyyy
https://books.yandex.ru/books/zzzzzz
```

Запустите:
```bash
python RUBookmatedownloader.py -a 1.txt
# или для .exe
RUBookmateDownloader.exe -a 1.txt
```

- Ссылки с `.../audiobooks/<id>` будут скачаны **как аудиокниги** с параметрами по умолчанию для списка:
  **без объединения глав** (`--merge-chapters`) и **в максимальном качестве** (эквивалент `--max-bitrate`).  
  (Примечание: в одиночном режиме по умолчанию и так используется максимальный битрейт; флаг `--max-bitrate` в CLI — исторический, и при его наличии переключает на *минимальный* битрейт.)

- Ссылки с `.../books/<id>` будут скачаны **как текстовые книги** в формат **EPUB**, а также будут автоматически созданы **FB2** и **PDF (текстовая, базовая конверсия)** рядом с EPUB.

- Пустые строки и строки, начинающиеся с `#` или `;`, пропускаются. Дубли URL внутри файла игнорируются.

- **Архив скачанных** (`archive.txt`) используется так же, как и в одиночном режиме: если ID уже есть, загрузка пропускается.


> По умолчанию главы аудиокниг **не объединяются**. Чтобы собрать единый файл, добавьте флаг `--merge-chapters`. `--keep-chapters` оставит отдельные файлы глав после склейки.
