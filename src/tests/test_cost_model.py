"""
Tests for retrogaze.cost_model — unit-economics constants and margin aggregation.

These tests run offline (no Supabase/fal.ai calls). They verify that known
fixture counts produce deterministic cost, revenue, and margin numbers.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timezone

from retrogaze.cost_model import (
    cost_for_model_path,
    monthly_revenue_for_tier,
    is_paid_tier,
    aggregate_margin_by_tier_month,
    FAL_FLUX_SCHNELL_512_COST_USD,
    FAL_FLUX_DEV_512_COST_USD,
    FAL_IMAGE2PIXEL_COST_USD,
    OVERHEAD_CPU_COST_USD,
    OVERHEAD_STORAGE_CDN_COST_USD,
)


SCHNELL_COST = (
    FAL_FLUX_SCHNELL_512_COST_USD
    + FAL_IMAGE2PIXEL_COST_USD
    + OVERHEAD_CPU_COST_USD
    + OVERHEAD_STORAGE_CDN_COST_USD
)
DEV_COST = (
    FAL_FLUX_DEV_512_COST_USD
    + FAL_IMAGE2PIXEL_COST_USD
    + OVERHEAD_CPU_COST_USD
    + OVERHEAD_STORAGE_CDN_COST_USD
)


class TestCostConstants:
    def test_schnell_path_cost(self):
        assert cost_for_model_path("schnell+image2pixel") == pytest.approx(SCHNELL_COST)

    def test_dev_path_cost(self):
        assert cost_for_model_path("dev+image2pixel") == pytest.approx(DEV_COST)

    def test_unknown_path_defaults_to_schnell(self):
        assert cost_for_model_path("future+magic") == pytest.approx(SCHNELL_COST)

    def test_tier_revenue_values(self):
        assert monthly_revenue_for_tier("free") == 0.0
        assert monthly_revenue_for_tier("starter") == 5.0
        assert monthly_revenue_for_tier("pro") == 10.0
        assert monthly_revenue_for_tier("studio") == 20.0
        assert monthly_revenue_for_tier("unknown") == 0.0

    def test_paid_tier_detection(self):
        assert is_paid_tier("starter") is True
        assert is_paid_tier("pro") is True
        assert is_paid_tier("studio") is True
        assert is_paid_tier("free") is False
        assert is_paid_tier("unknown") is False


class TestMarginAggregation:
    def test_aggregation_groups_by_month_and_tier(self):
        rows = [
            {"created_at": "2026-07-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": "2026-07-02T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": "2026-07-03T00:00:00Z", "model_path": "dev+image2pixel", "tier": "pro"},
            {"created_at": "2026-06-15T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "starter"},
        ]
        result, burn = aggregate_margin_by_tier_month(rows)

        assert len(result) == 3

        # July free
        july_free = next(r for r in result if r["month"] == "2026-07" and r["tier"] == "free")
        assert july_free["generation_count"] == 2
        assert july_free["estimated_cost_usd"] == pytest.approx(round(2 * SCHNELL_COST, 4))
        assert july_free["revenue_usd"] == 0.0
        assert july_free["margin_usd"] == pytest.approx(-round(2 * SCHNELL_COST, 4))

        # July pro (dev path)
        july_pro = next(r for r in result if r["month"] == "2026-07" and r["tier"] == "pro")
        assert july_pro["generation_count"] == 1
        assert july_pro["estimated_cost_usd"] == pytest.approx(round(DEV_COST, 4))

        # June starter
        june_starter = next(r for r in result if r["month"] == "2026-06" and r["tier"] == "starter")
        assert june_starter["generation_count"] == 1
        assert june_starter["estimated_cost_usd"] == pytest.approx(round(SCHNELL_COST, 4))

    def test_revenue_computed_from_subscriber_counts(self):
        rows = [
            {"created_at": "2026-07-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "starter"},
            {"created_at": "2026-07-02T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "starter"},
            {"created_at": "2026-07-03T00:00:00Z", "model_path": "dev+image2pixel", "tier": "pro"},
        ]
        subscribers = {"starter": 3, "pro": 2}
        result, _ = aggregate_margin_by_tier_month(rows, subscribers)

        starter = next(r for r in result if r["tier"] == "starter")
        assert starter["revenue_usd"] == 15.0  # 3 subscribers * $5
        expected_starter_cost = round(2 * SCHNELL_COST, 4)
        assert starter["margin_usd"] == pytest.approx(round(15.0 - expected_starter_cost, 4))

        pro = next(r for r in result if r["tier"] == "pro")
        assert pro["revenue_usd"] == 20.0  # 2 subscribers * $10
        expected_pro_cost = round(DEV_COST, 4)
        assert pro["margin_usd"] == pytest.approx(round(20.0 - expected_pro_cost, 4))

    def test_sort_order_newest_first(self):
        rows = [
            {"created_at": "2026-05-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": "2026-07-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": "2026-06-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
        ]
        result, _ = aggregate_margin_by_tier_month(rows)
        months = [r["month"] for r in result]
        assert months == ["2026-07", "2026-06", "2026-05"]

    def test_free_tier_burn_this_month(self):
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        rows = [
            {"created_at": f"{current_month}-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": f"{current_month}-02T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": f"{current_month}-03T00:00:00Z", "model_path": "dev+image2pixel", "tier": "free"},
            {"created_at": "2026-06-01T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "free"},
            {"created_at": f"{current_month}-04T00:00:00Z", "model_path": "schnell+image2pixel", "tier": "pro"},
        ]
        _, burn = aggregate_margin_by_tier_month(rows)
        expected_burn = round(2 * SCHNELL_COST + DEV_COST, 4)
        assert burn == pytest.approx(expected_burn)

    def test_empty_input(self):
        result, burn = aggregate_margin_by_tier_month([])
        assert result == []
        assert burn == 0.0

    def test_missing_fields_default_to_free_schnell(self):
        rows = [{"created_at": "2026-07-01T00:00:00Z"}]
        result, _ = aggregate_margin_by_tier_month(rows)
        assert len(result) == 1
        assert result[0]["tier"] == "free"
        assert result[0]["estimated_cost_usd"] == pytest.approx(round(SCHNELL_COST, 4))

    def test_stored_cost_usd_preferred_over_model_path_estimate(self):
        """RG-069: best-of-N rows store N× cost; margin must not re-derive 1×."""
        rows = [
            {
                "created_at": "2026-07-01T00:00:00Z",
                "model_path": "schnell+image2pixel",
                "tier": "pro",
                "cost_usd": 4 * SCHNELL_COST,
            },
            {
                "created_at": "2026-07-02T00:00:00Z",
                "model_path": "schnell+image2pixel",
                "tier": "pro",
                # no cost_usd → fall back to model_path estimate
            },
        ]
        result, _ = aggregate_margin_by_tier_month(rows)
        pro = next(r for r in result if r["tier"] == "pro")
        assert pro["generation_count"] == 2
        assert pro["estimated_cost_usd"] == pytest.approx(
            round(4 * SCHNELL_COST + SCHNELL_COST, 4)
        )
