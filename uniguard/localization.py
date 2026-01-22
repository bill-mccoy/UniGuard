"""Simple localization helper for UniGuard.
Provides translation strings for supported languages and a convenience `t()`
function to fetch formatted messages using the current language from config.
"""
from typing import Any, Optional, Union
from uniguard import config
import os
import json
import glob

# Minimal translation catalog: moved to JSON files under /locales.
# TRANSLATIONS will be populated at runtime by _load_locales() reading those files.
TRANSLATIONS = {}

LOCALES_DIR = os.path.join(os.path.dirname(__file__), '..', 'locales')  # json files with locale catalogs


def _load_locales():
    # Load JSON locale files from LOCALES_DIR for easier contributions
    if not os.path.isdir(LOCALES_DIR):
        return
    for path in glob.glob(os.path.join(LOCALES_DIR, '*.json')):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                # data is expected to be { lang_code: { key: value, ... } }
                for lang, catalog in data.items():
                    if lang not in TRANSLATIONS:
                        TRANSLATIONS[lang] = {}
                    TRANSLATIONS[lang].update(catalog)
        except Exception:
            # ignore malformed locale files
            continue

# Load locales on import
_load_locales()

_load_locales()



def get_lang() -> str:
    return config.get("system.language", "es") or "es"


def get_guild_lang(guild_id: Optional[Union[int, str]] = None) -> Optional[str]:
    """Return the language code configured for a guild or None if not set."""
    if not guild_id:
        return None
    return config.get(f"guilds.{guild_id}.language", None)


def t(key: str, guild: Optional[Union[int, str]] = None, **kwargs: Any) -> str:
    """Return the translated string for `key` formatted with `kwargs`.

    If `guild` is provided (guild id or str), attempt to use the guild's language
    override stored at `guilds.<id>.language`. Falls back to system language and
    then to English.
    """
    # Ensure locales are loaded (file-based locales may be added after import time)
    try:
        _load_locales()
    except Exception:
        pass

    # Determine language priority: guild specific -> system -> en
    lang = None
    try:
        if guild is not None:
            lang = get_guild_lang(guild)
    except Exception:
        lang = None

    if not lang:
        lang = get_lang()
    catalog = TRANSLATIONS.get(lang, {})
    template = catalog.get(key) or TRANSLATIONS.get("en", {}).get(key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def translate_for_lang(key: str, lang: Optional[str], **kwargs: Any) -> str:
    """Return translation for a given language code, falling back to English and then to key.

    This bypasses guild detection and forces the given language (useful for ensuring
    consistent language selection when handling an interaction).
    """
    if lang is None:
        # default behavior
        return t(key, **kwargs)
    catalog = TRANSLATIONS.get(lang, {})
    template = catalog.get(key) or TRANSLATIONS.get("en", {}).get(key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def set_language(lang: str) -> None:
    """Set language in config. Expects 'es' or 'en' (or any supported code)."""
    config.set("system.language", lang)