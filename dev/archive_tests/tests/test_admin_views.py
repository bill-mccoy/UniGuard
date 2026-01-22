import pytest
from types import SimpleNamespace

from cogs.admin import views
from uniguard import config


# Helper fakes
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

class FakeChannel:
    def __init__(self, id, name):
        self.id = id
        self.name = name

class FakeRole:
    def __init__(self, id, name):
        self.id = id
        self.name = name

class FakeGuild:
    def __init__(self, text_channels=None, roles=None):
        self.text_channels = text_channels or []
        self.roles = roles or []
        self._channels = {c.id: c for c in self.text_channels}
        self._roles = {r.id: r for r in self.roles}
    def get_channel(self, cid):
        return self._channels.get(cid)
    def get_role(self, rid):
        return self._roles.get(rid)


@pytest.mark.asyncio
async def test_config_channel_select_view(monkeypatch):
    ch = FakeChannel(10, "general")
    guild = FakeGuild(text_channels=[ch])
    cog = SimpleNamespace()

    calls = {}
    def fake_set(path, value):
        calls['last'] = (path, value)
        return True
    monkeypatch.setattr(config, 'set', fake_set)

    view = views.ConfigChannelSelectView(cog, "channels.verification", guild, "Verification Channel")
    # Ensure select was added
    assert any(isinstance(i, object) for i in view.children)

    inter = DummyInteraction(guild=guild, data={'values': [str(ch.id)]})
    await view.on_select(inter)
    assert calls['last'] == ("channels.verification", ch.id)
    assert any("actualizado" in (m[0] or "") for m in inter.response.sent)


@pytest.mark.asyncio
async def test_config_role_select_view(monkeypatch):
    r = FakeRole(20, "Student")
    # include an @everyone placeholder at index 0
    guild = FakeGuild(roles=[FakeRole(0, "@everyone"), r])
    cog = SimpleNamespace()

    calls = {}
    def fake_set(path, value):
        calls['last'] = (path, value)
        return True
    monkeypatch.setattr(config, 'set', fake_set)

    view = views.ConfigRoleSelectView(cog, "roles.verified", guild, "Verified Role")

    inter = DummyInteraction(guild=guild, data={'values': [str(r.id)]})
    await view.on_select(inter)
    assert calls['last'] == ("roles.verified", r.id)
    assert any("actualizado" in (m[0] or "") for m in inter.response.sent)


@pytest.mark.asyncio
async def test_select_user_callback(monkeypatch):
    # student row: email, uid, user, type, sponsor, r_name
    rows = [("e@x.com", 101, "UserA", 'student', None, "RealA"), ("g@x.com", 202, "GuestB", 'guest', 101, "Sponsor Name")]
    called = {'render': False}
    async def fake_render_panel(interaction):
        called['render'] = True
    cog = SimpleNamespace(render_panel=fake_render_panel, selected_uid=None, mode=None)

    select = views.SelectUser(cog, rows)
    # Simulate selection
    select._values = [str(101)]
    inter = DummyInteraction()
    await select.callback(inter)

    assert cog.selected_uid == '101'
    assert cog.mode == 'detail'
    assert called['render'] is True


@pytest.mark.asyncio
async def test_list_view_navigation_and_search(monkeypatch):
    # setup cog
    called = {'render': 0}
    async def fake_render_panel(interaction):
        called['render'] += 1
    cog = SimpleNamespace(render_panel=fake_render_panel, page=1, query="something")

    rows = []
    view = views.ListView(cog, rows, has_prev=True, has_next=True)

    # prev
    inter_prev = DummyInteraction()
    await view.prev_cb(inter_prev)
    assert cog.page == 0
    assert called['render'] == 1

    # next
    await view.next_cb(DummyInteraction())
    assert cog.page == 1
    assert called['render'] == 2

    # reload
    await view.reload_cb(DummyInteraction())
    assert called['render'] == 3

    # clear
    inter_clear = DummyInteraction()
    cog.query = "xyz"
    cog.page = 5
    await view.clear_cb(inter_clear)
    assert cog.query == ""
    assert cog.page == 0

    # search as non-admin should be blocked
    non_admin_user = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=False))
    inter_search = DummyInteraction(user=non_admin_user)
    await view.search_cb(inter_search)
    assert any("Solo administradores" in (m[0] or "") for m in inter_search.response.sent)

    # search as admin should call send_modal
    admin_user = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True))
    inter_search_admin = DummyInteraction(user=admin_user)
    await view.search_cb(inter_search_admin)
    assert inter_search_admin.response.modal is not None


@pytest.mark.asyncio
async def test_add_student_and_guest_buttons(monkeypatch):
    cog = SimpleNamespace()
    view = views.ListView(cog, [], has_prev=False, has_next=False)

    # non-admin cannot add student
    non_admin = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=False))
    inter1 = DummyInteraction(user=non_admin)
    await view.add_student_cb(inter1)
    assert any("Solo administradores" in (m[0] or "") for m in inter1.response.sent)

    # admin can open modal (we check that response.send_modal got called)
    admin = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True))
    inter2 = DummyInteraction(user=admin)
    await view.add_student_cb(inter2)
    assert inter2.response.modal is not None

    # add_guest_cb opens sponsor search modal when admin
    inter3 = DummyInteraction(user=admin)
    await view.add_guest_cb(inter3)
    assert inter3.response.modal is not None
