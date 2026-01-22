from cogs.admin.cog import AdminPanelCog
from uniguard import config

class FakeGuild:
    def __init__(self, id):
        self.id = id


def test_get_language_message_system_default(monkeypatch):
    cog = AdminPanelCog(None)
    config.set('system.language', 'es')
    # ensure no guild override
    config.set('guilds.999.language', None)
    guild = FakeGuild(999)
    msg = cog._get_language_message(guild)
    assert 'Idioma del sistema' in msg or 'System language' in msg


def test_get_language_message_with_override(monkeypatch):
    cog = AdminPanelCog(None)
    config.set('system.language', 'es')
    # set guild override
    config.set('guilds.999.language', 'en')
    guild = FakeGuild(999)
    msg = cog._get_language_message(guild)
    assert 'Idioma del servidor:' in msg or 'Server language' in msg
    # cleanup
    config.set('guilds.999.language', None)
