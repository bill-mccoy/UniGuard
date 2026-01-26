import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

AUDIT_FILE = os.environ.get('UNIGUARD_AUDIT_FILE', os.path.join(os.path.dirname(__file__), '..', 'data', 'audit.log'))
_dir_lock = threading.RLock()
_file_lock = threading.RLock()

os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def append_entry(action: str, admin_id: Optional[int] = None, admin_mention: Optional[str] = None,
                 user_id: Optional[int] = None, user_repr: Optional[str] = None, guild_id: Optional[int] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
    entry = {
        'timestamp': _now_iso(),
        'action': action,
        'admin_id': admin_id,
        'admin_mention': admin_mention,
        'user_id': user_id,
        'user': user_repr,
        'guild_id': guild_id,
        'details': details or {}
    }
    line = json.dumps(entry, ensure_ascii=False)
    with _file_lock:
        with open(AUDIT_FILE, 'a', encoding='utf-8') as fh:
            fh.write(line + "\n")


def read_entries() -> List[Dict[str, Any]]:
    if not os.path.exists(AUDIT_FILE):
        return []
    out = []
    with _file_lock:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    # skip malformed
                    continue
    return out


def export_json(path: Optional[str] = None) -> str:
    entries = read_entries()
    if path:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
        return path
    else:
        tmp = AUDIT_FILE + '.export.json'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
        return tmp


def export_csv(path: Optional[str] = None) -> str:
    import csv
    entries = read_entries()
    if not entries:
        tmp = (path or AUDIT_FILE + '.export.csv')
        # create empty csv
        with open(tmp, 'w', encoding='utf-8', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(['timestamp', 'action', 'admin_id', 'admin_mention', 'user_id', 'user', 'guild_id', 'details'])
        return tmp

    tmp = path or AUDIT_FILE + '.export.csv'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['timestamp', 'action', 'admin_id', 'admin_mention', 'user_id', 'user', 'guild_id', 'details'])
        for e in entries:
            writer.writerow([e.get('timestamp'), e.get('action'), e.get('admin_id'), e.get('admin_mention'), e.get('user_id'), e.get('user'), e.get('guild_id'), json.dumps(e.get('details') or {})])
    return tmp
