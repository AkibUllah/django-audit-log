.PHONY: install test lint fmt build example-migrate example-run example-seed

PY ?= .venv/bin/python

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

build:
	$(PY) -m pip install --quiet build
	$(PY) -m build

example-migrate:
	cd example && ../$(PY) manage.py migrate

example-seed:
	cd example && ../$(PY) manage.py seed_shop

example-run:
	cd example && ../$(PY) manage.py runserver 0.0.0.0:8000
