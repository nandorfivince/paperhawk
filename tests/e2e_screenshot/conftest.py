"""E2E Playwright fixtures: Streamlit dev-server + Chromium browser.

A `prototype-agentic/docs/prototype-agentic-tesztek/` 72 manuális screenshot-os
tesztet automatizáljuk. Per teszt-eset:
  - 5 tab full-page screenshot (görgetett tartalom)
  - chat-szekvencia 4-5 kérdés-válasz JSON-be mentve
  - DOCX letöltés + text-extract
  - AI-validáció külön Claude-hívással (lásd `ai_validator.py`)

A Streamlit szervert egy session-fixture indítja a 8520-as porton (LLM_PROFILE
default=claude, ha .env-ben be van állítva — egyébként dummy fallback).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"
STREAMLIT_PORT = 8520
STREAMLIT_URL = f"http://localhost:{STREAMLIT_PORT}"


# A `.env`-ből betöltjük az ANTHROPIC_API_KEY-t és a többi env-változót
# úgy, hogy a pytest folyamatban is rendelkezésre álljanak (az AI-validátor
# Claude vision-API-t hív, ami az env-kulcsot használja). A python-dotenv
# import-ja optional — ha nincs telepítve, manuális parsing.
def _load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass
    # Manuális fallback
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


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_health(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/_stcore/health", timeout=2)
            if r.ok:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Streamlit nem indult el {timeout}s alatt: {url}")


@pytest.fixture(scope="session")
def streamlit_server():
    """Streamlit dev-server session-fixture (port 8520).

    Ha a port már használatban van (pl. user `make dev` futtat), akkor a
    fixture nem indít újat — a futó server-en teszteljük.
    """
    SNAPSHOTS_DIR.mkdir(exist_ok=True)

    if _port_in_use(STREAMLIT_PORT):
        print(f"[streamlit_server] port {STREAMLIT_PORT} már használatban, skip indítás")
        _wait_for_health(STREAMLIT_URL, timeout=5)
        yield STREAMLIT_URL
        return

    env = os.environ.copy()
    # Ha az LLM_PROFILE nincs beállítva, a .env-ből veszi (claude default)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(PROJECT_ROOT / "app" / "main.py"),
            "--server.headless=true",
            f"--server.port={STREAMLIT_PORT}",
            "--browser.gatherUsageStats=false",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_for_health(STREAMLIT_URL, timeout=30)
        print(f"[streamlit_server] elindult: {STREAMLIT_URL}")
        yield STREAMLIT_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser():
    """Chromium session-fixture (headless=True, viewport=1600x1000).

    A `full_page=True` screenshot-tal a teljes scrollable tartalom rögzítve,
    nem csak a viewport — paritás a `prototype-agentic-tesztek/` manuális
    screenshotokkal (ahol a user maga görgette le a UI-t).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        yield context
        context.close()
        browser.close()


@pytest.fixture
def page(browser, streamlit_server):
    """Per-teszt page fixture: új tab, alapértelmezett URL navigálás."""
    page = browser.new_page()
    page.goto(streamlit_server)
    page.wait_for_load_state("networkidle", timeout=30000)
    yield page
    page.close()
