import pytest
import asyncio
from types import SimpleNamespace

from cogs.admin import modals
from uniguard import db

class DummyResponse:
    def __init__(self):
        self.sent = []
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

class DummyInteraction:
    def __init__(self, guild=None):
        self.guild = guild
        self.response = DummyResponse()

class FakeGuild:
    def __init__(self):
        pass

@pytest.mark.asyncio
async def test_confirm_delete_modal_accepts_variants(monkeypatch):
    # simulate successful DB delete and manage_discord_user
    async def fake_full_user_delete(uid):
        return True
    monkeypatch.setattr(db, 'full_user_delete', fake_full_user_delete)

    async def fake_manage_discord_user(*a, **k):
        return 'log'

    cog = SimpleNamespace(manage_discord_user=fake_manage_discord_user, render_panel=lambda *a, **k: None)
    modal = modals.ConfirmDeleteModal(cog, uid=123, user_display='User#123')

    for val in ['si', 'SI', 'sí', 'S', 'yes', 'Y']:
        modal.confirmation._value = val
        interaction = DummyInteraction(guild=FakeGuild())
        await modal.on_submit(interaction)
        # Should have sent a success message for valid confirmations
        assert any('success' in (m[0] or '').lower() for m in interaction.response.sent)
