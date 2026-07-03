# Robbo Obibok v2 — Makefile

.PHONY: install run test lint format build-indexes clean help

SHELL := /bin/bash
VENV  := venv
PYTHON := $(VENV)/bin/python3

help:
	@echo "Robbo Obibok v2 — Makefile"
	@echo ""
	@echo "  make install         # Full installation (venv + deps)"
	@echo "  make run             # Start the bot"
	@echo "  make test            # Run unit tests"
	@echo "  make lint            # Run ruff linter"
	@echo "  make format          # Run ruff formatter"
	@echo "  make build-indexes   # Build all local track indexes"
	@echo "  make clean           # Remove venv, caches, temp files"
	@echo "  make help            # This message"

install: $(VENV)/bin/activate
	@echo "Robbo Obibok v2 ready."

$(VENV)/bin/activate: pyproject.toml
	@echo "Creating Python virtual environment..."
	@python3 -m venv $(VENV)
	@$(VENV)/bin/pip install --quiet --upgrade pip
	@$(VENV)/bin/pip install --quiet -e ".[dev]"
	@touch $(VENV)/bin/activate
	@echo "Virtual environment ready"

run: $(VENV)/bin/activate
	@echo "Starting Robbo Obibok v2..."
	@cd $(CURDIR) && PYTHONPATH=src $(PYTHON) -m robbo_obibok

test: $(VENV)/bin/activate
	@echo "Running tests..."
	@cd $(CURDIR) && PYTHONPATH=src $(PYTHON) -m pytest tests/ -v

lint: $(VENV)/bin/activate
	@echo "Running ruff checks..."
	@cd $(CURDIR) && PYTHONPATH=src $(VENV)/bin/ruff check src/ tests/ scripts/
	@echo "Lint passed"

format: $(VENV)/bin/activate
	@echo "Running ruff formatter..."
	@cd $(CURDIR) && $(VENV)/bin/ruff format src/ tests/ scripts/
	@echo "Format complete"

build-indexes: $(VENV)/bin/activate
	@echo "Building local track indexes..."
	@-$(PYTHON) scripts/build_asma_index.py 2>/dev/null || echo "  ASMA index skipped (no archive)"
	@-$(PYTHON) scripts/build_hvsc_index.py 2>/dev/null || echo "  HVSC index skipped (no archive)"
	@-$(PYTHON) scripts/build_ay_index.py 2>/dev/null || echo "  AY index skipped (no archive)"
	@-$(PYTHON) scripts/build_ym_index.py 2>/dev/null || echo "  YM index skipped (no archive)"
	@-$(PYTHON) scripts/build_tiny_index.py 2>/dev/null || echo "  Tiny index skipped (no archive)"
	@-$(PYTHON) scripts/build_kgen_index.py 2>/dev/null || echo "  KGen index skipped (no archive)"
	@-$(PYTHON) scripts/build_modarchive_index.py 2>/dev/null || echo "  ModArchive index skipped (no archive)"
	@echo "Indexes built"

clean:
	@echo "Cleaning..."
	@rm -rf $(VENV) __pycache__ */__pycache__ .pytest_cache src/__pycache__
	@rm -f *.log *.pid *cache*.json
	@echo "Clean"
