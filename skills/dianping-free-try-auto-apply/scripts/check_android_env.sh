#!/usr/bin/env bash
set -euo pipefail

AVD_NAME="${1:-Pixel_API_35_DP}"
ANDROID_HOME_CANDIDATES=(
  "${ANDROID_HOME:-}"
  "${HOME}/Library/Android/sdk"
)

echo "== host =="
uname -a

echo
echo "== android sdk =="
SDK_ROOT=""
for candidate in "${ANDROID_HOME_CANDIDATES[@]}"; do
  if [[ -n "${candidate}" && -x "${candidate}/platform-tools/adb" ]]; then
    SDK_ROOT="${candidate}"
    break
  fi
done

if [[ -z "${SDK_ROOT}" ]]; then
  echo "missing adb. Install Android Studio or Android SDK platform-tools."
  exit 1
fi
echo "ANDROID_HOME=${SDK_ROOT}"
"${SDK_ROOT}/platform-tools/adb" version

echo
echo "== emulator =="
if [[ ! -x "${SDK_ROOT}/emulator/emulator" ]]; then
  echo "missing emulator binary. Install Android Emulator from Android Studio SDK Manager."
  exit 1
fi
"${SDK_ROOT}/emulator/emulator" -list-avds
if ! "${SDK_ROOT}/emulator/emulator" -list-avds | grep -qx "${AVD_NAME}"; then
  echo "missing AVD ${AVD_NAME}. Create it from Android Studio Device Manager."
  exit 1
fi

echo
echo "== adb devices =="
"${SDK_ROOT}/platform-tools/adb" devices -l

echo
echo "== python deps =="
python3 - <<'PY'
import importlib.util
import sys
print(sys.version)
missing = [name for name in ["PIL"] if importlib.util.find_spec(name) is None]
if missing:
    print("missing Python modules:", ", ".join(missing))
    print("install with: python3 -m pip install pillow")
    raise SystemExit(1)
print("python deps ok")
PY

echo
echo "environment check passed"
