# Dianping Free Try Auto Apply

Android emulator + ADB automation for scanning and applying to Dianping 大众点评 “免费试 / 霸王餐” activities with a reusable Codex skill.

This repository is designed for a single user automating their own account through the official Dianping app flow. It does not bypass login, captcha, face verification, payment password, SMS, or account-security checks.

## What is included

- `scripts/free_try_filter.py`  
  Scans Beijing free-try activities, fetches detail data, maps shop coordinates to districts, and writes a filtered CSV.

- `scripts/batch_apply_free_try_adb.py`  
  Uses ADB to open Dianping activity detail pages and apply through the app UI.

- `scripts/apply_free_try_adb.py`  
  Single-activity debugging helper.

- `skills/dianping-free-try-auto-apply/`  
  A Codex skill package with the same workflow, scripts, and emulator setup reference.

## Default filter rules

The bundled workflow defaults to:

- City: Beijing
- Category: food only
- Excluded districts:
  - 房山区
  - 门头沟区
  - 怀柔区
  - 平谷区
  - 密云区
  - 延庆区
  - 昌平区
  - 石景山区
- Include normal food packages with original value `>= 200`
- Include Tongzhou food packages with original value `>= 150`

## Safety boundaries

Stop the automation and require user action if any of these appear:

- Login page
- SMS verification
- Captcha
- Account-security verification
- Face verification
- Payment password
- Any unexpected or unknown page state

Do not commit app data, cookies, SMS codes, passwords, screenshots containing personal data, generated reports, or API/cache output.

## Requirements

- macOS
- Android Studio / Android SDK
- Android Emulator
- A Dianping APK installed by the user
- Optional WeChat APK installed by the user if the account login flow requires it
- Python 3
- Pillow:

```bash
python3 -m pip install pillow
```

The tested layout is an Android emulator with `1080x2400` resolution. UI coordinates in the batch script assume that layout.

## Quick start

Check the Android environment:

```bash
bash skills/dianping-free-try-auto-apply/scripts/check_android_env.sh Pixel_API_35_DP
```

Start or verify the emulator:

```bash
adb devices -l
adb shell wm size
adb shell getprop sys.boot_completed
```

Scan activities:

```bash
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 20
```

Apply eligible food activities:

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

For a known-good emulator, a faster mode can be tried in small batches first:

```bash
python3 scripts/batch_apply_free_try_adb.py \
  --food-only \
  --max-apply 20 \
  --detail-wait 2.4 \
  --sheet-wait 1.7 \
  --agreement-tap-wait 0.3 \
  --result-wait 3.2 \
  --retry-result-wait 2.2 \
  --delay 0.4
```

## Use the Codex skill

Copy the skill into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/dianping-free-try-auto-apply ~/.codex/skills/
```

Or link it from this checkout:

```bash
ln -s "$PWD/skills/dianping-free-try-auto-apply" ~/.codex/skills/dianping-free-try-auto-apply
```

Then invoke it in Codex:

```text
$dianping-free-try-auto-apply 帮我配置安卓模拟器并报名符合规则的大众点评免费试
```

## Generated local files

These paths are intentionally ignored by Git:

- `.cache/`
- `reports/`
- `.DS_Store`
- `*.log`

`reports/free_try_apply_state.json` is local state and should not be published.

## Notes

The Dianping UI and APIs can change. Treat this as a personal automation assistant for normal app actions, not as a guarantee of stable long-term compatibility.
