# 大众点评免费试报名助手

基于 Android 模拟器和 ADB 的大众点评“免费试 / 霸王餐”报名辅助工具，支持活动扫描、价格筛选、区域排除、App 内报名，以及可复用的 Codex Skill 工作流。

本项目面向个人账号的正常 App 操作辅助，不提供也不支持绕过登录、验证码、人脸验证、支付密码、短信验证或账号安全校验。

## 功能

- 扫描北京大众点评免费试活动
- 拉取活动详情、套餐原价、门店信息和门店坐标
- 根据北京行政区边界判断门店所在区
- 按默认规则筛选美食活动
- 通过 ADB 打开大众点评 App 内活动详情页并报名
- 记录本地报名状态，重复运行时跳过已成功活动
- 提供 Codex Skill，方便在新电脑上复用整套流程

## 默认筛选规则

当前默认规则：

- 城市：北京
- 分类：仅美食
- 排除区域：
  - 房山区
  - 门头沟区
  - 怀柔区
  - 平谷区
  - 密云区
  - 延庆区
  - 昌平区
  - 石景山区
- 普通美食套餐：原价 `>= 200`
- 通州区美食套餐：原价 `>= 150`

规则写在 `scripts/free_try_filter.py` 里，可以按自己的需求调整。

## 安全边界

如果出现以下页面或状态，应停止自动化并由用户本人处理：

- 登录页
- 短信验证码
- 图形验证码
- 账号安全验证
- 人脸验证
- 支付密码
- 任何未知页面或异常状态

不要提交或公开以下内容：

- App 数据
- Cookie / Token
- 短信验证码
- 密码 / 支付密码
- 带个人信息的截图
- 本地报名状态
- 接口缓存

## 环境要求

- macOS
- Android Studio / Android SDK
- Android Emulator
- 用户自行安装的大众点评 APK
- 如果登录流程需要微信，则用户自行安装微信 APK
- Python 3
- Pillow

安装 Python 依赖：

```bash
python3 -m pip install pillow
```

当前脚本默认按 `1080x2400` 模拟器分辨率设计，批量报名脚本里的 UI 坐标依赖这个布局。

## 快速开始

检查 Android 环境：

```bash
bash skills/dianping-free-try-auto-apply/scripts/check_android_env.sh Pixel_API_35_DP
```

确认模拟器和 ADB 状态：

```bash
adb devices -l
adb shell wm size
adb shell getprop sys.boot_completed
```

扫描活动：

```bash
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 20
```

稳定模式报名：

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

如果你的模拟器环境稳定，可以先小批量测试加速模式：

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

## 使用 Codex Skill

复制 Skill 到 Codex 技能目录：

```bash
mkdir -p ~/.codex/skills
cp -R skills/dianping-free-try-auto-apply ~/.codex/skills/
```

或者从当前仓库软链：

```bash
ln -s "$PWD/skills/dianping-free-try-auto-apply" ~/.codex/skills/dianping-free-try-auto-apply
```

在 Codex 中这样触发：

```text
$dianping-free-try-auto-apply 帮我配置安卓模拟器并报名符合规则的大众点评免费试
```

## 本地生成文件

以下路径已被 `.gitignore` 忽略：

- `.cache/`
- `reports/`
- `.DS_Store`
- `*.log`

其中 `reports/free_try_apply_state.json` 是本地报名状态，不应该公开。

## 免责声明

大众点评页面、接口和风控策略可能变化。本项目只适合作为个人账号的正常操作辅助工具，不保证长期可用，也不建议用于多账号、绕过平台限制或违反平台规则的用途。
