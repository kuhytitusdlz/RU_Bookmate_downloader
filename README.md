# RU_Bookmate_downloader

## Установка зависимостей
```bash
pip install -r requirements.txt
```

## Авторизация
Впервые запустите скрипт без параметров и авторизуйтесь.

## Примеры запуска
Подсказка по типу ресурса есть в URL: `https://bookmate.ru/<флаг>/<id>`.

### Основные команды
1. Скачать аудиокнигу в **максимальном** качестве:  
   ```bash
   python RUBookmatedownloader.py audiobook <id> --max-bitrate
   ```
2. Скачать аудиокнигу в обычном качестве:  
   ```bash
   python RUBookmatedownloader.py audiobook <id>
   ```
3. Скачать аудиокнигу **без объединения** глав:  
   ```bash
   python RUBookmatedownloader.py audiobook <id> --no-merge
   ```
4. Скачать аудиокнигу и **сохранить отдельные главы** после объединения:  
   ```bash
   python RUBookmatedownloader.py audiobook <id> --keep-chapters
   ```
5. Скачать текстовую книгу:  
   ```bash
   python RUBookmatedownloader.py book <id>
   ```
6. Скачать комикс:  
   ```bash
   python RUBookmatedownloader.py comicbook <id>
   ```
7. Скачать «сериал» (текстовая книга из нескольких частей):  
   ```bash
   python RUBookmatedownloader.py serial <id>
   ```
8. Скачать **серию** (подборку книг/аудиокниг/комиксов):  
   ```bash
   python RUBookmatedownloader.py series <id>
   ```

### Объединение глав аудиокниг
По умолчанию главы аудиокниг **объединяются автоматически** в один файл после скачивания.  
Если вы скачали главы отдельно или хотите переобъединить существующую аудиокнигу, используйте отдельный скрипт:

1. Объединить **одну** аудиокнигу:  
   ```bash
   python merge_audiobook.py "путь/к/папке/аудиокниги"
   ```
2. Объединить **все** аудиокниги в папке `mybooks/audiobook/`:  
   ```bash
   python merge_audiobook.py --batch
   ```
3. Принудительно **перезаписать** уже объединённые файлы:  
   ```bash
   python merge_audiobook.py --batch --force
   ```
4. **Сохранить главы** после объединения:  
   ```bash
   python merge_audiobook.py --batch --keep-chapters
   ```

> Примечание: для быстрой и «без потерь» склейки используется `ffmpeg` (если установлен). При его отсутствии выполняется резервное объединение через `pydub` с повторным кодированием. Рекомендуется установить `ffmpeg` и добавить его в `PATH`.

### Архив скачанных книг (как в yt-dlp)
Скрипт ведёт файл `archive.txt` в рабочей папке: каждый скачанный ID — на новой строке.  
Перед загрузкой проверяется, не скачивалась ли книга ранее; при совпадении ID загрузка пропускается.  
Можно указать свой файл архива:
```bash
python RUBookmatedownloader.py audiobook <id> --archive /path/to/my-archive.txt
```

### Полезные параметры
- `--proxy` — прокси для всех запросов, например: `socks5h://127.0.0.1:9050` или `http://127.0.0.1:8080`  
- `--throttle` — «вежливая» задержка (в сек) между скачиваниями треков, например `1.5`  
- `--max-bitrate` — использовать максимальный битрейт у аудиокниг  
- `--no-merge` — не объединять главы после скачивания  
- `--keep-chapters` — не удалять файлы глав после объединения  
- `--archive` — путь к файлу архива ID

### Пример под Windows (PowerShell)
```powershell
git clone <repo-url>
cd .\RU_Bookmate_downloader\
python -m venv .venv
venv\Scripts\activate
pip install -r .\requirements.txt

# Авторизация
python RUBookmatedownloader.py

# Скачать аудио через прокси и не объединять главы
$env:BOOKMATE_PROXY='socks5h://127.0.0.1:9050'
python RUBookmatedownloader.py audiobook --no-merge --max-bitrate <id>
```
