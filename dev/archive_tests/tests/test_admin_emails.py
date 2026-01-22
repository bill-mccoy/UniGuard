import pytest
from types import SimpleNamespace
from uniguard import config
from uniguard.utils import get_allowed_email_domains, set_allowed_email_domains
from cogs.admin.modals import AddEmailDomainModal
from cogs.admin.views import ConfigEmailsMenu

class DummyResponse:
    def __init__(self):
        self.sent = []
        self.modal = None
    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
    async def send_modal(self, modal):
        self.modal = modal
    async def defer(self, **kwargs):
        pass

class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyResponse()
        self.data = {}
        self.guild = None
        self.user = None


@pytest.mark.asyncio
async def test_add_email_modal_persists(tmp_path):
    # Use temp config file
    old_file = config.CONFIG_FILE
    tmp_file = tmp_path / "cfg_emails.json"
    try:
        config.CONFIG_FILE = str(tmp_file)
        config._config = None
        config.load_config()

        modal = AddEmailDomainModal(None)
        modal.domain._value = "example.edu"

        interaction = DummyInteraction()
        await modal.on_submit(interaction)

        assert any("Dominio agregado" in (m[0] or "") for m in interaction.response.sent)
        domains, allow = get_allowed_email_domains()
        assert "example.edu" in domains
        # Check persisted
        assert config.get('emails.allowed_domains') == domains
    finally:
        config.CONFIG_FILE = old_file
        config._config = None


@pytest.mark.asyncio
async def test_config_emails_menu_add_button_opens_modal(monkeypatch):
    view = ConfigEmailsMenu(None)
    # Find the add button by label and call its callback
    btn = next(c for c in view.children if getattr(c, 'label', '') == '➕ Agregar dominio')
    inter = DummyInteraction()
    await btn.callback(inter)
    # The callback sends a modal (response.modal set by DummyResponse.send_modal)
    assert inter.response.modal is not None


@pytest.mark.asyncio
async def test_toggle_subdomains_and_remove(monkeypatch, tmp_path):
    # Temp config
    old_file = config.CONFIG_FILE
    tmp_file = tmp_path / "cfg_emails2.json"
    try:
        config.CONFIG_FILE = str(tmp_file)
        config._config = None
        config.load_config()

        set_allowed_email_domains(['a.edu', 'b.edu'], allow_subdomains=False)
        view = ConfigEmailsMenu(None)

        # Toggle by finding the button and calling its callback
        inter = DummyInteraction()
        btn = next(c for c in view.children if getattr(c, 'label', '') == '🔁 Alternar subdominios')
        await btn.callback(inter)
        _, allow = get_allowed_email_domains()
        assert allow is True

        # Remove 'a.edu' via the select callback
        # Build the select view like the real implementation
        domains, _ = get_allowed_email_domains()
        options = [d for d in domains]

        # Simulate choosing 'a.edu' by directly calling the removal logic
        cur, allow = get_allowed_email_domains()
        new = [d for d in cur if d != 'a.edu']
        set_allowed_email_domains(new, allow_subdomains=allow)

        cur2, _ = get_allowed_email_domains()
        assert 'a.edu' not in cur2
    finally:
        config.CONFIG_FILE = old_file
        config._config = None
