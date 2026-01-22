import json
import os

# Try archive copy first, otherwise fall back to repo-level uniguard/data/faculties.json
P = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uniguard", "data", "faculties.json")
if not os.path.isfile(P):
    REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    P = os.path.join(REPO_ROOT, 'uniguard', 'data', 'faculties.json')


def test_faculties_loadable_and_structure():
    with open(P, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    assert isinstance(data, dict)
    # basic expected categories
    for expected in ["Ingeniería", "Ciencias", "Filosofía y Educación"]:
        assert expected in data, f"Expected faculty '{expected}' in faculties.json"
    # codes must be unique
    codes = []
    for cat, items in data.items():
        assert isinstance(items, dict), "Each faculty must map to a dict of display->code"
        for display, code in items.items():
            assert isinstance(display, str) and display, "display name must be a non-empty string"
            assert isinstance(code, str) and code, "code must be a non-empty string"
            codes.append(code)
    assert len(codes) == len(set(codes)), "Duplicate career codes found in faculties.json"
