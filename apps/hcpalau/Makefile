PYTHON ?= .venv/bin/python
ifeq ($(wildcard $(PYTHON)),)
PYTHON = python3
endif

.PHONY: install test run migrate seed

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -q
	node --check frontend/app.js

run:
	$(PYTHON) -m uvicorn backend.app.main:app --reload

migrate:
	$(PYTHON) -m alembic upgrade head

seed:
	$(PYTHON) -m backend.seed
