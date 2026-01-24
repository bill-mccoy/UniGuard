import pytest
from types import SimpleNamespace
from cogs.admin import modals

class FakeChannel:
    def __init__(self):
        self.sent = []
    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

class DummyResponse:
    def __init__(self):
        self.sent = []
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

class DummyInteraction:
    def __init__(self, guild=None, user=None):
        self.guild = guild
        self.user = user or SimpleNamespace(mention='@Admin#1')
        self.response = DummyResponse()

class FakeGuild:
    def __init__(self):
        pass

@pytest.mark.asyncio
async def test_add_student_logs_to_channel(monkeypatch):
    async def fake_update_or_insert_user(email, uid, mc, career, u_type='student'):
        return True
    monkeypatch.setattr('uniguard.db.update_or_insert_user', fake_update_or_insert_user)

    fake_channel = FakeChannel()
    fake_bot = SimpleNamespace(get_channel=lambda cid: fake_channel, config=SimpleNamespace(get=lambda *a, **k: {'log': 123}))

    async def fake_manage_discord_user(*a, **k):
        return 'log'
    cog = SimpleNamespace(bot=fake_bot, manage_discord_user=fake_manage_discord_user, render_panel=lambda *a, **k: None)
    modal = modals.AddStudentModal(cog, student_user=SimpleNamespace(mention='@User#1', id=9001))
    modal.mc._value = 'Player'
    modal.email._value = 'x@pucv.cl'

    inter = DummyInteraction(guild=FakeGuild(), user=SimpleNamespace(mention='@Admin#1'))
    await modal.on_submit(inter)

    assert fake_channel.sent, "Expected a log message to be sent to the log channel"

@pytest.mark.asyncio
async def test_delete_logs_to_channel(monkeypatch):
    async def fake_full_user_delete(uid):
        return True
    monkeypatch.setattr('uniguard.db.full_user_delete', fake_full_user_delete)

    fake_channel = FakeChannel()
    fake_bot = SimpleNamespace(get_channel=lambda cid: fake_channel, config=SimpleNamespace(get=lambda *a, **k: {'log': 123}))

    async def fake_manage_discord_user(*a, **k):
        return 'log'
    cog = SimpleNamespace(bot=fake_bot, manage_discord_user=fake_manage_discord_user, render_panel=lambda *a, **k: None)

    modal = modals.ConfirmDeleteModal(cog, uid=42, user_display='User#42')
    modal.confirmation._value = 'si'
    inter = DummyInteraction(guild=FakeGuild(), user=SimpleNamespace(mention='@Admin#1'))
    await modal.on_submit(inter)

    assert fake_channel.sent, "Expected a log message to be sent on delete"


@pytest.mark.asyncio
async def test_suspend_logs_to_channel(monkeypatch):
    async def fake_set_suspension_reason(uid, reason):
        return True
    async def fake_set_whitelist_flag(uid, flag):
        return True

    monkeypatch.setattr('uniguard.db.set_suspension_reason', fake_set_suspension_reason)
    monkeypatch.setattr('uniguard.db.set_whitelist_flag', fake_set_whitelist_flag)

    fake_channel = FakeChannel()
    fake_bot = SimpleNamespace(get_channel=lambda cid: fake_channel, config=SimpleNamespace(get=lambda *a, **k: {'log': 123}))
    cog = SimpleNamespace(bot=fake_bot, render_panel=lambda *a, **k: None)

    modal = modals.SuspensionReasonModal(cog, uid=9001)
    modal.reason._value = 'Testing suspension reason'

    inter = DummyInteraction(guild=FakeGuild(), user=SimpleNamespace(mention='@Admin#1'))
    await modal.on_submit(inter)

    assert fake_channel.sent, "Expected a log message to be sent on suspend"