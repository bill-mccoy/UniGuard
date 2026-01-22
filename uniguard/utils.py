# utils.py (packaged under uniguard)
import re
import secrets
import string
import hashlib
import threading
import os
import json
from typing import Dict, Optional

from uniguard import config

# --- Validadores y Helpers ---
def generate_verification_code(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:10]

# Configurable allowed domains for university emails
# Use a lock to protect mutable in-memory state and mirror config persistence
_domains_cfg, _allow_cfg = config.get("emails.allowed_domains", ["pucv.cl"]), config.get("emails.allow_subdomains", True)
_ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in (_domains_cfg or ["pucv.cl"]) if d and isinstance(d, str)]
_ALLOW_SUBDOMAINS = bool(_allow_cfg)
_domains_lock = threading.RLock()


def _load_email_config() -> None:
    """Load domains/flags from `config` into in-memory state (thread-safe)."""
    global _ALLOWED_EMAIL_DOMAINS, _ALLOW_SUBDOMAINS
    try:
        domains_cfg = config.get("emails.allowed_domains", ["pucv.cl"]) or ["pucv.cl"]
        allow_cfg = bool(config.get("emails.allow_subdomains", True))
        with _domains_lock:
            _ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in domains_cfg if d and isinstance(d, str)]
            _ALLOW_SUBDOMAINS = bool(allow_cfg)
    except Exception:
        import logging
        logging.getLogger("uniguard.utils").exception("Failed to load email domains from config")


def _sync_to_config(domains, allow_subdomains: bool):
    """Persist the domains and flag to config.json and sync in-memory state."""
    try:
        # Persist to config first, then update in-memory under lock
        config.set("emails.allowed_domains", domains)
        config.set("emails.allow_subdomains", bool(allow_subdomains))
        with _domains_lock:
            global _ALLOWED_EMAIL_DOMAINS, _ALLOW_SUBDOMAINS
            _ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in domains if d and isinstance(d, str)]
            _ALLOW_SUBDOMAINS = bool(allow_subdomains)
    except Exception:
        # If config persistence fails, keep in-memory state but log via config logger
        import logging
        logging.getLogger("uniguard.utils").exception("Failed to persist email domain configuration")


def set_allowed_email_domains(domains, allow_subdomains: bool = True) -> None:
    """Set the allowed email domains and persist to config.

    - domains: iterable of domain strings like 'pucv.cl' or 'mail.pucv.cl'
    - allow_subdomains: if True, domains like 'pucv.cl' will match 'mail.pucv.cl'
    """
    normalized = [d.strip().lower() for d in domains if d and isinstance(d, str)]
    _sync_to_config(normalized, bool(allow_subdomains))


def add_allowed_email_domain(domain: str) -> None:
    """Add a single allowed domain and persist the change."""
    d = domain.strip().lower()
    if not d:
        return
    with _domains_lock:
        if d not in _ALLOWED_EMAIL_DOMAINS:
            new_list = list(_ALLOWED_EMAIL_DOMAINS) + [d]
            _sync_to_config(new_list, _ALLOW_SUBDOMAINS)


def get_allowed_email_domains():
    """Return (domains_list, allow_subdomains_flag)."""
    with _domains_lock:
        return list(_ALLOWED_EMAIL_DOMAINS), bool(_ALLOW_SUBDOMAINS)


def reload_email_domains_from_config() -> None:
    """Reload in-memory email domain list from `config` (call if config.json changed externally)."""
    _load_email_config()


def validate_university_email(email: str) -> bool:
    """Validate whether an email belongs to allowed university domains.

    Default allows domains configured in `config.json` under `emails.allowed_domains` with the
    subdomain behavior controlled by `emails.allow_subdomains`.
    """
    if not email or '@' not in email:
        return False
    domain = email.strip().split('@', 1)[1].lower()
    with _domains_lock:
        for allowed in _ALLOWED_EMAIL_DOMAINS:
            if _ALLOW_SUBDOMAINS:
                if domain == allowed or domain.endswith('.' + allowed):
                    return True
            else:
                if domain == allowed:
                    return True
    return False

def validate_minecraft_username(username: str) -> bool:
    return re.match(r'^\w{3,16}$', username) is not None

# --- DATOS DE CARRERAS (migrado a JSON para facilitar ediciones por devs) ---

FACULTIES_FILE = os.path.join(os.path.dirname(__file__), 'data', 'faculties.json')

# Fallback default if JSON is missing or malformed (kept intentionally minimal)
DEFAULT_FACULTIES: Dict[str, Dict[str, str]] = {
    "Ingeniería": {
        "🖥️ Ingeniería Informática": "IIN",
        "🛠️ Ingeniería Civil": "ICI"
    }
}


def load_faculties(file_path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Load faculties mapping from JSON file; return DEFAULT_FACULTIES on error."""
    path = file_path or FACULTIES_FILE
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("faculties.json must be a dict of categories -> {display: code}")
            return data
    except Exception:
        import logging
        logging.getLogger('uniguard.utils').exception('Failed to load faculties from %s; using defaults', path)
        return dict(DEFAULT_FACULTIES)


# Public API: FACULTIES is the current mapping, can be reloaded at runtime with `reload_faculties`
FACULTIES: Dict[str, Dict[str, str]] = load_faculties()


def reload_faculties(file_path: Optional[str] = None) -> None:
    """Reload the faculties catalog from disk (optionally specify alternate path for tests)."""
    global FACULTIES
    FACULTIES = load_faculties(file_path)


def get_faculties() -> Dict[str, Dict[str, str]]:
    """Return the current faculties mapping (shallow copy)."""
    return dict(FACULTIES)
