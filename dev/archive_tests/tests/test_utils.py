from uniguard.utils import generate_verification_code, hash_code, validate_minecraft_username, FACULTIES, validate_university_email, set_allowed_email_domains


def test_generate_code_length():
    code = generate_verification_code(6)
    assert isinstance(code, str)
    assert len(code) == 6


def test_hash_code_consistency():
    a = hash_code("SOMESECRET")
    b = hash_code("SOMESECRET")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 10


def test_validate_mc_username_valid():
    assert validate_minecraft_username("Player123")
    assert validate_minecraft_username("abc_def")


def test_validate_mc_username_invalid():
    assert not validate_minecraft_username("ab")  # too short
    assert not validate_minecraft_username("invalid name")


def test_faculties_structure():
    assert isinstance(FACULTIES, dict)
    assert "Ciencias" in FACULTIES
    assert isinstance(FACULTIES["Ciencias"], dict)


def test_validate_university_email_default_and_config(tmp_path):
    from uniguard import config as _config_module

    # Use a temporary file for config and set a known starting state to avoid test order issues
    tmp_file = tmp_path / "email_cfg.json"
    old_file = _config_module.CONFIG_FILE
    try:
        _config_module.CONFIG_FILE = str(tmp_file)
        _config_module._config = None
        _config_module.load_config()

        # Ensure defaults are set and applied
        set_allowed_email_domains(['pucv.cl'], allow_subdomains=True)
        assert validate_university_email('user@pucv.cl')
        assert validate_university_email('user@mail.pucv.cl')

        # Change allowed domains to a custom one (persisted via config)
        set_allowed_email_domains(['example.edu'], allow_subdomains=False)
        # verify persisted in config
        assert _config_module.get('emails.allowed_domains') == ['example.edu']
        assert _config_module.get('emails.allow_subdomains') is False

        assert validate_university_email('user@example.edu')
        assert not validate_university_email('user@mail.example.edu')
        # Add subdomain support and check again
        set_allowed_email_domains(['example.edu'], allow_subdomains=True)
        assert validate_university_email('user@mail.example.edu')
    finally:
        # restore global config path
        _config_module.CONFIG_FILE = old_file
        _config_module._config = None
