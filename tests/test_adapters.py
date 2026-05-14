"""OpenAI-compatible adapter factories: base_url propagation."""

from __future__ import annotations

import importlib.util

import pytest

openai_installed = importlib.util.find_spec("openai") is not None


@pytest.mark.skipif(not openai_installed, reason="openai not installed")
def test_openai_compatible_factory_passes_base_url():
    from overseer.adapters import openai_compatible

    adapter = openai_compatible(
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        api_key="ollama",
    )
    assert adapter.base_url == "http://localhost:11434/v1"
    assert adapter.default_model == "llama3.2"


@pytest.mark.skipif(not openai_installed, reason="openai not installed")
def test_ollama_preset_defaults_to_localhost():
    from overseer.adapters import ollama

    a = ollama("qwen2.5:7b")
    assert a.base_url == "http://localhost:11434/v1"
    assert a.default_model == "qwen2.5:7b"


@pytest.mark.skipif(not openai_installed, reason="openai not installed")
def test_ollama_preset_custom_host():
    from overseer.adapters import ollama

    a = ollama("x", host="http://gpu-box:11434/")
    assert a.base_url == "http://gpu-box:11434/v1"


@pytest.mark.skipif(not openai_installed, reason="openai not installed")
def test_groq_preset():
    from overseer.adapters import groq

    a = groq("llama-3.3-70b-versatile", api_key="x")
    assert a.base_url == "https://api.groq.com/openai/v1"
    assert a.default_model == "llama-3.3-70b-versatile"


def test_openai_adapter_import_error_when_extra_missing(monkeypatch):
    """When the openai package isn't installed, the adapter raises with
    actionable install instructions."""
    if openai_installed:
        pytest.skip("openai is installed in this env; can't simulate missing")
    from overseer.adapters import openai_compatible

    with pytest.raises(ImportError, match=r"pip install overseer\[openai\]"):
        openai_compatible(base_url="http://x", model="m")
