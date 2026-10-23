"""Pricing-limit and generation-cost consistency tests."""

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze.cost_model import cost_for_model_path, model_path_and_cost


EXPECTED_TIER_LIMITS = {
    "free": {"daily": 5, "monthly": 50},
    "starter": {"daily": None, "monthly": 100},
    "pro": {"daily": None, "monthly": 225},
    "studio": {"daily": None, "monthly": 500},
}


API_PATH = Path(__file__).resolve().parents[1] / "retrogaze" / "api.py"


def _api_tree():
    return ast.parse(API_PATH.read_text(encoding="utf-8"))


def _api_tier_limits():
    for node in _api_tree().body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "_TIER_LIMITS"
                for target in node.targets
            ):
                return ast.literal_eval(node.value)
    raise AssertionError("_TIER_LIMITS assignment not found")


def test_generation_tier_limits_match_approved_table():
    assert _api_tier_limits() == EXPECTED_TIER_LIMITS


def test_free_monthly_limit_flows_into_atomic_reservation():
    source = API_PATH.read_text(encoding="utf-8")

    assert '"try_consume_generation"' in source
    assert '"p_tier_limits": _TIER_LIMITS' in source


def test_atomic_reservation_migration_checks_monthly_cap_for_free():
    migration = (
        Path(__file__).resolve().parents[2]
        / "Development"
        / "migrations"
        / "013_generation_tier_limits.sql"
    )
    if not migration.exists():
        pytest.skip("SaaS migration tree not present in this checkout")
    sql = migration.read_text(encoding="utf-8")

    assert "drop function if exists public.check_generation_limit(uuid)" in sql
    assert "p_tier_limits -> v_tier ->> 'monthly'" in sql
    assert (
        "and (v_monthly_limit is null or monthly_count < v_monthly_limit)"
        in sql
    )


@pytest.mark.parametrize(
    ("had_reference", "model_path"),
    [
        (False, "schnell+image2pixel"),
        (True, "dev+image2pixel"),
    ],
)
def test_recorded_generation_cost_comes_from_cost_model(had_reference, model_path):
    recorded_path, recorded_cost = model_path_and_cost(had_reference)

    assert recorded_path == model_path
    assert recorded_cost == pytest.approx(cost_for_model_path(model_path))


def test_generation_recording_calls_shared_cost_model_helper():
    tree = _api_tree()
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "model_path_and_cost"
    ]

    assert len(calls) == 1
