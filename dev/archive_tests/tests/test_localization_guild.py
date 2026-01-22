import pytest
from uniguard import localization, config


def test_guild_language_override(monkeypatch):
    # Ensure system language default
    config.set('system.language', 'es')
    assert localization.t('verification.dm_sent') == localization.t('verification.dm_sent', guild=None)

    # Set guild override to 'en'
    config.set('guilds.123.language', 'en')
    en_msg = localization.t('verification.dm_sent', guild=123)
    assert 'I\'ve sent you' in en_msg or 'sent you a private message' in en_msg

    # Reset guild override
    config.set('guilds.123.language', None)
    assert localization.t('verification.dm_sent', guild=123) == localization.t('verification.dm_sent')
