#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_audiobook.py — объединение глав аудиокниги в один файл.
По умолчанию ищет каталоги с главами вида "Глава_XX.m4a" и обложку "<Название>.(jpeg|jpg|png)".
Создаёт файл <Название>_complete.m4a с главами и метаданными.
"""

import os
import re
import glob
import argparse
from pathlib import Path
import json
import subprocess

def merge_audiobook_chapters_ffmpeg(audiobook_dir, output_file, metadata=None, cleanup_chapters=True):
    """Объединяет m4a главы с помощью ffmpeg, добавляет главы и обложку."""
    audiobook_path = Path(audiobook_dir)
    chapter_files = sorted([f for f in audiobook_path.glob("*.m4a") if "Глава_" in f.name],
                           key=lambda x: int(re.search(r'Глава_(\d+)\.m4a', x.name).group(1)) if re.search(r'Глава_(\d+)\.m4a', x.name) else 0)
    if not chapter_files:
        print(f"[skip] Нет глав в {audiobook_path}")
        return False

    cover_image = None
    for ext in ('.jpeg', '.jpg', '.png'):
        p = audiobook_path / f"{audiobook_path.name}{ext}"
        if p.exists():
            cover_image = p
            break

    filelist_path = audiobook_path / "chapters_list.txt"
    chapters_metadata_path = audiobook_path / "chapters_metadata.txt"
    try:
        # длительности
        chapter_durations = []
        current_time = 0.0
        for ch in chapter_files:
            cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(ch)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            dur = float(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else 180.0
            chapter_durations.append((current_time, current_time + dur, ch))
            current_time += dur

        with open(filelist_path, 'w', encoding='utf-8') as f:
            for ch in chapter_files:
                ap = str(ch.absolute()).replace("'", "\\'")
                f.write(f"file '{ap}'\n")

        with open(chapters_metadata_path, 'w', encoding='utf-8') as f:
            f.write(";FFMETADATA1\n")
            if metadata:
                for k, v in metadata.items():
                    if v:
                        ev = str(v).replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\\', '\\\\')
                        f.write(f"{k.upper()}={ev}\n")
            for i, (start, end, _) in enumerate(chapter_durations):
                f.write("\n[CHAPTER]\nTIMEBASE=1/1000\n")
                f.write(f"START={int(start*1000)}\nEND={int(end*1000)}\n")
                f.write(f"title=Глава {i+1}\n")

        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(filelist_path), '-i', str(chapters_metadata_path)]
        if cover_image:
            cmd += ['-i', str(cover_image), '-c:v', 'copy', '-c:a', 'copy', '-disposition:v:0', 'attached_pic', '-map_metadata', '1']
        else:
            cmd += ['-c', 'copy', '-map_metadata', '1']
        if metadata:
            for k, v in metadata.items():
                if v:
                    cmd += ['-metadata', f'{k}={v}']
        else:
            cmd += ['-metadata', f'title={audiobook_path.name}', '-metadata', 'genre=Audiobook', '-metadata', 'media_type=2']
        cmd.append(str(output_file))

        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode == 0:
            print(f"[ok] {output_file}")
            if cleanup_chapters:
                for ch in chapter_files:
                    try:
                        Path(ch).unlink()
                    except OSError:
                        pass
            return True
        else:
            print(r.stderr)
            return False
    finally:
        for p in (filelist_path, chapters_metadata_path):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

def extract_metadata_from_json(folder: Path):
    try:
        json_file = next(folder.glob("*.json"), None)
        if not json_file:
            return None
        info = json.loads(json_file.read_text(encoding='utf-8'))
        book = info.get('audiobook') or info.get('book') or {}
        author = (book.get('authors') or [{}])[0].get('name', '')
        narrator = ', '.join([n.get('name','') for n in (book.get('narrators') or []) if n.get('name')])
        publisher = (book.get('publishers') or [{}])[0].get('name', '')
        meta = {
            'title': book.get('title', folder.name),
            'artist': author or '',
            'album': book.get('title', folder.name),
            'album_artist': author or '',
            'composer': author or '',
            'genre': 'Audiobook',
            'media_type': '2',
            'comment': book.get('annotation', ''),
            'publisher': publisher or '',
            'language': book.get('language', 'ru') or 'ru',
        }
        if narrator:
            meta['performer'] = narrator
        return {k: v for k, v in meta.items() if v}
    except Exception:
        return None

def merge_one(folder: Path, force=False, keep_chapters=False):
    if not folder.is_dir():
        print(f"[skip] {folder} — не каталог")
        return
    output = folder / f"{folder.name}_complete.m4a"
    if output.exists() and not force:
        print(f"[skip] уже существует: {output}")
        return

    metadata = extract_metadata_from_json(folder)
    ok = merge_audiobook_chapters_ffmpeg(folder, output, metadata, cleanup_chapters=not keep_chapters)
    if not ok:
        # fallback pydub — если установлена
        try:
            from pydub import AudioSegment
        except ImportError:
            return
        files = sorted(glob.glob(str(folder / "Глава_*.m4a")),
                       key=lambda x: int(re.search(r'Глава_(\d+)\.m4a', x).group(1)) if re.search(r'Глава_(\d+)\.m4a', x) else 0)
        if not files:
            return
        merged = AudioSegment.empty()
        for f in files:
            merged += AudioSegment.from_file(f)
        merged.export(str(folder / f"{folder.name}.m4a"), format="mp4")
        print(f"[ok] pydub => {folder / f'{folder.name}.m4a'}")

def main():
    ap = argparse.ArgumentParser(description="Merge audiobook chapters into a single file.")
    ap.add_argument("path", nargs='?', default=None, help="Путь к папке аудиокниги (если не задан — пакетный режим)")
    ap.add_argument("--batch", action='store_true', help="Пройти по всем папкам в mybooks/audiobook")
    ap.add_argument("--force", action='store_true', help="Перезаписывать существующие объединённые файлы")
    ap.add_argument("--keep-chapters", action='store_true', help="Не удалять главы после объединения")
    args = ap.parse_args()

    targets = []
    if args.path:
        targets = [Path(args.path)]
    elif args.batch:
        base = Path("mybooks/audiobook")
        if base.exists():
            targets = [p for p in base.iterdir() if p.is_dir()]
    else:
        ap.error("Нужно указать путь или --batch")

    for t in targets:
        merge_one(t, force=args.force, keep_chapters=args.keep_chapters)

if __name__ == '__main__':
    main()
