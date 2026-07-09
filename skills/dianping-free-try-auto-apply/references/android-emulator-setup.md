# Android 模拟器配置参考

当一台新电脑还没有 Android 自动化环境时，按这份参考配置。

## 范围和安全边界

- 只辅助用户自己的大众点评账号。
- 不绕过验证码、人脸验证、支付密码、登录或账号安全校验。
- 只要出现验证或安全页面，就停止并让用户本人处理。
- 不要把第三方 APK 文件放进仓库。大众点评和微信 APK 应由用户自行下载或手动安装。
- 不要在仓库里保存短信验证码、密码、支付密码或个人身份信息。

## macOS 环境配置

1. 从 Android 官方网站安装 Android Studio。
2. 在 Android Studio 的 SDK Manager 中安装：
   - Android SDK Platform-Tools
   - Android Emulator
   - Android 系统镜像；Apple Silicon 机器建议 API 35 Google APIs / Play arm64 镜像
3. 在 Device Manager 中创建 AVD：
   - 名称：`Pixel_API_35_DP`
   - 分辨率：`1080x2400`
   - 内存：至少 `2560 MB`
   - 前置摄像头：如果登录验证需要摄像头，选择真实摄像头
4. 如有需要，把 SDK 工具加入 shell 环境：

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
```

5. 在 Skill 目录下检查环境：

```bash
bash scripts/check_android_env.sh Pixel_API_35_DP
```

## 启动模拟器

```bash
emulator -avd Pixel_API_35_DP
adb devices -l
adb shell wm size
```

期望屏幕尺寸为 `1080x2400`。如果出现额外模拟器屏幕，可以删除：

```bash
adb emu multidisplay del 1
```

## 安装 App

安装用户自行提供的官方 APK：

```bash
adb install -r /path/to/dianping.apk
adb install -r /path/to/wechat.apk
```

常见包名：

- 大众点评：`com.dianping.v1`
- 微信：`com.tencent.mm`

检查安装状态：

```bash
adb shell dumpsys package com.dianping.v1 | grep -E 'versionName=|versionCode='
adb shell dumpsys package com.tencent.mm | grep -E 'versionName=|versionCode='
```

## 登录和登录态保留

1. 如果需要微信登录，先登录微信。
2. 使用用户自己的正常官方流程登录大众点评。
3. 如果大众点评要求短信、支付密码、微信授权、人脸、验证码或账号安全校验，停止并让用户本人处理。
4. 不要清除 App 数据。可以强停 App，通常不会清掉登录态：

```bash
adb shell am force-stop com.dianping.v1
```

## 常用路由

免费试首页：

```bash
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-index%2Findex-bundle.js&notitlebar=true' -p com.dianping.v1"
```

免费试详情页：

```bash
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-detail%2Findex-bundle.js&offlineActivityId=ACTIVITY_ID&notitlebar=true' -p com.dianping.v1"
```

## 常见问题

- `adb devices` 为空：重启模拟器，并执行 `adb kill-server && adb start-server`
- 设备可见但 `adb shell am ...` 失败：等待 `adb shell getprop sys.boot_completed` 输出 `1`
- 详情 deeplink 打开的是上一个活动：报名脚本加 `--force-stop-before-open --precheck-detail`
- 协议勾选失败：查看 `*_agreement_failed.png`；如果还停在详情页，通常是 CTA 坐标或路由复用问题；如果已经在确认弹层，调整协议勾选区域
- UI 自动化遇到验证码、登录或安全关键词时应停止
