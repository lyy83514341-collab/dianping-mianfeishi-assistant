#!/usr/bin/env python3
"""Daily orchestrator for Dianping free-try scanning and application routes."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


TERMINAL_FAILURES = {"app_rejected", "not_eligible", "account_ineligible", "activity_ended"}
RETRYABLE_ROUTE_PAUSE = 5


def eligible_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    result: set[str] = set()
    with csv_path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            activity_id = row.get("offlineActivityId") or ""
            food = row.get("activityType") == "1" or row.get("isFood") == "True"
            if row.get("eligible") == "True" and food and activity_id:
                result.add(activity_id)
    return result


def remaining_ids(csv_path: Path, state_path: Path) -> set[str]:
    current = eligible_ids(csv_path)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    success = set((state.get("success") or {}).keys())
    failures = state.get("failed") or {}
    terminal = {
        activity_id
        for activity_id, record in failures.items()
        if (record or {}).get("status") in TERMINAL_FAILURES
    }
    return current - success - terminal


def scan_current_day(args: argparse.Namespace, python: str, phase: str) -> int:
    print(f"scan_phase={phase}", flush=True)
    return run(
        [
            python,
            str(SCRIPT_DIR / "free_try_filter.py"),
            "--max-pages",
            str(args.max_pages),
            "--workers",
            str(args.workers),
            "--top",
            "0",
            "--refresh-details",
            "--out",
            str(args.csv),
        ]
    )


def apply_routes(args: argparse.Namespace, python: str) -> int:
    before = remaining_ids(args.csv, args.state)
    if args.route == "auto" and not before:
        print("apply_routes=no_remaining", flush=True)
        return 0

    if args.route in {"auto", "list"}:
        list_cmd = [
            python,
            str(SCRIPT_DIR / "list_apply_free_try_adb.py"),
            "--serial",
            args.serial,
            "--csv",
            str(args.csv),
            "--state",
            str(args.state),
            "--max-success",
            str(args.max_apply),
            "--route-unavailable-retries",
            str(args.list_unavailable_retries),
            "--route-unavailable-backoff",
            str(args.list_unavailable_backoff),
            "--skip-failed",
        ]
        if args.dry_run:
            list_cmd.append("--dry-run")
        rc = run(list_cmd)
        if args.route == "list":
            return rc
        remaining = remaining_ids(args.csv, args.state)
        if rc not in {0, 3}:
            return rc
        if not remaining:
            return rc
        print(
            f"list_route_done exit={rc} remaining={len(remaining)}; falling_back=deeplink",
            flush=True,
        )

    deeplink_cmd = [
        python,
        str(SCRIPT_DIR / "direct_apply_free_try_adb.py"),
        "--serial",
        args.serial,
        "--csv",
        str(args.csv),
        "--state",
        str(args.state),
        "--max-success",
        str(args.max_apply),
        "--max-attempts",
        str(args.max_apply),
        "--max-consecutive-detail-blank",
        str(args.direct_blank_streak_limit),
        "--force-stop-before-open",
    ]
    if args.dry_run:
        print("dry_run_deeplink_not_supported; stopping_before_submit", flush=True)
        return 0
    return run(deeplink_cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", choices=("auto", "list", "deeplink"), default="auto")
    parser.add_argument("--max-apply", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--list-unavailable-retries", type=int, default=3)
    parser.add_argument("--list-unavailable-backoff", type=float, default=5.0)
    parser.add_argument("--direct-blank-streak-limit", type=int, default=3)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--state", type=Path, default=Path("reports/free_try_apply_state.json"))
    parser.add_argument("--csv", type=Path, default=Path("reports/free_try_candidates_beijing.csv"))
    parser.add_argument(
        "--skip-daily-scan",
        action="store_true",
        help="Diagnostic only: reuse the existing CSV instead of refreshing today's activities.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.list_unavailable_retries < 0:
        parser.error("--list-unavailable-retries must be >= 0")
    if args.list_unavailable_backoff < 0:
        parser.error("--list-unavailable-backoff must be >= 0")
    if args.direct_blank_streak_limit < 1:
        parser.error("--direct-blank-streak-limit must be >= 1")

    python = sys.executable
    if not args.skip_daily_scan:
        rc = scan_current_day(args, python, "initial")
        if rc:
            print(f"daily_scan_failed exit={rc}", flush=True)
            return rc

    rc = apply_routes(args, python)
    if args.dry_run or args.route != "auto":
        return rc
    if rc not in {0, RETRYABLE_ROUTE_PAUSE}:
        return rc
    if rc == RETRYABLE_ROUTE_PAUSE:
        print("apply_routes_paused=retryable_route_state; continuing_to_verification", flush=True)

    before_ids = eligible_ids(args.csv)
    unresolved_before = remaining_ids(args.csv, args.state)
    rc = scan_current_day(args, python, "verification")
    if rc:
        print(f"verification_scan_failed exit={rc}", flush=True)
        return rc

    after_ids = eligible_ids(args.csv)
    unresolved_after = remaining_ids(args.csv, args.state)
    added = after_ids - before_ids
    removed = before_ids - after_ids
    print(
        "verification_scan_complete "
        f"eligible_before={len(before_ids)} eligible_after={len(after_ids)} "
        f"added={len(added)} removed={len(removed)} "
        f"unresolved_before={len(unresolved_before)} unresolved_after={len(unresolved_after)}",
        flush=True,
    )
    if added:
        print("verification_added_ids=" + ",".join(sorted(added)), flush=True)

    if unresolved_after:
        print(f"verification_apply_delta count={len(unresolved_after)}", flush=True)
        rc = apply_routes(args, python)
        if rc not in {0, RETRYABLE_ROUTE_PAUSE}:
            return rc
        if rc == RETRYABLE_ROUTE_PAUSE:
            print("verification_route_paused=retryable_route_state", flush=True)

    final_remaining = remaining_ids(args.csv, args.state)
    print(f"verification_final_remaining={len(final_remaining)}", flush=True)
    if final_remaining:
        print("verification_remaining_ids=" + ",".join(sorted(final_remaining)), flush=True)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
