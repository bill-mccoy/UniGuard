.PHONY: install dev-install test test-integration

install:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt

dev-install:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt -r dev-requirements.txt

test:
	pytest -q

test-integration:
	RUN_DB_INTEGRATION=1 pytest -q tests/integration
