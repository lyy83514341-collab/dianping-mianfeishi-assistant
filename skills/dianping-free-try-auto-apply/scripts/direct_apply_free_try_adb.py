#!/usr/bin/env python3
"""Safely apply to remaining eligible activities by official App deeplink.

This route is used only after the visible list is unavailable or exhausted. It
reuses the screenshot-verified submission state machine from the list route;
the deeplink changes navigation, not the safety checks.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from batch_apply_free_try_adb import (
    DEFAULT_CSV,
    DEFAULT_SERIAL,
    DEFAULT_STATE,
    adb,
    load_state,
    open_detail,
    save_state,
)
from list_apply_free_try_adb import (
    TERMINAL_FAILURE_STATUSES,
    eligible,
    load_candidates,
    record_for,
    submit_current_detail,
)

DEFAULT_OUT_DIR = Path("/tmp/free_try_direct_batch")


def planned_rows(
    candidates: dict[str, dict[str, str]],
    state: dict[str, Any],
) -> list[dict[str, str]]:
    """Plan unresolved rows, placing recently blank details behind untried work."""
    success = state.get("success") or {}
    failures = state.get("failed") or {}
    paused = state.get("paused") or {}
    prioritized: list[tuple[int, int, dict[str, str]]] = []
    for position, (activity_id, row) in enumerate(candidates.items()):
        if not eligible(row) or activity_id in success:
            continue
        previous = failures.get(activity_id) or {}
        if previous.get("status") in TERMINAL_FAILURE_STATUSES:
            continue
        paused_status = (paused.get(activity_id) or {}).get("status")
        priority = 1 if paused_status == "detail_blank" else 0
        prioritized.append((priority, position, row))
    prioritized.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in prioritized]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--max-success", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=100)
    parser.add_argument("--detail-wait", type=float, default=0.6)
    parser.add_argument("--sheet-wait", type=float, default=2.5)
    parser.add_argument("--result-wait", type=float, default=4.5)
    parser.add_argument("--agreement-tap-wait", type=float, default=0.45)
    parser.add_argument(
        "--max-consecutive-detail-blank",
        type=int,
        default=3,
        help="Pause this route after this many consecutive verified blank details.",
    )
    parser.add_argument("--force-stop-before-open", action="store_true")
    args = parser.parse_args()
    if args.max_consecutive_detail_blank < 1:
        parser.error("--max-consecutive-detail-blank must be >= 1")

    state: dict[str, Any] = load_state(args.state)
    candidates = load_candidates(args.csv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = planned_rows(candidates, state)

    successes = 0
    attempts = 0
    consecutive_detail_blank = 0
    print(f"direct_planned={len(rows)}", flush=True)
    for row in rows:
        if successes >= args.max_success or attempts >= args.max_attempts:
            break
        attempts += 1
        activity_id = row["offlineActivityId"]
        print(
            f"direct_attempt={attempts} id={activity_id} cost={row.get('cost')} "
            f"district={row.get('districts')} title={row.get('title')}",
            flush=True,
        )
        open_detail(args.serial, activity_id, force_stop=args.force_stop_before_open)
        time.sleep(args.detail_wait)
        status, text = submit_current_detail(
            args.serial,
            args.out_dir,
            activity_id,
            row,
            args.sheet_wait,
            args.result_wait,
            args.agreement_tap_wait,
        )
        print(f"direct_id={activity_id} status={status}", flush=True)

        if status in {"success", "already_applied"}:
            consecutive_detail_blank = 0
            state.setdefault("success", {})[activity_id] = record_for(
                row, "success", "official App detail-deeplink fallback"
            )
            state.get("failed", {}).pop(activity_id, None)
            state.get("paused", {}).pop(activity_id, None)
            save_state(args.state, state)
            successes += 1
            window = adb(args.serial, "shell", "dumpsys", "window", check=False).stdout
            if "YodaRouterTransparentActivity" in window:
                print(f"paused=human_verification_after_success id={activity_id}", flush=True)
                return 2
            continue

        if status == "human_verification":
            state.setdefault("paused", {})[activity_id] = record_for(
                row, status, "user action required; rerun after completion"
            )
            save_state(args.state, state)
            print(f"paused=human_verification id={activity_id}", flush=True)
            return 2

        if status == "official_unavailable":
            state.setdefault("paused", {})[activity_id] = record_for(row, status, text[-300:])
            save_state(args.state, state)
            print(f"paused=official_unavailable id={activity_id}", flush=True)
            return 3

        state.setdefault("paused", {})[activity_id] = record_for(
            row, status, (text[-300:] or "route-specific technical state")
        )
        save_state(args.state, state)
        if status == "detail_blank":
            consecutive_detail_blank += 1
            print(
                "direct_detail_blank_streak="
                f"{consecutive_detail_blank}/{args.max_consecutive_detail_blank}",
                flush=True,
            )
            if consecutive_detail_blank >= args.max_consecutive_detail_blank:
                print(
                    "paused=route_detail_blank_streak "
                    f"count={consecutive_detail_blank} last_id={activity_id}",
                    flush=True,
                )
                return 5
        else:
            consecutive_detail_blank = 0
        if status == "unknown":
            print(f"paused=unknown id={activity_id}", flush=True)
            return 4

    print(f"direct_completed successes={successes} attempts={attempts}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
