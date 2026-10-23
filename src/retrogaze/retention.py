"""
Generation artifact retention policy and automated cleanup job.

Tier-based retention (per Product/Pricing.md tier definitions):

  - **Free tier** — generated images are auto-deleted after N days
    (default 30, configurable via ``RETROGAZE_FREE_RETENTION_DAYS``).
    The generation *row* is kept (cost_usd, model_path, counters) for
    financial reporting; only the image objects in Storage are removed
    and the path columns are nulled.

  - **Paid tiers** (starter, pro, studio) — indefinite retention.
    Images are kept until the user deletes them or closes their account.

The cleanup job is designed to run on a schedule (cron, Railway cron
service, or similar). It is idempotent: re-running it is safe because
purged rows have ``image_storage_path IS NULL`` and are skipped on
subsequent runs.

GDPR posture: automatic artifact expiry limits the personal data held
for free-tier users. The image (the primary personal-data artifact) is
deleted after the retention window; the row's ``description`` (prompt
text) is retained for analytics. A full right-to-erasure — nulling the
description — is a separate user-initiated flow, not part of the
scheduled retention sweep.

Usage
-----
    # From the src/ directory:
    python -m retrogaze.retention --dry-run
    python -m retrogaze.retention                # live run
    python -m retrogaze.retention --retention-days 14 --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .supabase_client import get_supabase_client, supabase_configured

logger = logging.getLogger("retrogaze.retention")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Free-tier retention window in days. Override with the
# RETROGAZE_FREE_RETENTION_DAYS env var.
_DEFAULT_FREE_RETENTION_DAYS = 30

# Paid tiers retain images indefinitely.
PAID_TIERS = ("starter", "pro", "studio")

# Storage bucket name — matches the bucket created in 001_initial_schema.sql.
STORAGE_BUCKET = "generations"

# How many user IDs to put in a single IN-clause (PostgREST URL-length guard).
_USER_BATCH_SIZE = 500

# How many storage paths to delete in a single remove() call.
_STORAGE_BATCH_SIZE = 100


def _free_retention_days() -> int:
    """Return the free-tier retention window in days (env-configurable)."""
    raw = os.environ.get("RETROGAZE_FREE_RETENTION_DAYS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "Invalid RETROGAZE_FREE_RETENTION_DAYS=%r, using default %d",
                raw, _DEFAULT_FREE_RETENTION_DAYS,
            )
    return _DEFAULT_FREE_RETENTION_DAYS


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    """Retention decision for a given tier."""
    tier: str
    retention_days: int | None  # None = indefinite
    auto_delete: bool

    @property
    def description(self) -> str:
        if self.retention_days is None:
            return f"{self.tier}: indefinite retention"
        return f"{self.tier}: auto-delete images after {self.retention_days} days"


def get_retention_policy(tier: str) -> RetentionPolicy:
    """Return the retention policy for a subscription tier.

    Paid tiers (starter, pro, studio) retain images indefinitely.
    The free tier (and any unrecognized tier) gets the time-bounded
    auto-delete policy.
    """
    if tier in PAID_TIERS:
        return RetentionPolicy(tier=tier, retention_days=None, auto_delete=False)
    return RetentionPolicy(
        tier=tier or "free",
        retention_days=_free_retention_days(),
        auto_delete=True,
    )


# ---------------------------------------------------------------------------
# Cleanup report
# ---------------------------------------------------------------------------

@dataclass
class CleanupReport:
    """Summary of a retention cleanup run."""
    dry_run: bool = False
    cutoff: datetime | None = None
    retention_days: int | None = None
    free_users_scanned: int = 0
    generations_found: int = 0
    storage_objects_deleted: int = 0
    storage_delete_errors: int = 0
    rows_updated: int = 0
    row_update_errors: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        prefix = "[DRY RUN] " if self.dry_run else ""
        cutoff_str = self.cutoff.strftime("%Y-%m-%d") if self.cutoff else "N/A"
        return (
            f"{prefix}Retention cleanup: "
            f"{self.free_users_scanned} free users scanned, "
            f"cutoff={cutoff_str} ({self.retention_days}d), "
            f"{self.generations_found} expired generations, "
            f"{self.storage_objects_deleted} storage objects "
            f"{'would be ' if self.dry_run else ''}deleted, "
            f"{self.rows_updated} rows {'would be ' if self.dry_run else ''}updated"
            + (f", {self.storage_delete_errors} storage errors"
               if self.storage_delete_errors else "")
            + (f", {self.row_update_errors} DB errors"
               if self.row_update_errors else "")
        )


# ---------------------------------------------------------------------------
# Cleanup job
# ---------------------------------------------------------------------------

def run_retention_cleanup(
    *,
    dry_run: bool = False,
    batch_size: int = 200,
    retention_days: int | None = None,
) -> CleanupReport:
    """Run one pass of the retention cleanup job.

    Finds free-tier users' generations older than the retention window,
    deletes their image objects from Supabase Storage, and nulls the
    path columns on the generations row. The row itself is preserved
    for cost/financial audit (generations is an immutable cost trail).

    Parameters
    ----------
    dry_run:
        If True, report what *would* be deleted without making any
        storage or DB changes.
    batch_size:
        Number of generation rows to fetch and process per iteration.
    retention_days:
        Override the free-tier retention window for this run. When
        None, uses ``RETROGAZE_FREE_RETENTION_DAYS`` env or the 30-day
        default.

    Returns a :class:`CleanupReport` with counts and any errors.
    """
    report = CleanupReport(
        dry_run=dry_run,
        retention_days=retention_days if retention_days is not None
        else _free_retention_days(),
    )

    if not supabase_configured():
        report.errors.append("Supabase not configured — cannot run cleanup")
        logger.error("Retention cleanup aborted: Supabase not configured")
        return report

    sb = get_supabase_client()
    days = report.retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    report.cutoff = cutoff
    logger.info(
        "Retention cleanup starting (dry_run=%s, retention=%d days, cutoff=%s)",
        dry_run, days, cutoff.isoformat(),
    )

    # --- 1. Collect all free-tier user IDs (paginated) --------------------
    free_user_ids: list[str] = []
    user_offset = 0
    user_page = 1000
    while True:
        try:
            result = (
                sb.table("profiles")
                .select("id")
                .eq("tier", "free")
                .range(user_offset, user_offset + user_page - 1)
                .execute()
            )
        except Exception as exc:
            report.errors.append(f"Failed to query free-tier profiles: {exc}")
            logger.error("Failed to query free-tier profiles: %s", exc)
            return report

        batch = result.data or []
        free_user_ids.extend(row["id"] for row in batch)
        if len(batch) < user_page:
            break
        user_offset += user_page

    report.free_users_scanned = len(free_user_ids)
    logger.info("Found %d free-tier users", len(free_user_ids))

    if not free_user_ids:
        logger.info("No free-tier users — nothing to clean up")
        return report

    cutoff_iso = cutoff.isoformat()
    bucket = sb.storage.from_(STORAGE_BUCKET)

    # --- 2. For each batch of user IDs, find and purge old generations ----
    for ui in range(0, len(free_user_ids), _USER_BATCH_SIZE):
        user_batch = free_user_ids[ui:ui + _USER_BATCH_SIZE]

        # Inner loop: re-query after each batch is purged so the filter
        # (image_storage_path IS NOT NULL) shrinks the result set. No
        # offset is needed — purged rows drop out of the next query.
        while True:
            try:
                result = (
                    sb.table("generations")
                    .select(
                        "id, image_storage_path, variation_storage_paths"
                    )
                    .in_("user_id", user_batch)
                    .lt("created_at", cutoff_iso)
                    .not_.is_("image_storage_path", "null")
                    .limit(batch_size)
                    .execute()
                )
            except Exception as exc:
                msg = f"Generation query failed (user batch {ui}): {exc}"
                report.errors.append(msg)
                logger.error(msg)
                break

            rows = result.data or []
            if not rows:
                break

            report.generations_found += len(rows)

            # Collect storage paths and generation IDs
            paths_to_delete: list[str] = []
            gen_ids: list[str] = []
            for row in rows:
                gen_ids.append(row["id"])
                primary = row.get("image_storage_path")
                if primary:
                    paths_to_delete.append(primary)
                for vp in (row.get("variation_storage_paths") or []):
                    if vp:
                        paths_to_delete.append(vp)

            if dry_run:
                report.storage_objects_deleted += len(paths_to_delete)
                report.rows_updated += len(gen_ids)
                logger.info(
                    "[DRY RUN] Would delete %d storage objects, "
                    "null paths on %d generations",
                    len(paths_to_delete), len(gen_ids),
                )
                continue

            # --- 2a. Delete storage objects (batched) --------------------
            for pi in range(0, len(paths_to_delete), _STORAGE_BATCH_SIZE):
                chunk = paths_to_delete[pi:pi + _STORAGE_BATCH_SIZE]
                try:
                    bucket.remove(chunk)
                    report.storage_objects_deleted += len(chunk)
                except Exception as exc:
                    report.storage_delete_errors += len(chunk)
                    logger.warning(
                        "Storage delete failed for %d paths: %s",
                        len(chunk), exc,
                    )

            # --- 2b. Null path columns on the generations rows -----------
            # Keep the row itself — cost_usd, model_path, and aggregate
            # counters remain for financial reporting. variation_storage_paths
            # is text[] NOT NULL DEFAULT '{}' so we set it to an empty array.
            try:
                sb.table("generations").update({
                    "image_storage_path": None,
                    "variation_storage_paths": [],
                }).in_("id", gen_ids).execute()
                report.rows_updated += len(gen_ids)
            except Exception as exc:
                report.row_update_errors += len(gen_ids)
                msg = f"DB update failed for {len(gen_ids)} generations: {exc}"
                report.errors.append(msg)
                logger.error(msg)

    logger.info(report.summary())
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="retrogaze.retention",
        description=(
            "Run the generation artifact retention cleanup job. "
            "Deletes free-tier users' images older than the retention window."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without making any changes.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of generation rows to process per batch (default: 200).",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            "Override the free-tier retention window in days for this run "
            "(default: env RETROGAZE_FREE_RETENTION_DAYS or 30)."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = run_retention_cleanup(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        retention_days=args.retention_days,
    )
    print(report.summary())
    if report.errors:
        print(f"\nErrors ({len(report.errors)}):")
        for err in report.errors:
            print(f"  - {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()