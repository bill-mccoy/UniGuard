from cogs.verification import FacultySelect
from uniguard.utils import FACULTIES


def test_faculty_select_has_expected_options():
    fs = FacultySelect(None, 123)
    # Discord limits selects to 25 options, so expect min(len(FACULTIES), 25)
    expected = min(len(FACULTIES), 25)
    assert len(fs.options) == expected
    # ensure each option value matches a faculty key
    vals = {opt.value for opt in fs.options}
    assert vals.issubset(set(FACULTIES.keys()))
