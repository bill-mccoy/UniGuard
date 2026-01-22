# Helpers and small utilities for admin panel
PAGE_SIZE = 8


def _safe_lower(s) -> str:
    return str(s or "").strip().lower()


def _fmt_user_line(row) -> str:
    try:
        email, user_id, username, u_type, sponsor, real_name = row
    except ValueError:
        from uniguard.localization import t
        return t('errors.bad_data_structure')

    username_display = f"`{username}`" if username else "—"
    
    if u_type == 'guest':
        return f"🤝 **{real_name or 'Invitado'}** ({username_display})\n   ↳ ID: `{user_id}` | Padrino: `{sponsor}`"
    else:
        return f"🎓 **Alumno** ({username_display})\n   ↳ ID: `{user_id}` | 📧 `{email}`"


def _filter_rows(rows, query: str):
    q = _safe_lower(query)
    if not q:
        return rows
    
    filtered = []
    for row in rows:
        # Convierte toda la fila a string y busca coincidencias
        full_text = " ".join([str(x) for x in row if x])
        if q in _safe_lower(full_text):
            filtered.append(row)
    return filtered


def _slice_page(rows, page: int):
    total = len(rows)
    max_page = max(0, (total - 1) // PAGE_SIZE)
    page = max(0, min(page, max_page))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    return rows[start:end], (page > 0), (end < total), page + 1, max_page + 1
