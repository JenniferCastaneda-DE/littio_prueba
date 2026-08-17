# Littio Senior DE take-home — kit harness
# Targets: smoke | test | rerun-proof | test-gate-fail | run | clean
#
# Conventions:
#   - python3 + .venv; PYTHONPATH=src
#   - smoke: install deps + land bronze + print row counts (bronze only; recruiter-safe)
#   - test: pytest -q tests/  (5 official + bronze sanity; NotImplemented → FAIL)
#   - run: land → silver → wap; tolerate NotImplemented with clear message
#   - rerun-proof: land twice → bronze count stable; if silver/wap implemented,
#       double pipeline GPV delta 0 + late_redelivery_delta no double GPV;
#       if NotImplemented: still assert bronze, exit 0 with message
#   - test-gate-fail: gate_fail fixture + NULL magnitude plant; non-zero when
#       checks implemented; if NotImplemented, skip with message (exit 0)
#   - clean: remove .venv, caches, warehouse.duckdb, __pycache__
#
# Pipeline API (src/pipeline):
#   bronze.land / silver.build_silver / quality.run_wap / gold.run_gold
#   run_wap builds stage gold, runs 3 checks, publishes gold.daily_metrics

PYTHON  ?= python3
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
export PYTHONPATH := src

.PHONY: smoke test rerun-proof test-gate-fail run clean venv deps

venv:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PIP) install -q -U pip
	@if [ -f requirements.txt ]; then $(PIP) install -q -r requirements.txt; \
	else $(PIP) install -q "duckdb>=0.10" "pytest>=7.0"; fi

deps: venv

smoke: deps
	@echo "==> smoke: land bronze + row counts"
	@$(PY) -m tests.make_runners smoke

test: deps
	@echo "==> test: pytest harness"
	@$(PY) -m pytest -q tests/

run: deps
	@echo "==> run: land → silver → wap"
	@$(PY) -m tests.make_runners run

rerun-proof: deps
	@echo "==> rerun-proof: bronze idempotency + money proofs when implemented"
	@$(PY) -m tests.make_runners rerun-proof

# When candidate checks are implemented: expect non-zero if gate does NOT close.
# When NotImplemented: runner prints SKIP and exits 0 (documented soft skip).
test-gate-fail: deps
	@echo "==> test-gate-fail: fail-closed publish on gate_fail fixture"
	@$(PY) -m tests.make_runners test-gate-fail

clean:
	@echo "==> clean"
	rm -rf $(VENV) .pytest_cache .mypy_cache
	rm -f data/warehouse.duckdb
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "clean done"
