"""
hemogrid/llm.py — Language-model interface.

generate(prompt) is the ONLY LLM call site in HemoGrid.

LLM is used for exactly two tasks:
    (a) Draft multilingual donor outreach messages  (Engagement Agent — Phase 2)
    (b) Narrate deterministic orchestrator decisions (Narrator Agent — Phase 2)
Never for matching, scoring, or any deterministic logic — that lives in engine.py.

Day-of provider swap: subclass LLMProvider, implement complete(), then call
set_provider(YourLLMProvider(...)) once at startup. Nothing else changes.

Candidate providers to slot in:
    AnthropicLLM  — Anthropic API (claude-* models)
    BedrockLLM    — AWS Bedrock (any model)
    VertexLLM     — Google Vertex AI
    AzureOpenAILLM — Azure OpenAI Service
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Minimal interface every LLM backend must satisfy."""

    @abstractmethod
    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Return the model's text completion for `prompt`."""


class StubLLM(LLMProvider):
    """
    No-op placeholder — zero cost, zero latency, zero network calls.

    Returns a clearly-marked sentinel string so callers can detect offline mode
    and tests can assert the stub is active.
    """

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return (
            "[LLM_STUB] Provider not configured. "
            f"({len(prompt)} char prompt received.) "
            "Call hemogrid.llm.set_provider() to enable real completions."
        )


# ---------------------------------------------------------------------------
# Module-level provider — single call site for all LLM interactions
# ---------------------------------------------------------------------------

_provider: LLMProvider = StubLLM()


def generate(prompt: str, **kwargs: Any) -> str:
    """
    Generate a completion for `prompt` using the active LLM provider.

    kwargs are forwarded as-is to the provider
    (e.g. max_tokens=256, temperature=0.3, language="te").
    Real providers should honour at minimum max_tokens and temperature.
    """
    return _provider.complete(prompt, **kwargs)


def set_provider(provider: LLMProvider) -> None:
    """Hot-swap the active provider. Call once at startup; not thread-safe."""
    global _provider
    _provider = provider
