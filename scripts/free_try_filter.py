#!/usr/bin/env python3
"""Fetch and filter Beijing Dianping free-try activities.

Filters:
- package value/cost >= 200
- Tongzhou food package value/cost >= 150
- skip activities whose shops are in excluded Beijing districts

The script is read-only against Dianping APIs. It does not submit applications.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CITY_ID = 2
MIN_COST = 200
TONGZHOU_FOOD_MIN_COST = 150

EXCLUDED_DISTRICTS = {
    "房山区",
    "门头沟区",
    "怀柔区",
    "平谷区",
    "密云区",
    "延庆区",
    "昌平区",
    "石景山区",
}

EXCLUDED_TEXT_KEYWORDS = {
    "房山区": ["房山", "良乡", "长阳", "窦店", "阎村", "燕山", "篱笆房", "拱辰", "韩村河", "琉璃河", "周口店"],
    "门头沟区": ["门头沟", "双峪", "龙泉", "永定", "冯村", "大峪", "石门营"],
    "怀柔区": ["怀柔", "雁栖", "庙城", "杨宋"],
    "平谷区": ["平谷", "金海湖", "马坊"],
    "密云区": ["密云", "古北水镇", "司马台"],
    "延庆区": ["延庆", "八达岭", "康庄"],
    "昌平区": ["昌平", "回龙观", "天通苑", "霍营", "沙河", "北七家", "南邵", "朱辛庄", "生命科学园", "十三陵", "小汤山"],
    "石景山区": ["石景山", "苹果园", "古城", "八角", "鲁谷", "金安桥", "杨庄", "模式口", "五里坨", "八大处"],
}

LIST_URL = "https://m.dianping.com/activity/static/pc/ajaxList"
DETAIL_URL = "https://m.dianping.com/bwc/customer/bwcDetailPackage"
GEOJSON_URL = "https://geo.datav.aliyun.com/areas_v3/bound/110000_full.json"

LIST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://m.dianping.com/activity/static/pc/list",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

DETAIL_HEADERS = {
    "User-Agent": LIST_HEADERS["User-Agent"],
    "Referer": "https://h5.dianping.com/app/app-community-free-meal/detail.html",
}


def post_json(url: str, obj: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers=LIST_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def post_form(url: str, obj: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(obj).encode(), headers=DETAIL_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": LIST_HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def list_page(page: int) -> tuple[list[dict[str, Any]], bool]:
    payload = {"cityId": CITY_ID, "page": page}
    result = post_json(LIST_URL, payload)
    data = result.get("data") or {}
    return data.get("detail") or [], bool(data.get("hasNext"))


def activity_detail(activity_id: int | str) -> dict[str, Any]:
    payload = {
        "id": str(activity_id),
        "offlineActivityId": str(activity_id),
        "busiType": "0",
        "env": "0",
        "lat": "",
        "lng": "",
        "cityId": str(CITY_ID),
        "appCityId": str(CITY_ID),
        "uuidSwitch": "false",
    }
    result = post_form(DETAIL_URL, payload)
    if result.get("code") != 200:
        raise RuntimeError(result)
    return result.get("data") or {}


def cached_activity_detail(activity_id: int | str, cache_dir: Path, refresh: bool = False) -> dict[str, Any]:
    detail_dir = cache_dir / "details"
    detail_path = detail_dir / f"{activity_id}.json"
    if detail_path.exists() and not refresh:
        return json.loads(detail_path.read_text())

    detail = activity_detail(activity_id)
    detail_dir.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(json.dumps(detail, ensure_ascii=False))
    return detail


def point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        xi, yi = point[0], point[1]
        xj, yj = ring[j][0], ring[j][1]
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            x_intersect = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lng < x_intersect:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lng: float, lat: float, coordinates: Any) -> bool:
    # Polygon: [outer, hole1, ...]. MultiPolygon: [[outer, ...], ...]
    if not coordinates:
        return False
    if isinstance(coordinates[0][0][0], (int, float)):
        polygons = [coordinates]
    else:
        polygons = coordinates
    for polygon in polygons:
        outer = polygon[0]
        if not point_in_ring(lng, lat, outer):
            continue
        in_hole = any(point_in_ring(lng, lat, hole) for hole in polygon[1:])
        if not in_hole:
            return True
    return False


def load_district_features(cache_path: Path) -> list[dict[str, Any]]:
    if cache_path.exists():
        geo = json.loads(cache_path.read_text())
    else:
        geo = fetch_json(GEOJSON_URL)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(geo, ensure_ascii=False))
    return geo.get("features") or []


def district_for_point(lng: Any, lat: Any, features: list[dict[str, Any]]) -> str:
    if lng in (None, "") or lat in (None, ""):
        return ""
    try:
        lng_f = float(lng)
        lat_f = float(lat)
    except (TypeError, ValueError):
        return ""
    for feature in features:
        geometry = feature.get("geometry") or {}
        if point_in_polygon(lng_f, lat_f, geometry.get("coordinates")):
            return (feature.get("properties") or {}).get("name") or ""
    return ""


def excluded_by_text(text: str) -> list[str]:
    hits = []
    for district, keywords in EXCLUDED_TEXT_KEYWORDS.items():
        for keyword in keywords:
            if keyword and keyword in text:
                hits.append(f"{district}:text:{keyword}")
                break
    return hits


def classify(detail: dict[str, Any], list_item: dict[str, Any], features: list[dict[str, Any]]) -> tuple[list[str], str, str]:
    shops = detail.get("activityShopInfoList") or []
    text_parts = [str(list_item.get("regionName") or ""), str(detail.get("title") or "")]
    shop_summaries = []
    district_names = []
    reasons = []

    for shop in shops:
        district = district_for_point(shop.get("glng"), shop.get("glat"), features)
        if district:
            district_names.append(district)
            if district in EXCLUDED_DISTRICTS:
                reasons.append(f"{district}:coord")
        parts = [shop.get("shopName"), shop.get("branchName"), shop.get("mainRegionName"), shop.get("address")]
        text = " ".join(str(part or "") for part in parts)
        text_parts.append(text)
        shop_summaries.append(
            "/".join(str(part or "") for part in [shop.get("shopName"), shop.get("branchName"), shop.get("mainRegionName"), shop.get("address")])
        )

    reasons.extend(excluded_by_text(" ".join(text_parts)))
    deduped_reasons = list(dict.fromkeys(reasons))
    deduped_districts = list(dict.fromkeys(district_names))
    return deduped_reasons, "、".join(deduped_districts), " | ".join(shop_summaries[:8])


def shop_categories(detail: dict[str, Any]) -> str:
    categories = []
    for shop in detail.get("activityShopInfoList") or []:
        category = shop.get("mainCategoryName")
        if category and category not in categories:
            categories.append(str(category))
    return "、".join(categories)


def eligible_rule(cost: int, activity_type: Any, districts: str, excluded_reasons: list[str]) -> tuple[bool, str]:
    if excluded_reasons:
        return False, ""
    is_food = activity_type == 1
    if cost >= MIN_COST:
        return True, "standard_cost_gte_200"
    if is_food and cost >= TONGZHOU_FOOD_MIN_COST and "通州区" in districts:
        return True, "tongzhou_food_cost_gte_150"
    return False, ""


def build_row(
    page: int,
    item: dict[str, Any],
    features: list[dict[str, Any]],
    cache_dir: Path,
    refresh_details: bool,
) -> dict[str, Any]:
    activity_id = item["offlineActivityId"]
    base = {
        "page": page,
        "offlineActivityId": activity_id,
        "title": item.get("activityTitle"),
        "cost": 0,
        "regionName": item.get("regionName") or "",
        "districts": "",
        "excludedReason": "",
        "eligible": False,
        "applyCount": item.get("applyCount"),
        "hits": item.get("hits"),
        "shops": "",
        "h5Url": f"https://h5.dianping.com/app/app-community-free-meal/detail.html?offlineActivityId={activity_id}",
    }
    try:
        detail = cached_activity_detail(activity_id, cache_dir, refresh=refresh_details)
        cost = int(float(detail.get("cost") or 0))
        reasons, districts, shop_summary = classify(detail, item, features)
        activity_type = detail.get("type")
        eligible, rule = eligible_rule(cost, activity_type, districts, reasons)
        base.update(
            {
                "title": detail.get("title") or base["title"],
                "cost": cost,
                "activityType": activity_type,
                "isFood": activity_type == 1,
                "mainCategories": shop_categories(detail),
                "districts": districts,
                "excludedReason": ";".join(reasons),
                "eligible": eligible,
                "eligibilityRule": rule,
                "applyBeginTime": detail.get("applyBeginTime"),
                "applyEndTime": detail.get("applyEndTime"),
                "beginTime": detail.get("beginTime"),
                "endTime": detail.get("endTime"),
                "shops": shop_summary,
            }
        )
    except Exception as exc:  # noqa: BLE001
        base["excludedReason"] = f"detail_error:{exc!r}"
    return base


def collect(max_pages: int, out_csv: Path, cache_dir: Path, workers: int, refresh_details: bool) -> list[dict[str, Any]]:
    features = load_district_features(cache_dir / "beijing_districts_datav.json")

    listed: list[tuple[int, dict[str, Any]]] = []
    seen = set()
    for page in range(1, max_pages + 1):
        items, has_next = list_page(page)
        if not items:
            break
        for item in items:
            activity_id = item.get("offlineActivityId")
            if activity_id in seen:
                continue
            seen.add(activity_id)
            listed.append((page, item))
        if not has_next:
            break
        time.sleep(0.15)

    rows: list[dict[str, Any]] = []
    if workers <= 1:
        for page, item in listed:
            rows.append(build_row(page, item, features, cache_dir, refresh_details))
            time.sleep(0.03)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(build_row, page, item, features, cache_dir, refresh_details)
                for page, item in listed
            ]
            for idx, future in enumerate(futures, 1):
                rows.append(future.result())
                if idx % 50 == 0:
                    print(f"details_processed={idx}/{len(futures)}", flush=True)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "eligible",
        "eligibilityRule",
        "offlineActivityId",
        "title",
        "cost",
        "activityType",
        "isFood",
        "mainCategories",
        "regionName",
        "districts",
        "excludedReason",
        "applyCount",
        "hits",
        "applyBeginTime",
        "applyEndTime",
        "beginTime",
        "endTime",
        "shops",
        "h5Url",
        "page",
    ]
    with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("reports/free_try_candidates_beijing.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--refresh-details", action="store_true")
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    rows = collect(args.max_pages, args.out, args.cache_dir, args.workers, args.refresh_details)
    eligible = [row for row in rows if row.get("eligible")]
    print(f"total={len(rows)} eligible={len(eligible)} csv={args.out}")
    for row in eligible[: args.top]:
        print(
            f"{row['offlineActivityId']} cost={row['cost']} district={row['districts']} "
            f"region={row['regionName']} title={row['title']}"
        )


if __name__ == "__main__":
    main()
