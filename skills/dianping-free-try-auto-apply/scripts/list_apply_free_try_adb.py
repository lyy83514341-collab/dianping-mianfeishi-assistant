#!/usr/bin/env python3
"""Apply to eligible Dianping free-try activities through visible list cards.

This is the preferred route while the free-try index is healthy. It taps the
same cards a user sees, resolves the actual offlineActivityId from the App's
own navigation log, applies the CSV policy, and pauses on human verification.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from batch_apply_free_try_adb import (
    DEFAULT_CSV,
    DEFAULT_SERIAL,
    DEFAULT_STATE,
    OFFICIAL_UNAVAILABLE_KEYWORDS,
    SECURITY_KEYWORDS,
    adb,
    dump_ui,
    ensure_agreement_checked,
    load_state,
    save_state,
    screenshot,
    ui_text,
)
from free_try_filter import build_row, cached_activity_detail, load_district_features

DEFAULT_OUT_DIR = Path("/tmp/free_try_list_batch")
LIST_DEEPLINK = (
    "dianping://picassobox?"
    "picassoid=pexus-freetry-index%2Findex-bundle.js&notitlebar=true"
)
ACTIVITY_ID_RE = re.compile(r"offlineactivityid(?:=|\"\s*:\s*\")(?P<id>\d+)", re.I)
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
TERMINAL_FAILURE_STATUSES = {
    "app_rejected",
    "not_eligible",
    "account_ineligible",
    "activity_ended",
}


@dataclass(frozen=True)
class UiNode:
    text: str
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2


@dataclass(frozen=True)
class VisibleCard:
    key: str
    title: str
    cta: UiNode


def parse_nodes(xmlish: str) -> list[UiNode]:
    start = xmlish.find("<hierarchy")
    end = xmlish.rfind("</hierarchy>")
    if start < 0 or end < 0:
        return []
    try:
        root = ET.fromstring(xmlish[start : end + len("</hierarchy>")])
    except ET.ParseError:
        return []
    nodes: list[UiNode] = []
    for raw in root.iter("node"):
        text = (raw.attrib.get("text") or raw.attrib.get("content-desc") or "").strip()
        match = BOUNDS_RE.fullmatch(raw.attrib.get("bounds") or "")
        if not text or not match:
            continue
        nodes.append(UiNode(text, tuple(map(int, match.groups()))))
    return nodes


def normalize_title(value: str) -> str:
    value = value.replace("￼", "").replace("|", "").replace("｜", "")
    return re.sub(r"[\s·•・]+", "", value)


def visible_cards(nodes: list[UiNode]) -> list[VisibleCard]:
    titles = [node for node in nodes if "套餐" in node.text and "元以上套餐" not in node.text]
    cards: list[VisibleCard] = []
    for cta in [node for node in nodes if node.text == "免费抽" and node.center[1] < 2200]:
        cx, cy = cta.center
        nearby = []
        for title in titles:
            tx, ty = title.center
            # In the list layout the CTA belongs to the nearest package title
            # above it. Considering titles below the CTA can bind the button to
            # the next card when vertical gaps are asymmetric.
            if 0 < cy - ty <= 300 and ty >= 900:
                nearby.append((cy - ty + abs(tx - cx) // 8, title))
        if not nearby:
            continue
        title_node = min(nearby, key=lambda item: item[0])[1]
        title = title_node.text
        # Coordinates change when registered cards disappear or the index is
        # reloaded.  Build a stable per-branch fingerprint from the package,
        # merchant/region and value text between its title and CTA instead.
        context = [
            normalize_title(node.text)
            for node in sorted(nodes, key=lambda item: item.center[1])
            if title_node.center[1] - 80 <= node.center[1] <= cy + 20
            and node.text != "免费抽"
        ]
        cards.append(VisibleCard("|".join(context), title, cta))
    return sorted(cards, key=lambda card: card.cta.bounds[1])


def tap_node(serial: str, node: UiNode) -> None:
    x, y = node.center
    adb(serial, "shell", "input", "tap", str(x), str(y))


def find_node(nodes: list[UiNode], *needles: str) -> UiNode | None:
    for needle in needles:
        exact = [node for node in nodes if node.text == needle]
        if exact:
            return exact[-1]
    for needle in needles:
        partial = [node for node in nodes if needle in node.text]
        if partial:
            return partial[-1]
    return None


def page(serial: str, out_dir: Path, name: str) -> tuple[list[UiNode], str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = ""
    text = ""
    for attempt in range(2):
        raw = dump_ui(serial, out_dir / f"{name}.xml")
        text = ui_text(raw)
        if "could not get idle state" not in text and "ERROR:" not in text:
            break
        time.sleep(0.8 + attempt * 0.4)
    (out_dir / f"{name}.txt").write_text(text, encoding="utf-8", errors="replace")
    return parse_nodes(raw), text


def timed(label: str, started: float) -> None:
    print(f"timing={label} seconds={time.monotonic() - started:.2f}", flush=True)


def count_pixels(image_path: Path, box: tuple[int, int, int, int], predicate: Any) -> int:
    image = Image.open(image_path).convert("RGB").crop(box)
    return sum(1 for pixel in image.getdata() if predicate(*pixel))


def confirmation_sheet_visible(image_path: Path) -> bool:
    orange = count_pixels(
        image_path,
        (40, 2100, 1040, 2330),
        lambda r, g, b: r > 225 and 55 <= g <= 175 and b < 125 and r - g > 65,
    )
    white = count_pixels(
        image_path,
        (40, 1500, 1040, 2050),
        lambda r, g, b: r > 235 and g > 235 and b > 235,
    )
    dimmed_header = count_pixels(
        image_path,
        (250, 80, 830, 210),
        lambda r, g, b: 70 <= r <= 180 and abs(r - g) < 12 and abs(g - b) < 12,
    )
    return orange > 3000 and white > 200000 and dimmed_header > 25000


def success_visible(image_path: Path) -> bool:
    green = count_pixels(
        image_path,
        (430, 170, 650, 430),
        lambda r, g, b: g > 125 and g > r * 1.35 and g > b * 1.2,
    )
    return green > 1200


def orange_detail_cta_visible(image_path: Path) -> bool:
    orange = count_pixels(
        image_path,
        (560, 2100, 1040, 2335),
        lambda r, g, b: r > 225 and 55 <= g <= 175 and b < 125 and r - g > 65,
    )
    return orange > 2500


def already_applied_detail_cta_visible(image_path: Path) -> bool:
    # The orange bottom button is shared by "我要报名" and the much longer
    # "已报名,看看其他活动".  Their geometry/color is identical, but the
    # long label has roughly twice as many white glyph pixels in this inner box
    # (observed 3757 vs 1872 on the verified 1080x2400 layout).
    white = count_pixels(
        image_path,
        (620, 2180, 1000, 2260),
        lambda r, g, b: r > 235 and g > 235 and b > 235,
    )
    return white > 3000


def wait_for_image(
    serial: str,
    path: Path,
    predicate: Any,
    timeout: float,
    poll: float = 0.45,
) -> bool:
    """Poll a cheap screenshot predicate without waiting for UIAutomator idle."""
    deadline = time.monotonic() + timeout
    while True:
        screenshot(serial, path)
        if predicate(path):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def security_present(text: str) -> bool:
    return any(keyword.lower() in text.lower() for keyword in SECURITY_KEYWORDS) or "滑块" in text or "拼图" in text


def open_list(serial: str, wait: float) -> None:
    adb(serial, "shell", f"am start -a android.intent.action.VIEW -d '{LIST_DEEPLINK}' -p com.dianping.v1")
    time.sleep(wait)


def route_retry_delay(base: float, attempt: int, cap: float = 30.0) -> float:
    """Return a bounded exponential delay for an index-only route failure."""
    return min(cap, max(0.0, base) * (2 ** max(0, attempt - 1)))


def extract_activity_id(serial: str) -> str:
    logs = adb(serial, "logcat", "-d", check=False).stdout
    current_detail_lines = [
        line
        for line in logs.splitlines()
        if "pageUrl:" in line and "pexus-freetry-detail" in line and "offlineactivityid" in line.lower()
    ]
    matches = [match for line in current_detail_lines for match in ACTIVITY_ID_RE.finditer(line)]
    return matches[-1].group("id") if matches else ""


def wait_for_activity_id(serial: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while True:
        activity_id = extract_activity_id(serial)
        if activity_id:
            return activity_id
        if time.monotonic() >= deadline:
            return ""
        time.sleep(0.25)


def load_candidates(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig") as handle:
        return {row.get("offlineActivityId", ""): row for row in csv.DictReader(handle)}


def eligible(row: dict[str, str] | None) -> bool:
    if not row or row.get("eligible") != "True":
        return False
    return row.get("activityType") == "1" or row.get("isFood") == "True"


def resolve_candidate(activity_id: str, candidates: dict[str, dict[str, str]]) -> dict[str, str] | None:
    row = candidates.get(activity_id)
    if row:
        return row
    try:
        cache_dir = Path(".cache")
        detail = cached_activity_detail(activity_id, cache_dir)
        shops = detail.get("activityShopInfoList") or []
        item = {
            "offlineActivityId": int(activity_id),
            "activityTitle": detail.get("title") or "",
            "regionName": (shops[0].get("mainRegionName") if shops else "") or "",
            "applyCount": detail.get("applyCount"),
            "hits": detail.get("followCount"),
        }
        built = build_row(
            0,
            item,
            load_district_features(cache_dir / "beijing_districts_datav.json"),
            cache_dir,
            False,
        )
        if str(detail.get("cityId") or "") != "2":
            built["eligible"] = False
            built["excludedReason"] = f"cityId:{detail.get('cityId')}"
        row = {key: str(value) if value is not None else "" for key, value in built.items()}
        row["eligible"] = "True" if built.get("eligible") else "False"
        row["isFood"] = "True" if built.get("isFood") else "False"
        candidates[activity_id] = row
        return row
    except Exception as exc:  # noqa: BLE001
        print(f"candidate_fallback_failed id={activity_id} error={exc!r}", flush=True)
        return None


def record_for(row: dict[str, str], status: str, note: str = "") -> dict[str, str]:
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "title": row.get("title", ""),
        "cost": row.get("cost", ""),
        "districts": row.get("districts", ""),
        "regionName": row.get("regionName", ""),
    }
    if note:
        record["note"] = note
    return record


def return_to_list(serial: str, wait: float, from_result: bool) -> bool:
    """Leave a verified result/detail without another expensive UI dump."""
    window = adb(serial, "shell", "dumpsys", "window", check=False).stdout
    if "YodaRouterTransparentActivity" in window:
        return False
    if from_result:
        # The verified result overlay has a fixed centered "查看更多活动" button.
        # A missed tap is harmless: the main-loop list recovery reopens the index.
        adb(serial, "shell", "input", "tap", "540", "758")
    else:
        adb(serial, "shell", "input", "keyevent", "4")
    time.sleep(min(wait, 1.2))
    return True


def submit_current_detail(
    serial: str,
    out_dir: Path,
    activity_id: str,
    row: dict[str, str],
    sheet_wait: float,
    result_wait: float,
    agreement_wait: float,
) -> tuple[str, str]:
    detail_text = ""
    detail_shot = out_dir / f"{activity_id}_detail.png"
    window = adb(serial, "shell", "dumpsys", "window", check=False).stdout
    if "YodaRouterTransparentActivity" in window:
        return "human_verification", detail_text
    detail_started = time.monotonic()
    detail_ready = wait_for_image(
        serial,
        detail_shot,
        orange_detail_cta_visible,
        timeout=max(1.0, sheet_wait * 4),
    )
    timed("detail_ready", detail_started)
    if detail_ready and already_applied_detail_cta_visible(detail_shot):
        return "already_applied", detail_text
    if not detail_ready:
        nodes, detail_text = page(serial, out_dir, f"{activity_id}_detail_fallback")
        if "报名成功" in detail_text or "已报名" in detail_text:
            return "already_applied", detail_text
        if security_present(detail_text):
            return "human_verification", detail_text
        if any(keyword in detail_text for keyword in OFFICIAL_UNAVAILABLE_KEYWORDS):
            return "official_unavailable", detail_text
        title = (row.get("title") or "").strip()
        generic_shell = all(marker in detail_text for marker in ("免费试活动详情", "适用商户", "活动流程"))
        if generic_shell and title and normalize_title(title) not in normalize_title(detail_text):
            return "detail_blank", detail_text
        apply_cta = find_node(nodes, "我要报名")
        if not apply_cta:
            return "detail_cta_missing", detail_text
        tap_node(serial, apply_cta)
    else:
        adb(serial, "shell", "input", "tap", "810", "2225")

    sheet_text = ""
    sheet_shot = out_dir / f"{activity_id}_sheet.png"
    sheet_started = time.monotonic()
    sheet_ready = wait_for_image(
        serial,
        sheet_shot,
        confirmation_sheet_visible,
        timeout=max(1.0, sheet_wait),
    )
    if not sheet_ready and orange_detail_cta_visible(sheet_shot):
        # Picasso occasionally drops the first CTA tap while the detail page is
        # still settling.  Retrying the detail CTA is idempotent because the
        # confirmation sheet has been pixel-verified as absent.
        print(f"retry=detail_cta id={activity_id}", flush=True)
        adb(serial, "shell", "input", "tap", "810", "2225")
        sheet_ready = wait_for_image(
            serial,
            sheet_shot,
            confirmation_sheet_visible,
            timeout=max(1.0, sheet_wait),
        )
    timed("sheet_ready", sheet_started)
    if not sheet_ready:
        sheet_nodes, sheet_text = page(serial, out_dir, f"{activity_id}_sheet_fallback")
        if security_present(sheet_text):
            return "human_verification", sheet_text
        if "确认报名信息" not in sheet_text and not find_node(sheet_nodes, "确认报名"):
            return "sheet_missing", sheet_text
    if not ensure_agreement_checked(serial, out_dir, activity_id, agreement_wait):
        return "agreement_not_checked", sheet_text
    adb(serial, "shell", "input", "tap", "540", "2205")

    result_text = ""
    result_shot = out_dir / f"{activity_id}_result.png"
    result_started = time.monotonic()
    result_ready = wait_for_image(
        serial,
        result_shot,
        success_visible,
        timeout=max(1.0, result_wait),
    )
    timed("result_ready", result_started)
    if result_ready:
        return "success", result_text
    if "YodaRouterTransparentActivity" in adb(serial, "shell", "dumpsys", "window", check=False).stdout:
        return "human_verification", result_text
    result_nodes, result_text = page(serial, out_dir, f"{activity_id}_result_fallback")
    if "报名成功" in result_text:
        return "success", result_text
    if "已报名" in result_text:
        return "already_applied", result_text
    if security_present(result_text):
        return "human_verification", result_text
    if any(keyword in result_text for keyword in OFFICIAL_UNAVAILABLE_KEYWORDS):
        return "official_unavailable", result_text
    return "unknown", result_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--max-success", type=int, default=20)
    parser.add_argument("--max-scrolls", type=int, default=40)
    parser.add_argument("--list-wait", type=float, default=2.0)
    parser.add_argument("--detail-wait", type=float, default=5.0)
    parser.add_argument("--sheet-wait", type=float, default=2.5)
    parser.add_argument("--result-wait", type=float, default=4.5)
    parser.add_argument("--agreement-tap-wait", type=float, default=0.45)
    parser.add_argument(
        "--route-unavailable-retries",
        type=int,
        default=3,
        help="Reopen a busy/network-error list this many times before falling back.",
    )
    parser.add_argument(
        "--route-unavailable-backoff",
        type=float,
        default=5.0,
        help="Initial exponential backoff in seconds for list-route recovery.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Open and classify visible cards without submitting.")
    parser.add_argument("--skip-failed", action="store_true")
    args = parser.parse_args()
    if args.route_unavailable_retries < 0:
        parser.error("--route-unavailable-retries must be >= 0")
    if args.route_unavailable_backoff < 0:
        parser.error("--route-unavailable-backoff must be >= 0")

    state: dict[str, Any] = load_state(args.state)
    candidates = load_candidates(args.csv)
    attempted_cards: set[str] = set()
    successes = 0
    scrolls = 0
    stagnant = 0
    last_signature = ""
    list_recoveries = 0
    route_unavailable_recoveries = 0

    open_list(args.serial, args.list_wait)
    while successes < args.max_success and scrolls <= args.max_scrolls:
        nodes, list_text = page(args.serial, args.out_dir, f"list_{scrolls}_{len(attempted_cards)}")
        screenshot(args.serial, args.out_dir / "latest_list.png")
        if security_present(list_text):
            print("paused=human_verification page=list", flush=True)
            return 2
        if "YodaRouterTransparentActivity" in adb(
            args.serial, "shell", "dumpsys", "window", check=False
        ).stdout:
            print("paused=human_verification page=list_window", flush=True)
            return 2
        unavailable_reason = next(
            (keyword for keyword in ("当前活动太火爆", "网络异常") if keyword in list_text),
            "",
        )
        if unavailable_reason:
            if route_unavailable_recoveries < args.route_unavailable_retries:
                route_unavailable_recoveries += 1
                delay = route_retry_delay(
                    args.route_unavailable_backoff,
                    route_unavailable_recoveries,
                )
                print(
                    "recover=route_unavailable "
                    f"attempt={route_unavailable_recoveries}/{args.route_unavailable_retries} "
                    f"backoff={delay:.1f} reason={unavailable_reason}",
                    flush=True,
                )
                time.sleep(delay)
                open_list(args.serial, args.list_wait)
                scrolls = 0
                stagnant = 0
                last_signature = ""
                continue
            print(
                "route_unavailable=list "
                f"retries={route_unavailable_recoveries} reason={unavailable_reason}",
                flush=True,
            )
            return 3
        if "全部商区" not in list_text:
            if list_recoveries < 2:
                list_recoveries += 1
                print(
                    f"recover=reload_list attempt={list_recoveries} text={list_text[-80:]!r}",
                    flush=True,
                )
                open_list(args.serial, args.list_wait)
                continue
            print("paused=unexpected_list_state", flush=True)
            return 4
        list_recoveries = 0

        cards = visible_cards(nodes)
        card = next((item for item in cards if item.key not in attempted_cards), None)
        if not card:
            visible_titles = [
                f"{normalize_title(node.text)}@{node.bounds[1]}"
                for node in nodes
                if ("套餐" in node.text or "单人餐" in node.text) and node.bounds[1] >= 400
            ]
            signature = "|".join(visible_titles)
            stagnant = stagnant + 1 if signature == last_signature else 0
            last_signature = signature
            if stagnant >= 3:
                print(f"completed=no_more_visible_cards successes={successes}", flush=True)
                return 0
            adb(args.serial, "shell", "input", "swipe", "540", "2100", "540", "1000", "500")
            time.sleep(0.75)
            scrolls += 1
            continue

        attempted_cards.add(card.key)
        card_started = time.monotonic()
        adb(args.serial, "logcat", "-c")
        tap_node(args.serial, card.cta)
        navigation_started = time.monotonic()
        activity_id = wait_for_activity_id(args.serial, args.detail_wait)
        timed("activity_id", navigation_started)
        if not activity_id:
            print(f"skip=missing_activity_id card={card.title}", flush=True)
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue

        row = resolve_candidate(activity_id, candidates)
        print(
            f"card={card.title} id={activity_id} eligible={eligible(row)} "
            f"known={bool(row)}",
            flush=True,
        )
        if activity_id in (state.get("success") or {}):
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue
        previous_failure = (state.get("failed") or {}).get(activity_id) or {}
        if args.skip_failed and previous_failure.get("status") in TERMINAL_FAILURE_STATUSES:
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue
        if not eligible(row):
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue
        assert row is not None
        if args.dry_run:
            print(f"dry_run=eligible id={activity_id} title={row.get('title')}", flush=True)
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue

        status, text = submit_current_detail(
            args.serial,
            args.out_dir,
            activity_id,
            row,
            args.sheet_wait,
            args.result_wait,
            args.agreement_tap_wait,
        )
        print(f"id={activity_id} status={status}", flush=True)
        timed(f"card_total id={activity_id}", card_started)
        if status in {"success", "already_applied"}:
            state.setdefault("success", {})[activity_id] = record_for(row, "success", "visible list-card route")
            state.get("failed", {}).pop(activity_id, None)
            state.get("paused", {}).pop(activity_id, None)
            save_state(args.state, state)
            successes += 1
            if not return_to_list(args.serial, args.list_wait, status == "success"):
                print(f"paused=human_verification_after_success id={activity_id}", flush=True)
                return 2
            continue
        if status == "human_verification":
            state.setdefault("paused", {})[activity_id] = record_for(row, status, "user action required; rerun after completion")
            save_state(args.state, state)
            print(f"paused=human_verification id={activity_id}", flush=True)
            return 2
        if status in {"official_unavailable", "detail_blank"}:
            state.setdefault("failed", {})[activity_id] = record_for(row, status)
            save_state(args.state, state)
            adb(args.serial, "shell", "input", "keyevent", "4")
            time.sleep(1.2)
            continue

        state.setdefault("paused", {})[activity_id] = record_for(row, status, text[-300:])
        save_state(args.state, state)
        print(f"paused={status} id={activity_id}", flush=True)
        return 4

    print(f"completed=max_success_or_scroll_limit successes={successes}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
