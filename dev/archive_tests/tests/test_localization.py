import pytest
from uniguard import localization
from uniguard import config


def test_translations_and_config_toggle(tmp_path):
    # Use temp config so test is isolated
    old = config.CONFIG_FILE
    tmp_file = tmp_path / "cfg_loc.json"
    try:
        config.CONFIG_FILE = str(tmp_file)
        config._config = None
        config.load_config()

        # default language is 'es'
        assert localization.get_lang() == 'es'
        assert 'Error inicializando' in localization.t('db.pool_failed', error='X')

        # set to english
        localization.set_language('en')
        assert localization.get_lang() == 'en'
        assert 'Database initialization' in localization.t('db.pool_failed', error='X')
    finally:
        config.CONFIG_FILE = old
        config._config = None
