from uniguard.utils import FACULTIES


def test_faculties_count_within_discord_limit():
    """Ensure the number of top-level faculties does not exceed Discord's 25 option limit."""
    assert len(FACULTIES) <= 25, f"FACULTIES has {len(FACULTIES)} entries; exceeds Discord select option limit (25)."