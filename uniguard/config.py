"""
Configuration manager for UniGuard (packaged under `uniguard`).
"""

import json
import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("uniguard.config")

CONFIG_FILE = "config.json"

# Default configuration
DEFAULT_CONFIG = {
    "roles": {
        "verified": 0,
        "not_verified": 0,
        "guest": 0
    },
    "limits": {
        "max_guests_per_sponsor": 1,
        "verification_max_attempts": 3
    },
    "channels": {
        "verification": 0,
        "admin": 0,
        "log": 0
    },
    "system": {
        "enable_status_msg": True,
        "enable_log_panel": False,
        "status_interval": 300,
        "db_sync_interval": 300,
        "db_retry_attempts": 3,
        "db_retry_backoff_base": 1.0,
        "db_retry_backoff_factor": 2.0,
        "db_warning_interval": 300,
        "language": "es"
    },
    "emails": {
        "allowed_domains": ["pucv.cl"],
        "allow_subdomains": True
    }
}

_config: Optional[Dict[str, Any]] = None


def load_config() -> Dict[str, Any]:
    """Load configuration from file, create if doesn't exist."""
    global _config
    
    if _config is not None:
        return _config
    
    if not os.path.exists(CONFIG_FILE):
        logger.warning(f"{CONFIG_FILE} not found, creating with defaults...")
        _config = dict(DEFAULT_CONFIG)
        save_config(_config)
    else:
        try:
            with open(CONFIG_FILE, 'r') as f:
                _config = json.load(f)
            logger.info(f"Configuration loaded from {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            _config = dict(DEFAULT_CONFIG)
    
    if _config is None:
        _config = dict(DEFAULT_CONFIG)
    
    return _config


def save_config(config: Dict[str, Any]) -> bool:
    global _config
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        _config = config
        logger.info("Configuration saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False


def get(path: str, default: Any = None) -> Any:
    config = load_config()
    keys = path.split(".")
    value = config
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


def set(path: str, value: Any) -> bool:
    config = load_config()
    keys = path.split(".")
    current = config
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
    return save_config(config)


def get_all() -> Dict[str, Any]:
    return load_config()
