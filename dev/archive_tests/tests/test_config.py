from uniguard import config


def test_config_get_set_tmp(tmp_path):
    tmp_file = tmp_path / "cfg_test.json"
    # monkeypatch CONFIG_FILE
    old = config.CONFIG_FILE
    config.CONFIG_FILE = str(tmp_file)

    # Ensure starting fresh
    if tmp_file.exists():
        tmp_file.unlink()

    # Reset in-memory cache so load_config uses the temporary CONFIG_FILE
    config._config = None
    c = config.load_config()
    assert isinstance(c, dict)

    # set a value and check persistence
    ok = config.set("test.newvalue", 42)
    assert ok
    _ = config.load_config()
    assert config.get("test.newvalue") == 42

    # Ensure channels.log exists in defaults
    cfg = config.load_config()
    assert 'channels' in cfg
    assert 'log' in cfg['channels']

    # cleanup
    config.CONFIG_FILE = old
    try:
        if tmp_file.exists():
            tmp_file.unlink()
    except Exception:
        pass
