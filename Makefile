.PHONY: install run run-local stop test test-fast eval load samples lint clean help

PYTHON := python3.12
VENV := .venv
ACTIVATE := . $(VENV)/bin/activate

help:  ## Megjeleníti a parancsokat
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Lokális venv + függőségek
	$(PYTHON) -m venv $(VENV)
	$(ACTIVATE) && pip install --upgrade pip
	$(ACTIVATE) && pip install --index-url https://download.pytorch.org/whl/cpu torch
	$(ACTIVATE) && pip install -r requirements.txt

run:  ## Docker compose: app indítás (Claude default)
	docker compose up -d --build langgraph-app
	@echo "App: http://localhost:8501"

run-local:  ## Docker compose: app + Ollama (lokális LLM)
	docker compose --profile ollama up -d --build
	@echo "App: http://localhost:8501  |  Ollama: http://localhost:11434"
	@echo "Első indítás:  docker compose exec ollama ollama pull llama3.1:8b"

stop:  ## Docker compose leállítás
	docker compose down

dev:  ## Streamlit lokálisan (.venv-et feltételez)
	$(ACTIVATE) && streamlit run app/main.py

test:  ## Pytest teljes (lassúak nélkül)
	$(ACTIVATE) && pytest tests/ -m "not slow" -v

test-fast:  ## Smoke + unit tesztek dummy LLM-mel (< 30s)
	$(ACTIVATE) && pytest tests/unit/ tests/integration/ -m "not slow" -q

test-e2e:  ## E2E forgatókönyvek (10 db, dummy LLM)
	$(ACTIVATE) && pytest tests/e2e/ -v

eval:  ## 14 chat kérdés + 10 forgatókönyv eval
	$(ACTIVATE) && python eval/run_eval.py --llm dummy

eval-claude:  ## Eval valódi Claude LLM-mel (lassú, API-költség)
	$(ACTIVATE) && python eval/run_eval.py --llm claude

load:  ## Load test: 100 chat query async-gather (dummy)
	$(ACTIVATE) && python load/benchmark.py --n 100

load-parallel:  ## Pipeline parallel test: 20 doksi egyszerre
	$(ACTIVATE) && python load/parallel_pipeline_bench.py --n 20

samples:  ## 75 minta fájl (PDF+DOCX+PNG) generálása
	$(ACTIVATE) && python test_data/generate_samples.py

lint:  ## Ruff lint + formatter
	$(ACTIVATE) && ruff check .
	$(ACTIVATE) && ruff format --check .

format:  ## Ruff auto-format
	$(ACTIVATE) && ruff format .

clean:  ## Cache + perzisztens runtime adat törlés
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf chroma_db/ data/checkpoints.sqlite*
