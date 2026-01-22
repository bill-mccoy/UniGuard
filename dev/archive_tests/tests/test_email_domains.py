from uniguard import utils as u
from uniguard import config as cfg


def test_default_domains_valid():
    # default from config should accept pucv.cl and mail.pucv.cl
    u.reload_email_domains_from_config()
    assert u.validate_university_email('user@pucv.cl')
    assert u.validate_university_email('user@mail.pucv.cl')


def test_set_allowed_domains_persistence(tmp_path):
    # use temporary config file to avoid clobbering user's real config
    old_file = cfg.CONFIG_FILE
    try:
        cfg.CONFIG_FILE = str(tmp_path / "cfg.json")
        cfg._config = None
        cfg.load_config()

        # set to example.edu without subdomains
        u.set_allowed_email_domains(['example.edu'], allow_subdomains=False)
        domains, allow = u.get_allowed_email_domains()
        assert domains == ['example.edu']
        assert allow is False

        assert u.validate_university_email('user@example.edu')
        assert not u.validate_university_email('user@mail.example.edu')

        # enable subdomains and check again
        u.set_allowed_email_domains(['example.edu'], allow_subdomains=True)
        domains, allow = u.get_allowed_email_domains()
        assert allow is True
        assert u.validate_university_email('user@mail.example.edu')
    finally:
        cfg.CONFIG_FILE = old_file
        cfg._config = None


def test_add_domain_preserves_existing(tmp_path):
    old_file = cfg.CONFIG_FILE
    try:
        cfg.CONFIG_FILE = str(tmp_path / "cfg2.json")
        cfg._config = None
        cfg.load_config()

        u.set_allowed_email_domains(['one.edu'], allow_subdomains=False)
        u.add_allowed_email_domain('two.edu')
        domains, allow = u.get_allowed_email_domains()
        assert 'one.edu' in domains and 'two.edu' in domains
    finally:
        cfg.CONFIG_FILE = old_file
        cfg._config = None
