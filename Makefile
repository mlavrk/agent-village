# Agent Village — the tests are plain scripts, no framework.
PYTHON ?= .venv/bin/python
TESTS  := $(sort $(wildcard tests/test_*.py))
ARGS   ?=                  # passed through to run.py: make mock ARGS="--players 8"
FAIL_LINES ?= 15           # tail of a failing file's output; the traceback is at the end

REQUIRE_PY = command -v "$(PYTHON)" >/dev/null || { echo "no interpreter at $(PYTHON) — try: PYTHON=python3"; exit 1; }

.PHONY: help run mock test test-v

help:
	@echo "make run      start a game on real models + dashboard on :8300"
	@echo "make mock     the same, but local stubs — no API key, no tokens"
	@echo "make test     run every test file, one line each"
	@echo "make test-v   the same, but show each file's output"
	@echo ""
	@echo "Flags reach run.py through ARGS:"
	@echo "  make mock ARGS=\"--players 8 --seed 3 --delay 0\""
	@echo "  make run  ARGS=\"--rounds 3 --budget 50000 --port 8400\""
	@echo "  make run  ARGS=--help        (every flag)"
	@echo ""
	@echo "PYTHON=$(PYTHON) (override: make test PYTHON=python3)"

## A real game costs tokens, so fail early rather than at the first API call.
run:
	@$(REQUIRE_PY)
	@test -f .env || test -n "$$OPENCODE_API_KEY" || \
		{ echo "no OPENCODE_API_KEY in .env or the environment — try: make mock"; exit 1; }
	$(PYTHON) run.py $(ARGS)

mock:
	@$(REQUIRE_PY)
	$(PYTHON) run.py --mock $(ARGS)

## Run all of them even if one fails, then exit non-zero if any did.
test:
	@$(REQUIRE_PY)
	@failed=""; \
	for t in $(TESTS); do \
		printf '%-22s ' "$$(basename $$t)"; \
		if out=$$($(PYTHON) $$t 2>&1); then \
			echo "PASS"; \
		else \
			echo "FAIL"; \
			echo "$$out" | tail -$(FAIL_LINES) | sed 's/^/    /'; \
			failed="$$failed $$(basename $$t)"; \
		fi; \
	done; \
	if [ -n "$$failed" ]; then echo; echo "FAILED:$$failed"; exit 1; fi; \
	echo; echo "$(words $(TESTS)) test files passed"

test-v:
	@$(REQUIRE_PY)
	@failed=""; \
	for t in $(TESTS); do \
		echo "── $$t"; \
		$(PYTHON) $$t || failed="$$failed $$(basename $$t)"; \
	done; \
	if [ -n "$$failed" ]; then echo; echo "FAILED:$$failed"; exit 1; fi; \
	echo; echo "$(words $(TESTS)) test files passed"
