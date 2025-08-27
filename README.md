# RU_Bookmate_downloader
## Установка зависимостей:
`pip install -r requirements.txt`

## Авторизоваться в аккаунт Яндекс
![Авторизация](https://github.com/kettle017/RU_Bookmate_downloader/assets/37309120/bb3453eb-5d44-4410-b2e1-05193c88333e)

## Примеры запуска скрипта:
Для определения нужного флага смотрите на URL, в нем всегда есть подсказка: https://bookmate.ru/<флаг>/<id>\
1. Скачать аудиокнигу в максимальном качестве:\
`python RUBookmatedownloader.py audiobook <id> --max_bitrate`
3. Скачать аудиокнигу в обычном качестве:\
`python RUBookmatedownloader.py audiobook <id>`
4. Скачать текстовую книгу:\
`python RUBookmatedownloader.py book <id>`
5. Скачать комикс:\
`python RUBookmatedownloader.py comicbook <id>`
6. Скачать текстовую книгу, разбитую на несколько частей:\
`python RUBookmatedownloader.py serial <id>`
5. Скачать серию текстовых книг, аудиокниг или комиксов:\
`python RUBookmatedownloader.py series <id>`

## run example
```bash
pip install virtualenv
git clone ..
cd .\RU_Bookmate_downloader\
virtualenv venv
venv\Scripts\activate
pip install -r .\requirements.txt

# авторизация
python RUBookmatedownloader.py
# скачать аудио
set BOOKMATE_PROXY=socks5h://127.0.0.1:9050
python RUBookmatedownloader.py audiobook --max_bitrate <id>

```