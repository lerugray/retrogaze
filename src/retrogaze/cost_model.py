"""
Retrogaze unit-economics constants and margin aggregation.

This module is the single source of truth for:
  * estimated per-generation COGS (fal.ai model costs + CPU/storage overhead)
  * monthly subscription revenue per tier
  * margin aggregation by tier and month

All dollar amounts are USD. Constants are top-level and editable so product
changes do not require hunting through endpoint code.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# fal.ai generation costs
#
# Source: Product/Pricing.md, section "Per-Generation Cost — LOCKED"
#         (locked 2026-04-04)
# Date captured in code: 2026-07-24
# ---------------------------------------------------------------------------

# FLUX Schnell text-to-image @ 512x512 via fal.ai.
FAL_FLUX_SCHNELL_512_COST_USD: float = 0.0030

# FLUX Dev image-to-image @ 512x512 via fal.ai (used when a reference image
# is uploaded).
FAL_FLUX_DEV_512_COST_USD: float = 0.0250

# Image2Pixel conversion call via fal.ai.
FAL_IMAGE2PIXEL_COST_USD: float = 0.0080

# Constraint enforcement, palette remapping, grid alignment, etc.
OVERHEAD_CPU_COST_USD: float = 0.0010

# Supabase Storage + CDN for one generated sprite.
OVERHEAD_STORAGE_CDN_COST_USD: float = 0.0010

# Effective cost per backend model path. These are the numbers the admin
# margin dashboard uses.
COST_PER_MODEL_PATH: dict[str, float] = {
    "schnell+image2pixel": (
        FAL_FLUX_SCHNELL_512_COST_USD
        + FAL_IMAGE2PIXEL_COST_USD
        + OVERHEAD_CPU_COST_USD
        + OVERHEAD_STORAGE_CDN_COST_USD
    ),
    "dev+image2pixel": (
        FAL_FLUX_DEV_512_COST_USD
        + FAL_IMAGE2PIXEL_COST_USD
        + OVERHEAD_CPU_COST_USD
        + OVERHEAD_STORAGE_CDN_COST_USD
    ),
}


# ---------------------------------------------------------------------------
# Subscription revenue per tier
#
# Source: Product/Pricing.md, section "Proposed Tiers"
# Date captured in code: 2026-07-24
# ---------------------------------------------------------------------------

MONTHLY_REVENUE_PER_TIER_USD: dict[str, float] = {
    "free": 0.0,
    "starter": 5.0,
    "pro": 10.0,
    "studio": 20.0,
}

PAID_TIERS: frozenset[str] = frozenset({"starter", "pro", "studio"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cost_for_model_path(model_path: str) -> float:
    """Return the estimated USD cost for a single generation path."""
    return COST_PER_MODEL_PATH.get(model_path, COST_PER_MODEL_PATH["schnell+image2pixel"])


def model_path_and_cost(had_reference: bool) -> tuple[str, float]:
    """Return the database model path and complete COGS for a generation."""
    model_path = "dev+image2pixel" if had_reference else "schnell+image2pixel"
    return model_path, cost_for_model_path(model_path)


def monthly_revenue_for_tier(tier: str) -> float:
    """Return the monthly USD revenue for one active subscriber at tier."""
    return MONTHLY_REVENUE_PER_TIER_USD.get(tier, 0.0)


def is_paid_tier(tier: str) -> bool:
    return tier in PAID_TIERS


def _month_key(created_at: Any) -> str:
    """Extract YYYY-MM from an ISO timestamp string."""
    if isinstance(created_at, str) and len(created_at) >= 7:
        return created_at[:7]
    return "unknown"


def aggregate_margin_by_tier_month(
    generation_rows: list[dict[str, Any]],
    active_subscriber_counts: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """
    Aggregate generation cost by (month, tier) and subtract tier revenue.

    Revenue is computed from the caller-supplied active-subscriber counts
    because Retrogaze does not yet store a dedicated revenue ledger. Pass the
    current active subscriber count per tier to see this month's margin; older
    months will reflect the cost side accurately and revenue side based on the
    same subscriber snapshot (a deliberate approximation documented in the
    admin dashboard).

    Args:
        generation_rows: dicts with keys ``created_at``, ``model_path``,
            and ``tier``. Prefer including the stored ``cost_usd`` so
            best-of-N (multi-candidate) rows that recorded N× per-candidate
            COGS are not under-counted; when ``cost_usd`` is absent the
            aggregator falls back to ``cost_for_model_path(model_path)``.
        active_subscriber_counts: mapping ``tier -> active subscriber count``.
            Defaults to all zeros.

    Returns:
        ``(rows, free_tier_burn_this_month)`` where rows are sorted newest-first
        then tier alphabetical, and ``free_tier_burn_this_month`` is the
        estimated COGS for the current calendar month on the free tier.
    """
    subscriber_counts = active_subscriber_counts or {}

    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"generation_count": 0, "estimated_cost_usd": 0.0}
    )

    for row in generation_rows:
        month = _month_key(row.get("created_at"))
        tier = (row.get("tier") or "free").lower()
        model_path = row.get("model_path") or "schnell+image2pixel"

        stored = row.get("cost_usd")
        if stored is not None and stored != "":
            cost = float(stored)
        else:
            cost = cost_for_model_path(model_path)
        key = (month, tier)
        buckets[key]["generation_count"] += 1
        buckets[key]["estimated_cost_usd"] += cost

    result: list[dict[str, Any]] = []
    for (month, tier), vals in buckets.items():
        revenue = monthly_revenue_for_tier(tier) * subscriber_counts.get(tier, 0)
        result.append(
            {
                "month": month,
                "tier": tier,
                "generation_count": vals["generation_count"],
                "estimated_cost_usd": round(vals["estimated_cost_usd"], 4),
                "revenue_usd": round(revenue, 2),
                "margin_usd": round(revenue - vals["estimated_cost_usd"], 4),
            }
        )

    # Newest month first, then tier alphabetical.
    result.sort(
        key=lambda r: (
            -(int(r["month"].replace("-", "")) if r["month"] != "unknown" else 0),
            r["tier"],
        )
    )

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    free_burn = sum(
        vals["estimated_cost_usd"]
        for (month, tier), vals in buckets.items()
        if month == current_month and tier == "free"
    )

    return result, round(free_burn, 4)
