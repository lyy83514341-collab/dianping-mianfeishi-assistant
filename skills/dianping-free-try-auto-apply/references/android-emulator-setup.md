# Android emulator setup for Dianping free-try automation

Use this reference when the machine has no Android automation environment.

## Scope and safety

- Automate only the user's own Dianping account.
- Do not bypass captcha, face verification, payment password, login, or account-security challenges.
- Stop and ask the user whenever a verification/security page appears.
- Do not bundle third-party APK files in the repository. Ask the user to provide official Dianping and WeChat APKs, or install them manually.
- Never store SMS codes, passwords, payment passwords, or personal identity data in repo files.

## macOS setup

1. Install Android Studio from the official Android developer site.
2. In Android Studio SDK Manager, install:
   - Android SDK Platform-Tools
   - Android Emulator
   - An Android system image, preferably API 35 Google APIs/Play image for arm64 on Apple Silicon.
3. Create an AVD in Device Manager:
   - Name: `Pixel_API_35_DP`
   - Resolution: `1080x2400`
   - RAM: at least `2560 MB`
   - Front camera: a real webcam if login verification requires camera
4. Add SDK tools to the shell environment if needed:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
```

5. Verify the environment from the skill folder:

```bash
bash scripts/check_android_env.sh Pixel_API_35_DP
```

## Start the emulator

```bash
emulator -avd Pixel_API_35_DP
adb devices -l
adb shell wm size
```

Expected screen size is `1080x2400`. If an extra emulator display appears, remove it:

```bash
adb emu multidisplay del 1
```

## Install apps

Install user-provided official APKs:

```bash
adb install -r /path/to/dianping.apk
adb install -r /path/to/wechat.apk
```

Known package names:

- Dianping: `com.dianping.v1`
- WeChat: `com.tencent.mm`

Verify:

```bash
adb shell dumpsys package com.dianping.v1 | grep -E 'versionName=|versionCode='
adb shell dumpsys package com.tencent.mm | grep -E 'versionName=|versionCode='
```

## Login and persistence

1. Log into WeChat first.
2. Log into Dianping using the user's normal official flow.
3. If Dianping asks for SMS, payment-password, WeChat authorization, face, captcha, or account security, stop for user input.
4. Do not clear app data. Force-stopping the app is allowed and normally preserves login:

```bash
adb shell am force-stop com.dianping.v1
```

## Useful routes

Free-try index:

```bash
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-index%2Findex-bundle.js&notitlebar=true' -p com.dianping.v1"
```

Free-try detail:

```bash
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-detail%2Findex-bundle.js&offlineActivityId=ACTIVITY_ID&notitlebar=true' -p com.dianping.v1"
```

## Troubleshooting

- `adb devices` empty: restart the emulator and `adb kill-server && adb start-server`.
- `adb shell am ...` fails while device is visible: wait until `adb shell getprop sys.boot_completed` prints `1`.
- Detail deeplink opens the previous activity: use `--force-stop-before-open --precheck-detail` in the batch script.
- Agreement checkbox fails: inspect `*_agreement_failed.png`. If still on detail page, CTA coordinate or route reuse is the issue. If on the confirmation sheet, adjust checkbox crop/tap coordinates.
- UI automation should stop on captcha/login/security keywords.
