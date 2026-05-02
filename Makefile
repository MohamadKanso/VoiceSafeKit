.PHONY: install test lint demo build

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

lint:
	python3 -m ruff check voicesafekit tests

demo:
	python3 -m voicesafekit check examples/transcripts/password_reset.txt --pretty

build:
	python3 -m build --sdist --wheel

