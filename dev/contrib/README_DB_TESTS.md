Running DB integration tests

This project includes optional DB integration tests that exercise `db.py` against a MySQL server.

Quick start (local using docker-compose):

1. Start the test database in `contrib/`:

   docker-compose -f contrib/docker-compose.yml up -d

2. Export environment variables expected by the tests (matching `contrib/docker-compose.yml`):

   export RUN_DB_INTEGRATION=1
   export MYSQL_HOST=127.0.0.1
   export MYSQL_PORT=3306
   export MYSQL_USER=uniguard
   export MYSQL_PASS=uniguard_pass
   export MYSQL_DB=uniguard_test

3. Run only the integration tests (or full tests if you prefer):

   pytest -q tests/integration

Notes:
- The integration tests are skipped by default unless `RUN_DB_INTEGRATION=1` is set.
- Docker must be running and the MySQL service healthy before running the tests.
