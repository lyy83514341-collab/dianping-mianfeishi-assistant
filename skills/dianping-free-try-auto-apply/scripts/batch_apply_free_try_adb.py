#!/usr/bin/env python3
"""Sequentially apply to filtered Dianping free-try activities through Android UI.

This script intentionally runs one activity at a time, with a delay between
activities, and stops on verification/security pages.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

DEFAULT_SERIAL = "emulator-5554"
DEFAULT_CSV = Path("reports/free_try_candidates_beijing.csv")
DEFAULT_STATE = Path("reports/free_try_apply_state.json")
DEFAULT_OUT_DIR = Path("/tmp/free_try_batch")
SECURITY_KEYWORDS = ["验证码", "身份验证", "账号安全", "支付密码", "人脸", "Yoda", "登录"]
OFFICIAL_UNAVAILABLE_KEYWORDS = [
    "当前活动太火爆",
    "活动太火爆",
    "请稍后再试",
    "稍后再试",
    "服务繁忙",
    "系统繁忙",
]


def run(
    cmd: list[str],
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def adb(
    serial: str,
    *args: str,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["adb", "-s", serial, *args]
    last: subprocess.CalledProcessError | None = None
    for attempt in range(3):
        try:
            return run(cmd, check=check, timeout=timeout)
        except subprocess.CalledProcessError as exc:
            if not check:
                return exc
            last = exc
            if attempt < 2:
                time.sleep(1.0 + attempt)
                continue
            raise
    raise last  # type: ignore[misc]


def screenshot(serial: str, path: Path) -> None:
    with path.open("wb") as handle:
        subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], check=True, stdout=handle)


def agreement_checked(image_path: Path) -> bool:
    image = Image.open(image_path).convert("RGB")
    # Checkbox crop for 1080x2400 layout.
    crop = image.crop((105, 2045, 190, 2140))
    orange = 0
    for r, g, b in crop.getdata():
        if r > 220 and 55 <= g <= 170 and b < 120 and r - g > 70:
            orange += 1
    return orange > 80


def ensure_agreement_checked(serial: str, out_dir: Path, activity_id: str, tap_wait: float) -> bool:
    # The App can remember the agreement selection across consecutive
    # applications. Never blindly toggle an already-selected checkbox off.
    initial_shot = out_dir / f"{activity_id}_agreement_initial.png"
    screenshot(serial, initial_shot)
    if agreement_checked(initial_shot):
        return True
    # Several adjacent points are tried because the custom Picasso checkbox has
    # a small hit target and occasionally drops taps during sheet animation.
    candidates = [(140, 2090), (160, 2090), (180, 2090), (300, 2090), (300, 2100)]
    for idx, (x, y) in enumerate(candidates, 1):
        adb(serial, "shell", "input", "tap", str(x), str(y))
        time.sleep(tap_wait)
        shot = out_dir / f"{activity_id}_agreement_{idx}.png"
        screenshot(serial, shot)
        if agreement_checked(shot):
            return True
        # If the tap did not select it, do not tap again on the same point;
        # moving to a new point avoids accidental double toggles.
    return False


def dump_ui(serial: str, path: Path) -> str:
    # Picasso pages contain countdowns and animations that can keep Android's
    # accessibility tree from ever reaching an "idle" state.  An unbounded
    # uiautomator call has blocked a batch for many minutes, so UI text is a
    # bounded fallback; screenshot predicates are the primary signal.
    try:
        result = adb(
            serial,
            "exec-out",
            "sh",
            "-c",
            "timeout 4 uiautomator dump /dev/tty",
            check=False,
            timeout=5.5,
        )
        raw = result.stdout
    except subprocess.TimeoutExpired:
        raw = "ERROR: uiautomator dump timed out after 5.5s"
    path.write_text(raw, encoding="utf-8", errors="replace")
    return raw


def ui_text(xmlish: str) -> str:
    start = xmlish.find("<hierarchy")
    end = xmlish.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return xmlish
    xml_text = xmlish[start : end + len("</hierarchy>")]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xmlish
    values = []
    for node in root.iter("node"):
        for key in ("text", "content-desc"):
            value = node.attrib.get(key) or ""
            if value:
                values.append(value)
    return "\n".join(values)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"success": {}, "failed": {}}
    return json.loads(path.read_text())


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def eligible_rows(
    csv_path: Path,
    state: dict[str, Any],
    extra_skip: set[str],
    food_only: bool = False,
    skip_failed: bool = False,
) -> list[dict[str, str]]:
    success = set((state.get("success") or {}).keys())
    failed = set((state.get("failed") or {}).keys()) if skip_failed else set()
    rows = []
    with csv_path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            activity_id = row.get("offlineActivityId") or ""
            if row.get("eligible") != "True":
                continue
            if food_only and not (row.get("activityType") == "1" or row.get("isFood") == "True"):
                continue
            if activity_id in success or activity_id in failed or activity_id in extra_skip:
                continue
            rows.append(row)
    return rows


def open_detail(serial: str, activity_id: str, force_stop: bool = False) -> None:
    if force_stop:
        adb(serial, "shell", "am", "force-stop", "com.dianping.v1")
        time.sleep(1.0)
    deeplink = (
        "dianping://picassobox?"
        "picassoid=pexus-freetry-detail%2Findex-bundle.js"
        f"&offlineActivityId={activity_id}"
        "&notitlebar=true"
    )
    adb(serial, "shell", f"am start -a android.intent.action.VIEW -d {shlex.quote(deeplink)} -p com.dianping.v1")


def apply_one(
    serial: str,
    out_dir: Path,
    row: dict[str, str],
    waits: dict[str, float],
    save_logcat: bool,
    save_result_screenshot: bool,
    force_stop_before_open: bool,
    precheck_detail: bool,
) -> tuple[str, str]:
    activity_id = row["offlineActivityId"]
    out_dir.mkdir(parents=True, exist_ok=True)
    if save_logcat:
        adb(serial, "logcat", "-c")
    open_detail(serial, activity_id, force_stop=force_stop_before_open)
    time.sleep(waits["detail"])

    if precheck_detail:
        detail_xml_path = out_dir / f"{activity_id}_detail.xml"
        detail_text = ui_text(dump_ui(serial, detail_xml_path))
        (out_dir / f"{activity_id}_detail_text.txt").write_text(detail_text, encoding="utf-8", errors="replace")
        if "已报名" in detail_text or "报名成功" in detail_text:
            return "already_applied", detail_text
        if any(keyword in detail_text for keyword in SECURITY_KEYWORDS):
            return "security_stop", detail_text
        if any(keyword in detail_text for keyword in OFFICIAL_UNAVAILABLE_KEYWORDS):
            return "official_unavailable_stop", detail_text
        # A Picasso detail page can render its static shell (title, price label,
        # merchant section and tabs) while the actual activity payload never
        # arrives. Do not tap the fixed CTA in that state: it is not an
        # agreement-checkbox problem and can never become a valid submission.
        generic_shell = all(marker in detail_text for marker in ("免费试活动详情", "适用商户", "活动流程"))
        activity_title = (row.get("title") or "").strip()
        if generic_shell and activity_title and activity_title not in detail_text:
            return "detail_blank", "activity payload did not load; only the static detail shell is visible"

    # Fixed bottom CTA in the tested 1080x2400 layout. The active button is
    # right-aligned on some detail templates; tapping its visual center is more
    # reliable than the older left-side coordinate.
    adb(serial, "shell", "input", "tap", "810", "2225")
    time.sleep(waits["sheet"])

    # Confirmation sheet: agree to rules, verified by screenshot pixel state.
    if not ensure_agreement_checked(serial, out_dir, activity_id, waits["agreement_tap"]):
        screenshot(serial, out_dir / f"{activity_id}_agreement_failed.png")
        return "agreement_not_checked", "agreement checkbox did not become selected"
    adb(serial, "shell", "input", "tap", "540", "2205")
    time.sleep(waits["result"])

    xml_path = out_dir / f"{activity_id}_result.xml"
    text = ui_text(dump_ui(serial, xml_path))
    if "could not get idle state" in text or "ERROR:" in text:
        time.sleep(2.5)
        text = ui_text(dump_ui(serial, xml_path))
    if "报名成功" not in text and ("确认报名信息" in text or "确认报名" in text):
        # Occasionally the first confirm tap lands before the button becomes active.
        adb(serial, "shell", "input", "tap", "540", "2205")
        time.sleep(waits["retry_result"])
        text = ui_text(dump_ui(serial, xml_path))
        if "could not get idle state" in text or "ERROR:" in text:
            time.sleep(2.5)
            text = ui_text(dump_ui(serial, xml_path))

    if save_result_screenshot:
        screenshot(serial, out_dir / f"{activity_id}_result.png")
    (out_dir / f"{activity_id}_text.txt").write_text(text, encoding="utf-8", errors="replace")
    if save_logcat:
        (out_dir / f"{activity_id}_logcat.txt").write_text(adb(serial, "logcat", "-d").stdout, encoding="utf-8", errors="replace")

    if "报名成功" in text:
        return "success", text
    if "已报名" in text:
        return "already_applied", text
    if any(keyword in text for keyword in SECURITY_KEYWORDS):
        return "security_stop", text
    if any(keyword in text for keyword in OFFICIAL_UNAVAILABLE_KEYWORDS):
        return "official_unavailable_stop", text
    return "unknown", text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--max-apply", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--skip", default="1349529257,1838507997")
    parser.add_argument(
        "--skip-failed",
        action="store_true",
        help="Skip activities already recorded as failed in this state file and continue with the next eligible activity.",
    )
    parser.add_argument("--food-only", action="store_true")
    parser.add_argument("--detail-wait", type=float, default=3.2)
    parser.add_argument("--sheet-wait", type=float, default=2.4)
    parser.add_argument("--agreement-tap-wait", type=float, default=0.45)
    parser.add_argument("--result-wait", type=float, default=4.2)
    parser.add_argument("--retry-result-wait", type=float, default=2.8)
    parser.add_argument("--save-logcat", action="store_true")
    parser.add_argument("--save-result-screenshot", action="store_true")
    parser.add_argument("--force-stop-before-open", action="store_true")
    parser.add_argument("--precheck-detail", action="store_true")
    args = parser.parse_args()

    state = load_state(args.state)
    extra_skip = {item.strip() for item in args.skip.split(",") if item.strip()}
    rows = eligible_rows(
        args.csv,
        state,
        extra_skip,
        food_only=args.food_only,
        skip_failed=args.skip_failed,
    )
    rows = rows[: args.max_apply]
    waits = {
        "detail": args.detail_wait,
        "sheet": args.sheet_wait,
        "agreement_tap": args.agreement_tap_wait,
        "result": args.result_wait,
        "retry_result": args.retry_result_wait,
    }

    print(f"planned={len(rows)} max_apply={args.max_apply}")
    for index, row in enumerate(rows, 1):
        activity_id = row["offlineActivityId"]
        print(
            f"[{index}/{len(rows)}] applying {activity_id} cost={row.get('cost')} "
            f"district={row.get('districts')} region={row.get('regionName')} title={row.get('title')}",
            flush=True,
        )
        status, text = apply_one(
            args.serial,
            args.out_dir,
            row,
            waits,
            save_logcat=args.save_logcat,
            save_result_screenshot=args.save_result_screenshot,
            force_stop_before_open=args.force_stop_before_open,
            precheck_detail=args.precheck_detail,
        )
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "title": row.get("title"),
            "cost": row.get("cost"),
            "districts": row.get("districts"),
            "regionName": row.get("regionName"),
        }
        if status in {"success", "already_applied"}:
            state.setdefault("success", {})[activity_id] = record
        else:
            state.setdefault("failed", {})[activity_id] = record
        save_state(args.state, state)
        print(f"[{index}/{len(rows)}] status={status}", flush=True)
        if status == "security_stop":
            print("stopping_on_security_page", flush=True)
            break
        if status == "official_unavailable_stop":
            print("stopping_on_official_unavailable_or_rate_limit", flush=True)
            break
        if status == "unknown":
            print("stopping_on_unknown_state", flush=True)
            print(text[-1000:], flush=True)
            break
        if index < len(rows):
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
