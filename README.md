# RUBookmatedownloader

> **Основной способ — готовая Windows‑сборка `.exe`.** Вариант через Python оставлен ниже как альтернатива.

---

## 🚀 Быстрый старт (Windows, готовый `.exe`)

1. **Скачайте** архив релиза: `RUBookmateDownloader-win64.zip` (в разделе *Releases*).
2. **Распакуйте** в удобную папку (например, `C:\Apps\RUBookmateDownloader\`).  
   Внутри уже есть `RUBookmateDownloader.exe` **и** готовые `ffmpeg.exe / ffprobe.exe / ffplay.exe` — **ничего отдельно ставить не нужно**.
3. **Первый запуск / вход**  
   Откройте PowerShell в папке программы и выполните:
   ```powershell
   .\RUBookmateDownloader.exe
   ```
   Следуйте подсказкам для авторизации в Bookmate.
4. **Использование (примеры)**  
   Тип ресурса можно понять по URL: `https://bookmate.ru/<тип>/<id>` (например: `audiobook`, `book`, `comicbook`, `serial`, `series`).

   **Аудиокнига (макс. качество):**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --max-bitrate
   ```

   **Аудиокнига (обычное качество):**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id>
   ```

   **Не объединять главы:**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --no-merge
   ```

   **Оставить отдельные главы после объединения:**
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --keep-chapters
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

5. **Прокси (по желанию)**  
   - Параметром:
     ```powershell
     .\RUBookmateDownloader.exe audiobook <id> --proxy "socks5h://127.0.0.1:9050"
     ```
   - Или переменной окружения (PowerShell):
     ```powershell
     $env:BOOKMATE_PROXY = "http://127.0.0.1:8080"
     .\RUBookmateDownloader.exe audiobook <id>
     ```

6. **Архив скачанных (как у yt‑dlp)**  
   Приложение ведёт файл `archive.txt` в рабочей папке: **каждый скачанный ID** — на новой строке.  
   Перед загрузкой ID проверяется; при совпадении загрузка **пропускается**. Можно указать свой файл:
   ```powershell
   .\RUBookmateDownloader.exe audiobook <id> --archive "D:\my-archive.txt"
   ```

7. **Объединение глав аудиокниг**  
   По умолчанию главы **объединяются** в один файл (используется `ffmpeg`, уже лежит в папке рядом с EXE).  
   Ключи управления: `--no-merge`, `--keep-chapters`.

8. **Траблшутинг**
   - **SmartScreen/Defender**: при первом запуске может предупреждать. Откройте свойства файла → «Разблокировать», либо «Дополнительно → Все равно выполнить».
   - **«ID уже скачан»**: ID есть в `archive.txt`. Удалите строку или укажите другой файл `--archive`.
   - **Сеть / блокировки**: попробуйте `--proxy` или переменную `BOOKMATE_PROXY`. При необходимости увеличьте паузу между треками `--throttle 1.5`.

---

## 🐍 Альтернативный способ: запуск через Python

1. **Зависимости**
   ```bash
   pip install -r requirements.txt
   ```

2. **Первый запуск / авторизация**
   ```bash
   python RUBookmatedownloader.py
   ```

3. **Примеры**
   ```bash
   # Аудиокнига (макс. качество)
   python RUBookmatedownloader.py audiobook <id> --max-bitrate

   # Аудиокнига (обычное качество)
   python RUBookmatedownloader.py audiobook <id>

   # Не объединять главы
   python RUBookmatedownloader.py audiobook <id> --no-merge

   # Оставить отдельные главы после объединения
   python RUBookmatedownloader.py audiobook <id> --keep-chapters

   # Текстовая книга
   python RUBookmatedownloader.py book <id>

   # Комикс
   python RUBookmatedownloader.py comicbook <id>

   # Сериал (текст из частей)
   python RUBookmatedownloader.py serial <id>

   # Серия (подборка)
   python RUBookmatedownloader.py series <id>
   ```

4. **Объединение глав отдельно (опционально)**  
   Если нужно переобъединить скачанную аудиокнигу:
   ```bash
   # одну аудиокнигу
   python merge_audiobook.py "путь/к/папке/аудиокниги"

   # все в mybooks/audiobook/
   python merge_audiobook.py --batch

   # перезаписать готовые файлы
   python merge_audiobook.py --batch --force

   # сохранить главы
   python merge_audiobook.py --batch --keep-chapters
   ```

5. **Нюансы FFmpeg**
   - В `.exe`‑версии **FFmpeg уже включён** (лежит рядом с `RUBookmateDownloader.exe`).  
   - В Python‑варианте нужен `ffmpeg` в `PATH` для быстрой/без потерь склейки.  
     Установка: **Linux** — `apt install ffmpeg`, **macOS** — `brew install ffmpeg`, **Windows** — используйте готовые сборки (например, BtbN) и добавьте `bin` в `PATH`.

---

## 🔧 Сборка `.exe` (для контрибьюторов)
- GitHub Actions (`build-exe.yml`) собирает однофайловый EXE и подтягивает **готовую сборку FFmpeg** (BtbN, `win64 gpl-shared`), копируя весь `bin` рядом с EXE.
- Результат: `release/RUBookmateDownloader-win64.zip`.
