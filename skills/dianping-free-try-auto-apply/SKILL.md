---
name: dianping-free-try-auto-apply
description: "End-to-end Android emulator workflow for the user's own Dianping free-try automation: set up a macOS Android emulator, install/login Dianping and WeChat, scan Beijing free-try activities, filter food packages by the user's default rules, and apply through the Dianping app with ADB UI automation. Use when asked to continue, set up, troubleshoot, rescan, or run this Dianping 免费试 / 霸王餐报名 workflow."
---

# Dianping free-try auto apply

## Default policy

Use this skill only for the user's own account and normal official app flow. Do not bypass captcha, face verification, payment password, SMS, login, or account-security pages. If any of those appear, stop and ask the user.

Default filter rules:

- City: Beijing, `cityId=2`.
- Category: food only, Dianping detail `type=1`.
- Exclude districts: 房山区、门头沟区、怀柔区、平谷区、密云区、延庆区、昌平区、石景山区.
- Include normal food packages with original value `>= 200`.
- Include Tongzhou food packages with original value `>= 150`.
- De-duplicate by `offlineActivityId`.

Never commit or store SMS codes, payment passwords, personal passwords, cookies, app data, or APK files.

## Resources

- `scripts/free_try_filter.py`: read-only scanner/filter. Produces `reports/free_try_candidates_beijing.csv`.
- `scripts/batch_apply_free_try_adb.py`: batch ADB app UI applicator. Uses `reports/free_try_apply_state.json`.
- `scripts/apply_free_try_adb.py`: single activity debugging applicator.
- `scripts/check_android_env.sh`: local Android/ADB/Python environment check.
- `references/android-emulator-setup.md`: full setup, login, route, and troubleshooting notes. Read it when setting up a new computer or emulator.

## End-to-end workflow

1. If the machine is not already configured, read `references/android-emulator-setup.md` and set up Android Studio, SDK tools, and the `Pixel_API_35_DP` emulator.
2. Verify the local environment:

```bash
bash scripts/check_android_env.sh Pixel_API_35_DP
```

3. Start or verify the emulator:

```bash
adb devices -l
adb shell wm size
adb shell getprop sys.boot_completed
```

Expected screen size is `1080x2400`; the batch script coordinates assume this layout.

4. Ensure Dianping and WeChat are installed and logged in. If login is not complete, guide the user through official login. Do not automate or bypass security verification.
5. Scan all current activities:

```bash
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 10
```

6. Count remaining eligible food activities:

```bash
python3 - <<'PY'
import csv, json
from pathlib import Path
state_path = Path("reports/free_try_apply_state.json")
state = json.loads(state_path.read_text()) if state_path.exists() else {"success": {}}
success = set((state.get("success") or {}).keys())
remaining = []
with open("reports/free_try_candidates_beijing.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if row.get("eligible") == "True" and (row.get("activityType") == "1" or row.get("isFood") == "True"):
            if row.get("offlineActivityId") not in success:
                remaining.append(row)
print("remaining_food_eligible_not_success", len(remaining))
for row in remaining[:20]:
    print(row["offlineActivityId"], row["cost"], row.get("eligibilityRule"), row["districts"], row["regionName"], row["title"])
PY
```

7. Apply remaining activities. Start with the stable mode when moving to a new computer:

```bash
python3 scripts/batch_apply_free_try_adb.py \
  --food-only \
  --max-apply 500 \
  --detail-wait 4.5 \
  --sheet-wait 3.0 \
  --agreement-tap-wait 0.7 \
  --result-wait 5.0 \
  --retry-result-wait 3.5 \
  --delay 1.0 \
  --force-stop-before-open \
  --precheck-detail \
  --save-result-screenshot
```

For a known-good `1080x2400` emulator, faster mode can be used:

```bash
python3 scripts/batch_apply_free_try_adb.py \
  --food-only \
  --max-apply 500 \
  --detail-wait 2.4 \
  --sheet-wait 1.7 \
  --agreement-tap-wait 0.3 \
  --result-wait 3.2 \
  --retry-result-wait 2.2 \
  --delay 0.4
```

8. After a batch finishes, force-stop/re-enter the free-try index and rescan:

```bash
adb shell am force-stop com.dianping.v1
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-index%2Findex-bundle.js&notitlebar=true' -p com.dianping.v1"
sleep 5
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 0
```

Repeat scan/apply until remaining eligible food count is `0`.

## Operational notes

- The scanner caches detail JSON under `.cache/details/`; use `--refresh-details` only when data may be stale.
- If `adb devices` loses the emulator, restart ADB and wait for boot completion before continuing.
- The batch script writes state after every item. Rerunning is safe; it skips IDs already in `success`.
- If screenshots show the previous detail page instead of the target activity, rerun with `--force-stop-before-open --precheck-detail`.
- If the agreement checkbox fails, inspect `*_agreement_failed.png`. Do not click confirm unless the orange agreement state is detected.
- Typical stable speed is about `10-14s` per item on the known emulator. Further speedups should be validated in small batches.
