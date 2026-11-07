.PHONY: install test lint demo bench build

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

lint:
	python3 -m ruff check voicesafekit tests benchmarks

demo:
	echo "my card is four two four two four two four two four two four two four two four two" | python3 -m voicesafekit redact --placeholders

bench:
	python3 benchmarks/run.py

build:
	python3 -m build --sdist --wheel
