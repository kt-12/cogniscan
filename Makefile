PY=.venv/bin/python
.PHONY: setup serve check test export-mesh lint ui ui-dev ui-check
setup:
	uv venv --python 3.12 .venv
	uv pip install -p $(PY) -e ".[dev]" websocket-client
	$(MAKE) ui
serve:
	$(PY) -m cli.cogniscan serve
export-mesh:
	$(PY) -m cli.cogniscan export-mesh
ui:            ## build the React viewer into server/static/dist (needs node >= 20)
	cd ui && npm ci && npm run build
ui-dev:        ## hot-reloading viewer on :5173, proxied to the server on :8787
	cd ui && npm run dev
ui-check:
	cd ui && npx tsc -b && npm run lint
lint:
	.venv/bin/ruff check server cli tests
test:
	$(PY) -m pytest -q
check: lint test ui-check
