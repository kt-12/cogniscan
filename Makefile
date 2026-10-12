PY=.venv/bin/python
.PHONY: setup serve check test export-mesh lint
setup:
	uv venv --python 3.12 .venv
	uv pip install -p $(PY) -e ".[dev]" websocket-client
serve:
	$(PY) -m cli.scanmyweb serve
export-mesh:
	$(PY) -m cli.scanmyweb export-mesh
lint:
	.venv/bin/ruff check server cli tests
test:
	$(PY) -m pytest -q
check: lint test
