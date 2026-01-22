import pytest
from types import SimpleNamespace

from cogs.admin import views
from cogs.verification import VerificationView
from uniguard.localization import t

# Reuse test helpers from existing tests
class DummyResponse:
    def __init__(self):
        self.sent = []
        self.deferred = False
        self.modal = None
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
    async def defer(self, **kwargs):
        self.deferred = True
    async def send_modal(self, modal):
        self.modal = modal

class DummyFollowup(DummyResponse):
    pass

class DummyUser:
    def __init__(self, admin=False):
        self.guild_permissions = SimpleNamespace(administrator=admin)
        self.id = 123

class DummyInteraction:
    def __init__(self, guild=None, user=None, data=None):
        self.guild = guild
        self.user = user or DummyUser(admin=False)
        self.data = data or {}
        self.response = DummyResponse()
        self.followup = DummyFollowup()

class FakeGuild:
    def __init__(self, text_channels=None, roles=None):
        self.text_channels = text_channels or []
        self.roles = roles or []


@pytest.mark.asyncio
async def test_config_menu_embed_localized():
    cog = SimpleNamespace()
    view = views.ListView(cog, [], has_prev=False, has_next=False)
    admin_user = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True))
    inter = DummyInteraction(user=admin_user, guild=FakeGuild())

    await view.config_cb(inter)

    # response sent an embed
    assert inter.response.sent, "No response sent"
    _, kwargs = inter.response.sent[-1]
    embed = kwargs.get('embed')
    assert embed is not None
    assert embed.title == t('config.menu_title')
    assert t('config.menu_description') in embed.description


@pytest.mark.asyncio
async def test_verification_button_label_localized():
    # Ensure a deterministic system language for this test
    from uniguard import config as _cfg
    old = _cfg.get('system.language')
    try:
        _cfg.set('system.language', 'es')
        # instantiate the view inside an event loop
        view = VerificationView(None)
        btn = next((c for c in view.children if getattr(c, 'custom_id', None) == 'verify_start'), None)
        assert btn is not None
        assert btn.label == t('verification.start_button')
    finally:
        _cfg.set('system.language', old)

