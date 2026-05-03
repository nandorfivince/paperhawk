"""E2E API paritás-teszt fixtures.

A `prototype-agentic/test_e2e.py` 10-csoportos automata szkript langgraph-ekvivalense.
Közvetlenül a `pipeline_graph.ainvoke()`-ot hívja (NEM a Streamlit UI-on át),
úgy mint a `prototype-agentic` az `orchestrator.process_files()`-t.

A `.env`-ből betöltjük az `ANTHROPIC_API_KEY`-t. Az `LLM_PROFILE=claude` a default —
a Vince szabálya szerint dummy NEM ad megbízható paritás-igazolást.
"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_env_file() -> None:
    """A .env betöltése a pytest folyamatba (ANTHROPIC_API_KEY, LLM_PROFILE, stb.)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()
