#!/usr/bin/env python3
"""Apply to one Dianping free-try activity through the Android app.

This is intentionally scoped to one activity ID per run. Filtering should be
done before calling this script.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_SERIAL = "emulator-5554"
DEFAULT_OUT_DIR = Path("/tmp")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def adb(serial: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["adb", "-s", serial, *args], check=check)


def screenshot(serial: str, path: Path) -> None:
    with path.open("wb") as handle:
        subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], check=True, stdout=handle)


def dump_ui(serial: str, path: Path) -> str:
    result = adb(serial, "exec-out", "uiautomator", "dump", "/dev/tty", check=False)
    path.write_text(result.stdout, encoding="utf-8", errors="replace")
    return result.stdout


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
        text = node.attrib.get("text") or ""
        desc = node.attrib.get("content-desc") or ""
        if text:
            values.append(text)
        if desc:
            values.append(desc)
    return "\n".join(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("activity_id")
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Open detail page only, do not tap apply/confirm.")
    parser.add_argument(
        "--no-coordinate-fallback",
        action="store_true",
        help="Stop if the confirmation sheet is not visible in UI XML instead of using tested coordinates.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    activity_id = args.activity_id
    serial = args.serial

    deeplink = (
        "dianping://picassobox?"
        "picassoid=pexus-freetry-detail%2Findex-bundle.js"
        f"&offlineActivityId={activity_id}"
        "&notitlebar=true"
    )

    adb(serial, "logcat", "-c")
    adb(
        serial,
        "shell",
        f"am start -a android.intent.action.VIEW -d {shlex.quote(deeplink)} -p com.dianping.v1",
    )
    time.sleep(8)
    screenshot(serial, args.out_dir / f"free_try_{activity_id}_detail.png")
    before_xml = dump_ui(serial, args.out_dir / f"free_try_{activity_id}_detail.xml")
    before_text = ui_text(before_xml)
    if args.dry_run:
        print("opened_detail")
        print(before_text[-2000:])
        return

    # Coordinates are derived from the tested 1080x2400 app layout. The Picasso
    # detail page sometimes returns malformed UI XML, so the bottom fixed CTA is
    # clicked by stable layout coordinate after opening a filtered activity.
    adb(serial, "shell", "input", "tap", "718", "2193")
    time.sleep(5)
    screenshot(serial, args.out_dir / f"free_try_{activity_id}_confirm.png")
    confirm_xml = dump_ui(serial, args.out_dir / f"free_try_{activity_id}_confirm.xml")
    confirm_text = ui_text(confirm_xml)
    print("after_apply_text")
    print(confirm_text[-2000:])

    confirm_detected = "确认报名信息" in confirm_text or "我已阅读" in confirm_text
    if not confirm_detected and args.no_coordinate_fallback:
        print("confirm_sheet_not_detected")
        return
    if not confirm_detected:
        print("confirm_sheet_not_detected_in_xml_using_coordinate_fallback")

    # Agree to rules and confirm.
    adb(serial, "shell", "input", "tap", "160", "2100")
    time.sleep(1)
    adb(serial, "shell", "input", "tap", "540", "2205")
    time.sleep(8)
    screenshot(serial, args.out_dir / f"free_try_{activity_id}_result.png")
    result_xml = dump_ui(serial, args.out_dir / f"free_try_{activity_id}_result.xml")
    result_text = ui_text(result_xml)
    print("result_text")
    print(result_text[-3000:])

    log_path = args.out_dir / f"free_try_{activity_id}_apply.log"
    log_path.write_text(adb(serial, "logcat", "-d").stdout, encoding="utf-8", errors="replace")

    if "报名成功" in result_text:
        print(f"APPLY_SUCCESS activity_id={activity_id}")
    else:
        print(f"APPLY_NOT_CONFIRMED activity_id={activity_id}")


if __name__ == "__main__":
    main()
