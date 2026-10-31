"""Конвертация DOCX в Markdown через Pandoc с извлечением изображений."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

from flask import url_for
from werkzeug.utils import secure_filename

from servicesystem.services.audit import unique_filename
from servicesystem.services.storage import get_storage

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def is_pandoc_available() -> bool:
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _pandoc_markdown_format() -> str:
    """Формат Markdown, совместимый с CMS (python-markdown + таблицы)."""
    # Мы используем markdown с отключением всего лишнего:
    # -link_attributes - убирает {width="..."} для изображений
    return "markdown-raw_html-native_divs-native_spans-fenced_divs-bracketed_spans-grid_tables-multiline_tables-link_attributes-header_attributes+pipe_tables"


def normalize_pandoc_markdown(text: str) -> str:
    """Убирает артефакты Pandoc и приводит к виду, удобному для CMS-редактора."""
    if not text:
        return ""

    t = text.replace("\r\n", "\n").replace("\r", "\n")

    # [текст]{.underline} → <u>текст</u>
    t = re.sub(r"\[([^\]]+?)\]\{\.underline\}", r"<u>\1</u>", t)
    t = re.sub(r"\[([^\]]+?)\]\{\.ul\}", r"<u>\1</u>", t)
    t = re.sub(r"\[([^\]]+?)\]\{\.mark\}", r"<mark>\1</mark>", t)
    t = re.sub(r"\[([^\]]+?)\]\{\.underline\s[^}]*\}", r"<u>\1</u>", t)

    # Заголовки / spans с {#id} {.class}
    t = re.sub(r"(^|\s)\{[.#][^}\n]*\}", "", t)
    t = re.sub(r"^(#{1,6}[^\n]*?)\s*\{[^}\n]+\}\s*$", r"\1", t, flags=re.M)

    # Pandoc escaped newlines in tables / soft breaks
    t = re.sub(r"\\\n", "\n", t)

    # Лишние backslash перед пунктуацией, которые мешают в редакторе (кроме спецсимволов, которые мы обрабатываем отдельно)
    t = re.sub(r"\\([\[\]().,;:!?>\-])", r"\1", t)
    
    # Pandoc экранирует решетки (\#), если они не в начале строки, но нам это мешает
    t = re.sub(r"\\#", "#", t)

    # Pandoc иногда экранирует амперсанды в ссылках или тексте, но для markdown это излишне
    t = re.sub(r"\\&", "&", t)
    t = re.sub(r"\\<", "<", t)
    t = re.sub(r"\\>", ">", t)
    t = re.sub(r"\\_", "_", t)
    t = re.sub(r"\\\*", "*", t)
    t = re.sub(r"\\`", "`", t)

    # Убираем HTML-теги <img ...>, которые pandoc генерирует для изображений с заданными размерами,
    # и заменяем их на обычный Markdown (![](src)), так как мы обрабатываем картинки через регулярки
    # Поддерживаем как обычные теги <img ...>, так и самозакрывающиеся <img ... />
    def replace_img_tag(match):
        # Извлекаем src из любой позиции в теге
        img_tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', img_tag)
        if src_match:
            src = src_match.group(1)
            return f"![]({src})"
        return match.group(0)  # Если src не найден, возвращаем как есть
    
    # Ищем все img теги (как самозакрывающиеся, так и обычные)
    t = re.sub(r'<img[^>]*/?>', replace_img_tag, t, flags=re.IGNORECASE)

    # Убираем Pandoc-атрибуты у изображений, например: ![](media/image1.png){width="6.49in" height="4.00in"}
    # Это может мешать замене URL и парсингу
    t = re.sub(r"(!\[[^\]]*\]\([^)]+\))\{[^}]+\}", r"\1", t)

    # Схлопнуть 3+ пустых строк
    t = re.sub(r"\n{3,}", "\n\n", t)

    # Убрать пробелы в конце строк
    t = re.sub(r"[ \t]+\n", "\n", t)

    return t.strip() + ("\n" if t.strip() else "")


def _upload_media_tree(media_root: Path) -> dict[str, str]:
    """Загружает файлы из дерева --extract-media в cms storage. path→url."""
    if not media_root.exists():
        return {}

    storage = get_storage()
    storage.ensure_dir("cms")
    url_map: dict[str, str] = {}

    for path in media_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        try:
            stored = unique_filename(path.name)
            # Чтобы не зависеть от внутренней реализации backend-а (LocalStorageBackend), 
            # используем штатный механизм сохранения через временный объект FileStorage
            from werkzeug.datastructures import FileStorage
            with open(path, "rb") as fh:
                fs = FileStorage(stream=fh, filename=path.name)
                storage.save_file(f"cms/{stored}", fs)
            
            try:
                url = url_for("admin.cms_image_serve", filename=stored)
            except RuntimeError:
                # Fallback для работы скрипта вне контекста веб-запроса (например в CLI-тестах)
                url = f"/admin/cms-images/{stored}"
                
            # Ключи для замены в markdown (имя файла и относительный путь)
            url_map[path.name] = url
            try:
                rel = str(path.relative_to(media_root)).replace("\\", "/")
                url_map[rel] = url
            except ValueError:
                pass
            url_map[str(path).replace("\\", "/")] = url
        except Exception as exc:
            print(f"docx_import: не удалось загрузить {path}: {exc}")

    return url_map


def _rewrite_media_urls(markdown: str, url_map: dict[str, str], media_root: Path) -> str:
    # Даже если url_map пуст, мы должны очистить временные пути
    # if not url_map:
    #     return markdown

    def repl(match: re.Match[str]) -> str:
        alt = match.group(1)
        src = match.group(2).strip()
        
        # Если src обёрнут в <img src="...">, извлечём его оттуда (хотя мы уже заменяем их в normalize)
        if src.startswith("<img"):
            img_match = re.search(r'src="([^"]+)"', src)
            if img_match:
                src = img_match.group(1)
                
        base = os.path.basename(src)
        # pandoc может генерировать как media/image1.png так и сырой путь.
        candidates = [
            src,
            src.replace("\\", "/"),
            base,
            src.lstrip("./"),
            src.split("?")[0], # На случай если добавились параметры ширины/высоты в URL
        ]
        
        # Если src это абсолютный путь извлечения (например /tmp/tmpxxx/media/image1.png), 
        # то мы должны проверять именно по basename
        if "media/" in src:
            candidates.append(src.split("media/")[-1])
        try:
            rel = str((media_root / src).resolve())
            candidates.append(rel.replace("\\", "/"))
        except OSError:
            pass
        for key in candidates:
            if key in url_map:
                return f"![{alt}]({url_map[key]})"
                
        # частичное совпадение по basename
        for map_key, url in url_map.items():
            if map_key.endswith(base) or os.path.basename(map_key) == base:
                return f"![{alt}]({url})"
                    
        # Если ничего не нашли, все равно нужно убрать абсолютный временный путь,
        # иначе картинки в браузере будут битые с путем /tmp/...
        return f"![{alt}]({base})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, markdown)


def convert_docx_to_markdown(
    docx_path: str | Path,
    extract_media: bool = True,
) -> Tuple[str, dict[str, str]]:
    if not is_pandoc_available():
        raise RuntimeError(
            "Pandoc не установлен. Установите пакет pandoc в контейнере/системе."
        )

    docx_path = Path(docx_path)
    if not docx_path.exists():
        raise FileNotFoundError(f"Файл не найден: {docx_path}")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        media_dir = temp_dir_path / "media"

        cmd = [
            "pandoc",
            str(docx_path),
            "-f", "docx",
            "-t", _pandoc_markdown_format(),
            "--wrap=none",
            "--atx-headers",
        ]
        if extract_media:
            cmd.append(f"--extract-media={temp_dir_path}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "неизвестная ошибка").strip()
            raise RuntimeError(f"Ошибка Pandoc: {err}")

        markdown_text = result.stdout or ""
        image_urls: dict[str, str] = {}

        markdown_text = normalize_pandoc_markdown(markdown_text)

        if extract_media:
            image_urls = _upload_media_tree(temp_dir_path)
            markdown_text = _rewrite_media_urls(markdown_text, image_urls, temp_dir_path)

        return markdown_text, image_urls


def convert_docx_file(file_storage) -> Tuple[str, dict]:
    if not file_storage or not file_storage.filename:
        return "", {"success": False, "error": "Файл не загружен"}

    filename = secure_filename(file_storage.filename)
    if not filename.lower().endswith(".docx"):
        # secure_filename может выкинуть не-ascii имя — проверим исходное
        raw = (file_storage.filename or "").lower()
        if not raw.endswith(".docx"):
            return "", {"success": False, "error": "Разрешены только файлы .docx"}
        filename = "import.docx"

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
            temp_path = temp_file.name
            file_storage.save(temp_path)

        try:
            markdown_text, image_urls = convert_docx_to_markdown(
                temp_path, extract_media=True
            )
            if not (markdown_text or "").strip():
                return "", {
                    "success": False,
                    "error": "Pandoc вернул пустой текст. Проверьте содержимое DOCX.",
                }
            return markdown_text, {
                "success": True,
                "images_count": len(set(image_urls.values())),
                "images": list(dict.fromkeys(image_urls.values())),
            }
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    except Exception as e:
        return "", {"success": False, "error": str(e)}
