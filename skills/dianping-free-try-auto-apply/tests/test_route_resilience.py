from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import direct_apply_free_try_adb as direct_route  # noqa: E402
import list_apply_free_try_adb as list_route  # noqa: E402
import run_free_try_auto as auto_route  # noqa: E402


CSV_FIELDS = [
    "offlineActivityId",
    "eligible",
    "activityType",
    "title",
    "cost",
    "districts",
    "regionName",
]


def write_candidates(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for activity_id in range(1, count + 1):
            writer.writerow(
                {
                    "offlineActivityId": str(activity_id),
                    "eligible": "True",
                    "activityType": "1",
                    "title": f"candidate-{activity_id}",
                    "cost": "200",
                    "districts": "朝阳区",
                    "regionName": "test",
                }
            )


class ListRouteRecoveryTests(unittest.TestCase):
    def run_route(self, page_texts: list[str], retries: int) -> tuple[int, mock.Mock]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            csv_path = temp / "candidates.csv"
            state_path = temp / "state.json"
            write_candidates(csv_path, 0)
            state_path.write_text('{"success": {}, "failed": {}, "paused": {}}')
            open_list = mock.Mock()
            args = [
                "list_apply_free_try_adb.py",
                "--csv",
                str(csv_path),
                "--state",
                str(state_path),
                "--out-dir",
                str(temp / "out"),
                "--max-scrolls",
                "0",
                "--route-unavailable-retries",
                str(retries),
                "--route-unavailable-backoff",
                "0",
                "--dry-run",
            ]
            with (
                mock.patch.object(sys, "argv", args),
                mock.patch.object(list_route, "open_list", open_list),
                mock.patch.object(
                    list_route,
                    "page",
                    side_effect=[([], text) for text in page_texts],
                ),
                mock.patch.object(list_route, "screenshot"),
                mock.patch.object(
                    list_route,
                    "adb",
                    return_value=SimpleNamespace(stdout=""),
                ),
                mock.patch.object(list_route.time, "sleep"),
            ):
                result = list_route.main()
            return result, open_list

    def test_busy_list_recovers_before_fallback(self) -> None:
        result, open_list = self.run_route(
            ["当前活动太火爆", "网络异常", "全部商区"],
            retries=2,
        )
        self.assertEqual(result, 0)
        self.assertEqual(open_list.call_count, 3)

    def test_busy_list_falls_back_after_retry_budget(self) -> None:
        result, open_list = self.run_route(
            ["当前活动太火爆"] * 3,
            retries=2,
        )
        self.assertEqual(result, 3)
        self.assertEqual(open_list.call_count, 3)

    def test_retry_delay_is_bounded_exponential(self) -> None:
        self.assertEqual(
            [list_route.route_retry_delay(5, attempt) for attempt in range(1, 5)],
            [5, 10, 20, 30],
        )


class DirectRouteCircuitTests(unittest.TestCase):
    def test_recent_blank_rows_are_deprioritized(self) -> None:
        candidates = {
            str(activity_id): {
                "offlineActivityId": str(activity_id),
                "eligible": "True",
                "activityType": "1",
            }
            for activity_id in range(1, 5)
        }
        state = {
            "success": {},
            "failed": {},
            "paused": {"1": {"status": "detail_blank"}},
        }
        planned = direct_route.planned_rows(candidates, state)
        self.assertEqual([row["offlineActivityId"] for row in planned], ["2", "3", "4", "1"])

    def test_three_consecutive_blank_details_pause_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            csv_path = temp / "candidates.csv"
            state_path = temp / "state.json"
            write_candidates(csv_path, 5)
            state_path.write_text(
                json.dumps({"success": {}, "failed": {}, "paused": {}}),
                encoding="utf-8",
            )
            submit = mock.Mock(return_value=("detail_blank", ""))
            args = [
                "direct_apply_free_try_adb.py",
                "--csv",
                str(csv_path),
                "--state",
                str(state_path),
                "--out-dir",
                str(temp / "out"),
                "--detail-wait",
                "0",
                "--max-consecutive-detail-blank",
                "3",
            ]
            with (
                mock.patch.object(sys, "argv", args),
                mock.patch.object(direct_route, "open_detail"),
                mock.patch.object(direct_route, "submit_current_detail", submit),
                mock.patch.object(direct_route.time, "sleep"),
            ):
                result = direct_route.main()
            self.assertEqual(result, 5)
            self.assertEqual(submit.call_count, 3)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["paused"]), 3)


class AutoRouteVerificationTests(unittest.TestCase):
    def test_retryable_direct_pause_still_runs_one_verification_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            csv_path = temp / "candidates.csv"
            state_path = temp / "state.json"
            write_candidates(csv_path, 1)
            state_path.write_text(
                json.dumps({"success": {}, "failed": {}, "paused": {}}),
                encoding="utf-8",
            )
            args = [
                "run_free_try_auto.py",
                "--skip-daily-scan",
                "--csv",
                str(csv_path),
                "--state",
                str(state_path),
            ]
            with (
                mock.patch.object(sys, "argv", args),
                mock.patch.object(
                    auto_route,
                    "apply_routes",
                    side_effect=[auto_route.RETRYABLE_ROUTE_PAUSE] * 2,
                ) as apply_routes,
                mock.patch.object(auto_route, "scan_current_day", return_value=0) as scan,
            ):
                result = auto_route.main()
            self.assertEqual(result, 4)
            self.assertEqual(apply_routes.call_count, 2)
            scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
