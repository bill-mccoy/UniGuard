import os
import pytest
from uniguard import db

pytestmark = pytest.mark.skipif(os.getenv('RUN_DB_INTEGRATION') != '1', reason='Integration tests require RUN_DB_INTEGRATION=1 and a running MySQL (see contrib/docker-compose.yml)')


@pytest.mark.asyncio
async def test_db_integration_basic():
    # Expect env vars to be set (docker-compose example provided in repo)
    assert os.getenv('MYSQL_HOST')
    assert os.getenv('MYSQL_USER')
    assert os.getenv('MYSQL_PASS')
    assert os.getenv('MYSQL_DB')

    ok = await db.init_pool(minsize=1, maxsize=2)
    assert ok

    # Ensure tables exist
    await db._ensure_pool_or_log()

    # Insert a student
    ok = await db.update_or_insert_user('int@pucv.cl', 9001, 'IntPlayer', 'TST', u_type='student')
    assert ok
    assert await db.check_existing_user(9001)

    # Add guest sponsored by 9001
    ok, msg = await db.add_guest_user(9002, 'GuestA', 'Guest One', 9001)
    assert ok, msg

    rows = await db.list_verified_players()
    ids = [r[1] for r in rows]
    assert 9001 in ids and 9002 in ids

    # Test whitelist flags and suspension reason
    assert await db.set_whitelist_flag(9001, False)
    assert (await db.get_whitelist_flag(9001)) == 0
    assert await db.set_suspension_reason(9001, 'Testing')
    assert (await db.get_suspension_reason(9001)) == 'Testing'

    # Cleanup
    assert await db.delete_verification(9001)
    assert await db.full_user_delete(9002)
