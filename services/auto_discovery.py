"""
Auto-Discovery Service
──────────────────────
Scans local ports for LLM servers (Ollama, vLLM, LM Studio, LocalAI, TextGen)
and external APIs (Gemini, Mistral, HuggingFace). Reports what's available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("auto_discovery")


@dataclass
class DiscoveredProvider:
    name: str
    kind: str  # "local" | "cloud"
    base_url: str
    model: str
    available: bool = False
    latency_ms: float = 0.0
    models: list[str] = field(default_factory=list)
    env_var_host: str = ""
    env_var_model: str = ""
    env_var_key: str = ""
    setup_hint: str = ""


# ── Port scan targets ───────────────────────────────────────

LOCAL_TARGETS = [
    {
        "name": "Ollama",
        "kind": "local",
        "default_host": "http://localhost:11434",
        "health_path": "/api/tags",
        "env_var_host": "OLLAMA_HOST",
        "env_var_model": "OLLAMA_MODEL",
        "default_model": "llama3.1:8b",
        "setup_hint": "Install: https://ollama.ai → ollama pull llama3.1:8b",
    },
    {
        "name": "vLLM",
        "kind": "local",
        "default_host": "http://localhost:8000",
        "health_path": "/v1/models",
        "env_var_host": "VLLM_HOST",
        "env_var_model": "VLLM_MODEL",
        "default_model": "meta-llama/Llama-3-8B-Instruct",
        "setup_hint": "pip install vllm → vllm serve meta-llama/Llama-3-8B-Instruct",
    },
    {
        "name": "LM Studio",
        "kind": "local",
        "default_host": "http://localhost:1234",
        "health_path": "/v1/models",
        "env_var_host": "LM_STUDIO_HOST",
        "env_var_model": "LM_STUDIO_MODEL",
        "default_model": "default",
        "setup_hint": "Download: https://lmstudio.ai → load a model → Start Server",
    },
    {
        "name": "LocalAI",
        "kind": "local",
        "default_host": "http://localhost:8080",
        "health_path": "/v1/models",
        "env_var_host": "LOCALAI_HOST",
        "env_var_model": "LOCALAI_MODEL",
        "default_model": "gpt-3.5-turbo",
        "setup_hint": "docker run -p 8080:8080 localai/localai:latest",
    },
    {
        "name": "TextGen WebUI",
        "kind": "local",
        "default_host": "http://localhost:5000",
        "health_path": "/v1/models",
        "env_var_host": "TEXTGEN_HOST",
        "env_var_model": "TEXTGEN_MODEL",
        "default_model": "default",
        "setup_hint": "git clone https://github.com/oobabooga/text-generation-webui → python server.py",
    },
]

CLOUD_TARGETS = [
    {
        "name": "Gemini",
        "kind": "cloud",
        "env_var_key": "GEMINI_API_KEY",
        "check_url": "https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        "default_model": "gemini-2.0-flash",
        "setup_hint": "Free: https://aistudio.google.com/apikey",
    },
    {
        "name": "Mistral",
        "kind": "cloud",
        "env_var_key": "MISTRAL_API_KEY",
        "check_url": "https://api.mistral.ai/v1/models",
        "default_model": "mistral-small-latest",
        "setup_hint": "Free tier: https://console.mistral.ai/",
    },
    {
        "name": "OpenAI",
        "kind": "cloud",
        "env_var_key": "OPENAI_API_KEY",
        "check_url": "https://api.openai.com/v1/models",
        "default_model": "gpt-4o-mini",
        "setup_hint": "https://platform.openai.com/api-keys",
    },
    {
        "name": "Claude",
        "kind": "cloud",
        "env_var_key": "ANTHROPIC_API_KEY",
        "check_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-haiku-20240307",
        "setup_hint": "https://console.anthropic.com/",
    },
    {
        "name": "HuggingFace",
        "kind": "cloud",
        "env_var_key": "HUGGINGFACE_API_TOKEN",
        "check_url": "https://huggingface.co/api/models?limit=1",
        "default_model": "HuggingFaceH4/zephyr-7b-beta",
        "setup_hint": "Free: https://huggingface.co/settings/tokens",
    },
]


def _check_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _extract_host_port(url: str) -> tuple[str, int]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


async def _probe_local(target: dict) -> DiscoveredProvider:
    host_url = os.environ.get(target["env_var_host"], target["default_host"])
    host, port = _extract_host_port(host_url)

    available = _check_port_open(host, port, timeout=1.0)
    latency_ms = 0.0
    models = []

    if available:
        start = asyncio.get_event_loop().time()
        try:
            url = f"{host_url}{target['health_path']}"
            resp = await asyncio.get_event_loop().run_in_executor(
                None, lambda: urllib.request.urlopen(url, timeout=3).read()
            )
            latency_ms = (asyncio.get_event_loop().time() - start) * 1000
            data = json.loads(resp)
            if "models" in data:
                models = [m.get("name", m) if isinstance(m, dict) else str(m) for m in data["models"]]
        except Exception:
            latency_ms = (asyncio.get_event_loop().time() - start) * 1000

    model = os.environ.get(target["env_var_model"], target["default_model"])

    return DiscoveredProvider(
        name=target["name"],
        kind="local",
        base_url=host_url,
        model=model,
        available=available,
        latency_ms=round(latency_ms, 1),
        models=models,
        env_var_host=target["env_var_host"],
        env_var_model=target["env_var_model"],
        setup_hint=target["setup_hint"],
    )


async def _probe_cloud(target: dict) -> DiscoveredProvider:
    api_key = os.environ.get(target["env_var_key"], "")
    if not api_key:
        return DiscoveredProvider(
            name=target["name"],
            kind="cloud",
            base_url="",
            model=target["default_model"],
            available=False,
            env_var_key=target["env_var_key"],
            setup_hint=target["setup_hint"],
        )

    available = False
    start = asyncio.get_event_loop().time()
    try:
        check_url = target["check_url"].format(key=api_key)
        headers = {"Authorization": f"Bearer {api_key}"} if "models" in check_url else {}
        req = urllib.request.Request(check_url, headers=headers)
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=5).read()
        )
        available = True
    except urllib.error.HTTPError as e:
        available = e.code == 401  # 401 means key is valid but endpoint wrong
    except Exception:
        pass
    latency_ms = (asyncio.get_event_loop().time() - start) * 1000

    return DiscoveredProvider(
        name=target["name"],
        kind="cloud",
        base_url=target.get("check_url", ""),
        model=target["default_model"],
        available=available,
        latency_ms=round(latency_ms, 1),
        env_var_key=target["env_var_key"],
        setup_hint=target["setup_hint"],
    )


async def discover_all() -> list[DiscoveredProvider]:
    """Probe all known LLM providers and return availability status."""
    tasks = [_probe_local(t) for t in LOCAL_TARGETS]
    tasks += [_probe_cloud(t) for t in CLOUD_TARGETS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    providers = [r for r in results if isinstance(r, DiscoveredProvider)]
    available_count = sum(1 for p in providers if p.available)
    logger.info(
        "Auto-discovery: %d/%d providers available",
        available_count, len(providers),
    )
    return providers


def auto_configure_env(providers: list[DiscoveredProvider]) -> dict[str, str]:
    """
    Given discovered providers, return env vars that should be set
    to auto-configure the LLM engine (first available wins).
    """
    env_updates = {}
    priority = ["OpenAI", "Claude", "Gemini", "Mistral", "vLLM", "LM Studio", "LocalAI", "TextGen WebUI", "Ollama", "HuggingFace"]

    for name in priority:
        for p in providers:
            if p.name == name and p.available:
                if p.kind == "local" and p.env_var_host:
                    env_updates[p.env_var_host] = p.base_url
                    if p.env_var_model:
                        env_updates[p.env_var_model] = p.model
                break

    return env_updates


async def ensure_ollama_model(model: str = "llama3.1:8b") -> bool:
    """Auto-pull an Ollama model if Ollama is running but model is missing."""
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    host, port = _extract_host_port(ollama_host)

    if not _check_port_open(host, port):
        return False

    try:
        url = f"{ollama_host}/api/tags"
        resp = await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlopen(url, timeout=5).read()
        )
        data = json.loads(resp)
        installed = [m.get("name", "") for m in data.get("models", [])]

        # Check if model is already installed (exact match or prefix match)
        for m in installed:
            if model == m or model.split(":")[0] in m:
                logger.info("Ollama model %s already installed", model)
                return True

        # Pull the model
        logger.info("Auto-pulling Ollama model: %s (this may take a few minutes)...", model)
        pull_url = f"{ollama_host}/api/pull"
        payload = json.dumps({"name": model, "stream": False}).encode()
        req = urllib.request.Request(
            pull_url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=600).read()
        )
        logger.info("Ollama model %s pulled successfully", model)
        return True
    except Exception as e:
        logger.warning("Failed to ensure Ollama model: %s", e)
        return False


async def ensure_ml_models() -> dict[str, bool]:
    """Ensure ML models are downloaded. Returns status dict."""
    import subprocess
    import sys
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_models.py")
    script = os.path.normpath(script)

    if not os.path.exists(script):
        return {"error": "setup_models.py not found"}

    try:
        result = subprocess.run(
            [sys.executable, script, "--check"],
            capture_output=True, text=True, timeout=30,
        )
        return {"check_output": result.stdout, "returncode": result.returncode}
    except Exception as e:
        return {"error": str(e)}
