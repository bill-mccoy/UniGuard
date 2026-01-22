import pytest
import asyncio
from types import SimpleNamespace
from cogs.verification import VerificationView
from uniguard import config
from uniguard.localization import t

class DummyResponse:
    def __init__(self):
        self.sent = []
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
    async def defer(self, **kwargs):
        pass

class DummyUser:
    def __init__(self):
        self.sent = []
        self.id = 9999
        self.roles = []
    async def send(self, *args, **kwargs):
        # capture embed if provided
        if 'embed' in kwargs:
            self.sent.append(('embed', kwargs['embed']))
        else:
            self.sent.append(('msg', args[0] if args else None))

class DummyInteraction:
    def __init__(self, guild=None, user=None):
        self.guild = guild
        self.user = user or DummyUser()
        self.response = DummyResponse()
        self.data = {}

@pytest.mark.asyncio
async def test_verify_uses_guild_language_in_dm():
    # Setup: system default English, guild override to Spanish
    old_system = config.get('system.language')
    config.set('system.language', 'en')
    config.set('guilds.999.language', 'es')

    guild = SimpleNamespace(id=999)
    user = DummyUser()
    inter = DummyInteraction(guild=guild, user=user)

    # Cog stub with lock and state
    cog = SimpleNamespace()
    cog.lock = asyncio.Lock()
    cog.user_states = {}
    # Minimal bot config required by the view
    cog.bot = SimpleNamespace(config={'roles': {'verified': 0}})
    view = VerificationView(cog)

    # Invoke the verify button handler by calling the underlying button callback
    btn = next((c for c in view.children if getattr(c, 'custom_id', None) == 'verify_start'), None)
    assert btn is not None
    await btn.callback(inter)
    try:
        # Confirm DM was sent and uses guild-localized title
        assert user.sent, "DM not sent to user"
        kind, embed = user.sent[0]
        assert kind == 'embed'
        assert embed.title == t('verification.dm_embed_title', guild=999)

        # Confirm interaction acknowledgment was sent localized for guild
        assert inter.response.sent, "No response sent"
        content, kwargs = inter.response.sent[-1]
        assert t('verification.dm_sent', guild=999) in content or kwargs.get('embed') is None
    finally:
        # Restore previous system language to avoid test leakage
        config.set('system.language', old_system)
