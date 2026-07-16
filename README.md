# 大众点评免费试自动报名助手

基于 Android 模拟器、ADB 和 Python 的大众点评“免费试 / 霸王餐”个人辅助工具。它会每天重新扫描活动，按规则筛选，通过官方 App 模拟正常点击完成报名，并在结束后再复扫一次确认是否有新增或漏报。

本项目仅用于辅助用户操作自己的账号，不提供也不支持绕过登录、验证码、人脸验证、短信验证、支付密码或账号安全校验。

## 主要能力

- 每次正式运行都重新扫描当天活动及详情
- 按城市、分类、区域和套餐价值筛选
- 优先从免费试列表点击可见的“免费抽”卡片
- 列表遗漏或异常时，对剩余活动使用官方 App 详情链接兜底
- 列表出现“当前活动太火爆”或“网络异常”时，先按 5、10、20 秒退避重开三次
- 详情兜底连续出现 3 个空白详情时自动熔断，避免整批无效重试
- 通过截图像素和 UI 状态验证详情、确认页、协议和报名结果
- 记录成功、失败和暂停状态，重复运行不会重复提交
- 报名结束后再全量刷新一次，只处理新增或漏报差集
- 遇到验证码或账号安全页立即暂停，等待用户本人完成

## 默认筛选规则

仓库当前附带一组可修改的北京示例规则：

- 城市：北京，详情 `cityId=2`
- 分类：仅美食，详情 `type=1`
- 排除：房山、门头沟、怀柔、平谷、密云、延庆、昌平、石景山
- 普通美食套餐原价：`>= 200`
- 通州区美食套餐原价：`>= 150`
- 按 `offlineActivityId` 去重
- 不预先排除 V 专享、PASS 等会员标签，由登录后的官方 App 判断资格

规则实现在 `scripts/free_try_filter.py` 中，请按自己的城市和需求修改。页面显示的距离不用于判断活动城市；模拟器粗略定位异常时，北京门店也可能显示 `>100km`。

## 安全边界

出现以下情况时，脚本必须停止并由用户本人处理：

- 登录、短信验证码
- 滑块、拼图、按数字顺序点击等验证
- 人脸验证、支付密码、账号安全验证
- 无法判断的页面或结果

不要提交或公开 App 数据、Cookie、Token、验证码、密码、APK、本地报名状态、接口缓存或带个人信息的截图。

## 环境要求

- macOS
- Android Studio / Android SDK / Android Emulator
- Python 3
- Pillow
- 用户自行安装并登录的大众点评 App
- `1080x2400` 模拟器分辨率

安装 Python 依赖：

```bash
python3 -m pip install pillow
```

推荐从 Android Studio 的 **Tools → Device Manager → Run** 启动 `Pixel_API_35_DP`，并在启动期间保持 Android Studio 打开。

检查环境：

```bash
bash skills/dianping-free-try-auto-apply/scripts/check_android_env.sh Pixel_API_35_DP
adb devices -l
adb -s emulator-5554 shell getprop sys.boot_completed
adb -s emulator-5554 shell wm size
```

应看到已连接设备、启动值 `1` 和分辨率 `1080x2400`。

## 快速开始

使用统一入口执行完整每日流程：

```bash
python3 skills/dianping-free-try-auto-apply/scripts/run_free_try_auto.py \
  --route auto \
  --max-apply 100
```

完整流程为：

```text
首次全量刷新
→ 列表交互点击报名
→ 剩余活动安全详情直达
→ 第二次全量刷新
→ 只报名新增/漏报差集
→ 输出最终剩余数量
```

第二次刷新严格只执行一轮，避免无限循环。全部处理完成时会输出：

```text
verification_final_remaining=0
```

如果中途出现需要人工处理的验证，完成后在同一天续跑：

```bash
python3 skills/dianping-free-try-auto-apply/scripts/run_free_try_auto.py \
  --route auto \
  --max-apply 100 \
  --skip-daily-scan
```

`--skip-daily-scan` 只跳过续跑前的首次刷新，结束前的二次确认刷新仍会执行。不要用它复用昨天的数据。

## 两种报名路线

### 列表交互路线（默认）

`list_apply_free_try_adb.py` 会：

- 只点击屏幕内完整可见的“免费抽”按钮
- 将按钮与附近套餐、门店和区域信息绑定
- 从 App 当前详情日志解析真实活动 ID
- 对照当天刷新后的筛选结果
- 验证“我要报名”、确认弹层、协议和结果页
- 在 App 丢失第一次点击时，只在确认弹层明确未出现时重试一次
- 遇到列表服务繁忙时保留已处理卡片记录，从顶部退避重开；三次仍失败才进入详情兜底

小范围只读测试：

```bash
python3 scripts/list_apply_free_try_adb.py --dry-run --max-scrolls 1
```

### 详情直达兜底路线

当列表首页异常、列表遍历完成但仍有合规活动未处理时，`direct_apply_free_try_adb.py` 仅对剩余 ID 使用官方 App 详情链接。它与列表路线共用同一套截图验屏和安全暂停逻辑，不会在空白详情壳上盲点固定坐标。

如果连续 3 个不同活动都返回已验证的空白详情，直达路线会暂停并进入唯一一次复扫。复扫时优先尝试尚未处理的活动，避免固定的空白活动阻塞后续候选；复扫后仍未解决的 ID 会明确输出，留待同日续跑。

## 文件说明

- `scripts/run_free_try_auto.py`：每日统一入口与二次复扫闭环
- `scripts/free_try_filter.py`：扫描详情并按规则筛选
- `scripts/list_apply_free_try_adb.py`：列表交互点击主路线
- `scripts/direct_apply_free_try_adb.py`：剩余活动详情直达兜底
- `scripts/batch_apply_free_try_adb.py`：共享 ADB/状态工具和旧版诊断入口
- `scripts/apply_free_try_adb.py`：单活动诊断
- `skills/dianping-free-try-auto-apply/`：可安装的 Codex Skill

## 安装 Codex Skill

```bash
mkdir -p ~/.codex/skills
cp -R skills/dianping-free-try-auto-apply ~/.codex/skills/
```

在 Codex 中触发：

```text
$dianping-free-try-auto-apply 帮我扫描并报名符合规则的大众点评免费试
```

## 本地生成文件

以下内容已通过 `.gitignore` 排除：

- `.cache/`
- `reports/`
- `.DS_Store`
- `*.log`
- `__pycache__/`

其中 `reports/free_try_apply_state.json` 保存个人报名状态，不应公开。

## 免责声明

大众点评页面、接口和风控策略可能变化。本项目只适合作为个人账号的正常操作辅助工具，不保证长期可用，也不应用于多账号操作、绕过平台限制或违反平台规则的场景。
