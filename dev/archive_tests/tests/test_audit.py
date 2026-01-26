import os
from uniguard import audit


def test_append_and_export_json_and_csv(tmp_path):
    # use a temporary audit file
    try:
        tmpfile = str(tmp_path / 'audit_test.log')
        audit.AUDIT_FILE = tmpfile
        # append some entries
        audit.append_entry('test_action', admin_id=1, admin_mention='@Admin', user_id=2, user_repr='@User', guild_id=123, details={'k': 'v'})
        audit.append_entry('test_action2', admin_id=1, admin_mention='@Admin', user_id=3, user_repr='@User3', guild_id=123, details={'k2': 'v2'})

        entries = audit.read_entries()
        assert len(entries) == 2

        json_path = audit.export_json(str(tmp_path / 'out.json'))
        assert os.path.exists(json_path)
        csv_path = audit.export_csv(str(tmp_path / 'out.csv'))
        assert os.path.exists(csv_path)
    finally:
        audit.AUDIT_FILE = os.path.join(os.path.dirname(audit.__file__), '..', 'data', 'audit.log')