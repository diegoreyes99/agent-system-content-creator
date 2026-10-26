"""Estimated cost of a model call, so every run shows how much it spent.

Prices in USD per million tokens (Gemini API, paid tier). They change often:
check https://ai.google.dev/gemini-api/docs/pricing and update the table and
its date. "Thinking" tokens are billed as output.
"""

from __future__ import annotations

PRICES_CHECKED = "2026-10-15"
PRICES_USD_PER_M = {
    # model id: (input, output)
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
}
USD_TO_MXN = 18.5  # approximate, only to show pesos; update when it moves a lot


def cost_usd(model_id: str, prompt_tokens: int, output_tokens: int, thinking_tokens: int = 0) -> float | None:
    """None when the model is not in the table (unknown price, e.g. a local model)."""
    prices = PRICES_USD_PER_M.get(model_id)
    if prices is None:
        return None
    return (prompt_tokens * prices[0] + (output_tokens + thinking_tokens) * prices[1]) / 1_000_000


def describe(usd: float | None) -> str:
    if usd is None:
        return "costo desconocido (modelo sin precio en agents/shared/pricing.py)"
    return f"≈ ${usd:.4f} USD (≈ ${usd * USD_TO_MXN:.2f} MXN)"
