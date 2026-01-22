import pytest
from cogs.admin.helpers import _safe_lower, _fmt_user_line, _filter_rows, _slice_page


def test_safe_lower():
    assert _safe_lower(' AbC ') == 'abc'
    assert _safe_lower(None) == ''


def test_fmt_user_line_student():
    row = ('email@mail.pucv.cl', 1234, 'Player', 'student', None, None)
    s = _fmt_user_line(row)
    assert 'Alumno' in s
    assert 'email@mail.pucv.cl' in s


def test_fmt_user_line_guest():
    row = (None, 2345, 'GuestName', 'guest', 1111, 'Real Guest')
    s = _fmt_user_line(row)
    assert 'Real Guest' in s
    assert 'GuestName' in s
    assert 'Padrino' in s


def test_filter_and_slice():
    rows = [
        ('a@mail', 1, 'A', 'student', None, None),
        ('b@mail', 2, 'B', 'guest', 1, 'B Real'),
        ('c@mail', 3, 'C', 'student', None, None),
    ]
    filtered = _filter_rows(rows, 'b')
    assert len(filtered) == 1

    page_rows, has_prev, has_next, cur_p, tot_p = _slice_page(rows, 0)
    assert len(page_rows) >= 1
    assert cur_p == 1
