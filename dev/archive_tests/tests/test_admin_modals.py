import pytest
import asyncio
from types import SimpleNamespace

import discord

from cogs.admin import modals
from uniguard import db, config


# --- Helper mocks ---
class DummyResponse:
    def __init__(self):
        self.sent = []
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

class DummyFollowup(DummyResponse):
    pass

class DummyInteraction:
    def __init__(self, guild=None, data=None):
        self.guild = guild
        self.data = data or {}
        self.response = DummyResponse()
        self.followup = DummyFollowup()

    async def wait_until(self):
        await asyncio.sleep(0)


class FakeMember:
    def __init__(self, id, name, display_name=None):
        self.id = id
        self.name = name
        self.display_name = display_name or name

class FakeGuild:
    def __init__(self, members=None):
        self.members = members or []
        self._members_map = {m.id: m for m in self.members}
    def get_member(self, uid):
        return self._members_map.get(uid)
    async def fetch_member(self, uid):
        # Simulate fetch by returning None so callers must handle NotFound
        raise discord.NotFound("")


# --- Tests ---


@pytest.mark.asyncio
async def test_search_user_modal_title_and_placeholder():
    # student
    sm = modals.SearchUserModal(cog=None, user_type="student", selected_callback=None)
    assert "Alumno" in sm.title
    assert "alumno" in sm.query.placeholder.lower()

    # sponsor
    sm2 = modals.SearchUserModal(cog=None, user_type="sponsor", selected_callback=None)
    assert "Padrino" in sm2.title
    assert "padrino" in sm2.query.placeholder.lower()

    # guest
    sm3 = modals.SearchUserModal(cog=None, user_type="guest", selected_callback=None)
    assert "Invitado" in sm3.title
    assert "invitado" in sm3.query.placeholder.lower()


@pytest.mark.asyncio
async def test_search_modal_empty_query(monkeypatch):
    class DummyCog:
        def __init__(self):
            self.query = None
            self.page = None
        async def render_panel(self, interaction):
            raise AssertionError("Should not call render_panel for empty query")

    cog = DummyCog()
    modal = modals.SearchModal(cog)
    modal.query._value = ""  # empty (TextInput.value is read-only, set private _value)

    interaction = DummyInteraction()
    await modal.on_submit(interaction)

    # Should have sent an ephemeral message telling to write something
    assert any("Debes escribir" in (m[0] or "") for m in interaction.response.sent)


@pytest.mark.asyncio
async def test_add_guest_modal_success(monkeypatch):
    sponsor = FakeMember(1, "sponsor")
    guest = FakeMember(2, "guest")
    guild = FakeGuild(members=[sponsor, guest])

    # monkeypatch DB and cog methods
    async def fake_add_guest_user(uid, mc, real_name, sponsor_id):
        return True, "Invitado agregado"
    monkeypatch.setattr(db, 'add_guest_user', fake_add_guest_user)

    async def fake_manage_discord_user(guild, user_id, action, mc_name=None):
        return "Discord log"
    called = {'render': False}
    async def fake_render_panel(interaction):
        called['render'] = True

    cog = SimpleNamespace(manage_discord_user=fake_manage_discord_user, render_panel=fake_render_panel)

    modal = modals.AddGuestModal(cog, sponsor_user=sponsor, guest_user=guest)
    modal.guest_mc._value = "GuestMC"
    modal.real_name._value = "Real Name"

    interaction = DummyInteraction(guild=guild)
    await modal.on_submit(interaction)

    # Should have sent success message via response
    assert any("Invitado agregado" in (m[0] or "") for m in interaction.response.sent)
    assert called['render'] is True


@pytest.mark.asyncio
async def test_add_guest_modal_checks_missing_sponsor(monkeypatch):
    sponsor = FakeMember(1, "sponsor")
    guest = FakeMember(2, "guest")
    # Guild only has guest (sponsor removed)
    guild = FakeGuild(members=[guest])

    modal = modals.AddGuestModal(SimpleNamespace(), sponsor_user=sponsor, guest_user=guest)
    modal.guest_mc._value = "GuestMC"
    modal.real_name._value = "Real Name"

    interaction = DummyInteraction(guild=guild)
    await modal.on_submit(interaction)

    assert any("padrino" in (m[0] or "").lower() for m in interaction.response.sent)


@pytest.mark.asyncio
async def test_confirm_delete_modal_cancel(monkeypatch):
    cog = SimpleNamespace(manage_discord_user=lambda *a, **k: "log", render_panel=lambda *a, **k: None)
    modal = modals.ConfirmDeleteModal(cog, uid=123, user_display="User#123")
    modal.confirmation._value = "NO"

    interaction = DummyInteraction(guild=FakeGuild(members=[]))
    await modal.on_submit(interaction)

    assert any("Cancelado" in (m[0] or "") for m in interaction.response.sent)


@pytest.mark.asyncio
async def test_config_number_modal_valid_and_invalid(monkeypatch):
    # Replace config.set to observe calls
    calls = {}
    def fake_set(path, value):
        calls['last'] = (path, value)
        return True
    monkeypatch.setattr(config, 'set', fake_set)

    cog = SimpleNamespace()
    modal = modals.ConfigNumberModal(cog, "limits.max_guests_per_sponsor", "Max Guests")

    # Invalid input
    modal.value_input._value = "not-a-number"
    interaction = DummyInteraction()
    await modal.on_submit(interaction)
    assert any("debe ser un número" in (m[0] or "") for m in interaction.response.sent)

    # Valid input
    modal.value_input._value = "3"
    interaction2 = DummyInteraction()
    await modal.on_submit(interaction2)
    assert calls['last'] == ("limits.max_guests_per_sponsor", 3)
    assert any("actualizado" in (m[0] or "") for m in interaction2.response.sent)
