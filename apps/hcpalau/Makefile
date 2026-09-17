PYTHON ?= .venv/bin/python
ifeq ($(wildcard $(PYTHON)),)
PYTHON = python3
endif

.PHONY: install venv test run migrate seed

venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.txt

install: venv

test:
	$(PYTHON) -m pytest -q
	node --check frontend/app.js

run:
	$(PYTHON) -m uvicorn backend.app.main:app --reload

migrate:
	$(PYTHON) -m alembic upgrade head

seed:
	$(PYTHON) -m backend.seed
