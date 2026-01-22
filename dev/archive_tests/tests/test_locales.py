import json
import os
import glob

ROOT = os.path.dirname(os.path.dirname(__file__))
LOCALES_DIR = os.path.join(ROOT, "locales")

ESSENTIAL_KEYS = {
    "verification.dm_embed_title",
    "verification.dm_embed_desc",
    "verification.dm_sent",
    "verification.dm_forbidden",
    "verification.dm_forbidden_ephemeral",
    "verification.select_career_placeholder",
    "verification.select_faculty_placeholder",
    "verification.page_info",
}


def _flatten_keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out |= _flatten_keys(v, full)
        else:
            out.add(full)
    return out


def test_locales_parse_and_lang_key():
    files = glob.glob(os.path.join(LOCALES_DIR, "*.json"))
    assert files, "No locale files found in locales/"
    for p in files:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # top-level should be a dict with a language code key matching filename
        assert isinstance(data, dict)
        lang = os.path.splitext(os.path.basename(p))[0]
        assert lang in data, f"Expected top-level language key '{lang}' in {p}"


def test_essential_locale_keys_present():
    # ensure essential keys are present in all locales
    files = glob.glob(os.path.join(LOCALES_DIR, "*.json"))
    for p in files:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        lang = os.path.splitext(os.path.basename(p))[0]
        flat = _flatten_keys(data.get(lang, {}))
        missing = ESSENTIAL_KEYS - flat
        assert not missing, f"Locale '{lang}' is missing keys: {sorted(missing)}"


def test_locales_key_coverage():
    # English should be the superset of keys (source of truth)
    files = glob.glob(os.path.join(LOCALES_DIR, "*.json"))
    catalogs = {}
    for p in files:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        lang = os.path.splitext(os.path.basename(p))[0]
        catalogs[lang] = _flatten_keys(data.get(lang, {}))

    if 'en' in catalogs:
        en_keys = catalogs['en']
        for lang, keys in catalogs.items():
            missing = en_keys - keys
            assert not missing, f"Locale '{lang}' is missing keys present in 'en': {sorted(missing)[:10]}"
