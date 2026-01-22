import json
from uniguard import utils


def test_get_faculties_default():
    f = utils.get_faculties()
    assert isinstance(f, dict)
    # should have at least one known category
    assert any('Ingeniería' in k or 'Ciencias' in k for k in f.keys())


def test_reload_faculties_tmp(tmp_path):
    tmp = tmp_path / 'fac_temp.json'
    data = {"Demo": {"🔧 Test": "TST"}}
    tmp.write_text(json.dumps(data, ensure_ascii=False))

    # reload from temp file
    utils.reload_faculties(str(tmp))
    f = utils.get_faculties()
    assert 'Demo' in f

    # restore original
    utils.reload_faculties()
    f2 = utils.get_faculties()
    assert 'Demo' not in f2
