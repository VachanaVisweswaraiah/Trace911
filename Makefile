# trace911 — monorepo dev commands.
#
# Usage:
#   make install   # backend venv + deps; frontend npm install (if present)
#   make dev       # run backend + frontend together (Ctrl+C stops both)
#   make backend   # backend only
#   make frontend  # frontend only
#   make clean     # remove venvs, node_modules, sqlite db

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

.PHONY: help install install-backend install-frontend dev backend frontend clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install everything

install-backend: ## Create venv and install backend deps
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -e "$(BACKEND_DIR)[dev]"
	@test -f $(BACKEND_DIR)/.env || cp $(BACKEND_DIR)/.env.example $(BACKEND_DIR)/.env
	@echo "✓ backend ready"

install-frontend: ## npm install if frontend/package.json exists
	@if [ -f $(FRONTEND_DIR)/package.json ]; then \
	  cd $(FRONTEND_DIR) && npm install; \
	  echo "✓ frontend ready"; \
	else \
	  echo "• frontend/package.json missing — skip (drop the Lovable export into $(FRONTEND_DIR)/ when ready)"; \
	fi

backend: ## Run backend only
	@$(UVICORN) --app-dir $(BACKEND_DIR) app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

frontend: ## Run frontend only
	@if [ -f $(FRONTEND_DIR)/package.json ]; then \
	  cd $(FRONTEND_DIR) && npm run dev -- --port $(FRONTEND_PORT); \
	else \
	  echo "frontend/package.json missing. Drop the Lovable export into $(FRONTEND_DIR)/ first."; \
	  exit 1; \
	fi

dev: ## Run backend + frontend together (Ctrl+C stops both)
	@echo "→ backend  http://localhost:$(BACKEND_PORT)"
	@echo "→ frontend http://localhost:$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) -s backend & \
	if [ -f $(FRONTEND_DIR)/package.json ]; then \
	  $(MAKE) -s frontend & \
	else \
	  echo "• frontend/package.json missing — running backend only"; \
	fi; \
	wait

clean: ## Remove venv, node_modules, sqlite db, caches
	rm -rf $(VENV) $(FRONTEND_DIR)/node_modules
	rm -f $(BACKEND_DIR)/trace911.db $(BACKEND_DIR)/test_trace911.db
	find $(BACKEND_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ cleaned"
