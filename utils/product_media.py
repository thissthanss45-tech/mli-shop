from __future__ import annotations

from aiogram.utils.media_group import MediaGroupBuilder


def normalize_media_type(value: str | None) -> str:
    return "video" if (value or "").strip().lower() == "video" else "photo"


def first_photo_media(items) -> object | None:
    for item in items or []:
        if normalize_media_type(getattr(item, "media_type", None)) == "photo":
            return item
    return None


def first_media_item(items) -> object | None:
    for item in items or []:
        return item
    return None


def describe_media_item(item, index: int) -> str:
    media_type = normalize_media_type(getattr(item, "media_type", None))
    label = "Видео" if media_type == "video" else "Фото"
    return f"{index}. {label}"


def build_product_media_group(items, caption: str) -> MediaGroupBuilder:
    album = MediaGroupBuilder(caption=caption)
    for item in items or []:
        media_type = normalize_media_type(getattr(item, "media_type", None))
        if media_type == "video":
            album.add_video(media=getattr(item, "file_id"))
        else:
            album.add_photo(media=getattr(item, "file_id"))
    return album