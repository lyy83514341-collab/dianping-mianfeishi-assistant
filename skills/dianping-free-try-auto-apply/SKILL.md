---
name: dianping-free-try-auto-apply
description: "自动化用户本人账号的大众点评免费试报名：在 Android 模拟器上每日刷新活动，按城市、分类、区域和价格筛选，优先从可见列表模拟人工点击，使用详情直达补齐遗漏，持久化进度，二次复扫确认，并在验证码、登录或安全校验时暂停。适用于环境配置、每日扫描报名、验证码后续跑、列表/网络/定位故障排查和流程优化。"
---

# 大众点评免费试自动报名

将本 Skill 视为可根据真实 App 行为迭代的自动化系统，不要当作固定坐标点击脚本。优先使用 Skill 内置脚本。

将本文件所在目录记为 `SKILL_DIR`。从项目工作目录调用 `$SKILL_DIR/scripts/` 下的脚本，使状态保存在项目的 `reports/` 中。

## 安全和账号范围

- 只操作用户本人的账号和官方大众点评 App。
- 不自动化或绕过验证码、人脸、短信、登录、支付密码和账号安全校验；出现时立即停止，让用户本人处理。
- 不保存密码、短信验证码、Cookie、App 数据或 APK。
- 不在空白详情页或未验证的确认状态上提交。

## 默认筛选策略

仓库附带以下可修改示例规则：

- 北京，详情 `cityId=2`
- 仅美食，详情 `type=1`
- 排除房山、门头沟、怀柔、平谷、密云、延庆、昌平、石景山
- 普通套餐原价 `>=200`；通州美食套餐原价 `>=150`
- 按 `offlineActivityId` 去重
- 不预先排除 V 专享、PASS 等会员标签，让登录后的官方 App 判断资格

不要用页面显示距离判断活动城市。模拟器粗略定位错误时，北京商户也可能显示 `>100km`；应使用 `cityId`、门店坐标、行政区和区域数据。

## 每日标准流程

1. 从 Android Studio → Device Manager → Run 启动 `Pixel_API_35_DP`，启动期间保持 Android Studio 打开。
2. 检查设备：

```bash
adb devices -l
adb -s emulator-5554 shell getprop sys.boot_completed
adb -s emulator-5554 shell wm size
```

要求设备已连接、启动值为 `1`、分辨率为 `1080x2400`。

3. 运行唯一每日入口：

```bash
python3 "$SKILL_DIR/scripts/run_free_try_auto.py" \
  --route auto \
  --max-apply 100
```

正式批次必须重新拉取当天列表并刷新所有当前详情，不得复用昨天的 CSV。

4. 第一轮报名完成后，全量刷新列表和详情恰好一次。比较刷新前后的合规 ID，只处理新增或仍未解决的差集，最后输出 `verification_final_remaining`。若仍存在可重试合规活动，返回非零状态并打印 ID。不要无限复扫。
5. 如果因人工验证退出，用户完成官方验证流程后，同一天续跑：

```bash
python3 "$SKILL_DIR/scripts/run_free_try_auto.py" \
  --route auto \
  --max-apply 100 \
  --skip-daily-scan
```

`--skip-daily-scan` 只允许用于当天已完成首次刷新的续跑；最终复查刷新仍会执行。

6. 报告二次复扫新增/下架数量、新成功数、跳过项、暂停 ID/原因和最终剩余数。

## 路由选择

默认使用 `run_free_try_auto.py --route auto`。只有自动模式执行报名后的单轮复扫闭环；显式 `list` 和 `deeplink` 仅用于诊断。

### 路线 A：可见列表交互（优先）

列表正常展示筛选器和活动卡片时，使用 `list_apply_free_try_adb.py`：

- 只点击底部导航上方完整可见的“免费抽”按钮
- 将按钮绑定到附近套餐、门店和区域上下文，避免坐标变化导致重复打开
- 从 App 当前详情的 `pageUrl` 日志解析真实 `offlineActivityId`
- 与当天刷新 CSV 对照；新卡片可回退到官方详情缓存重新判断
- 使用截图像素为主、UI 文本为辅验证详情、确认弹层、协议和结果
- 对所有 UIAutomator 调用设置上限，避免动态 Picasso 页面永远无法空闲而卡死批次
- 只有确认弹层明确未出现且详情按钮仍在时，才重试一次被 App 丢失的详情点击
- 成功后立即写状态并回到列表
- 验证码或未知状态一律暂停，不猜测

在 `1080x2400` 模拟器上，`timing=card_total` 约 3–5 秒属于健康的核心提交耗时；连续超过 10 秒应排查加载或 UI dump。

修改解析逻辑后先执行小范围只读测试：

```bash
python3 "$SKILL_DIR/scripts/list_apply_free_try_adb.py" \
  --dry-run \
  --max-scrolls 1
```

连续多张卡片的列表标题、解析 ID 和候选标题一致后，再允许提交。

### 路线 B：官方 App 详情直达（兜底）

以下情况才使用 `direct_apply_free_try_adb.py`：

- 列表提示“当前活动太火爆”“网络异常”或其他仅首页故障
- 列表可见卡片遍历完成，但刷新 CSV 仍有合规未提交 ID

只处理剩余差集，并遵守：

- 复用列表路线的详情、确认、协议和结果验屏状态机
- 每个 deeplink 前强停 App，清除旧 Picasso/结果遮罩
- 点击前区分“我要报名”和长文本“已报名,看看其他活动”；后者直接补记成功状态
- 静态空白壳没有目标标题时绝不点击
- 详情/确认页出现服务繁忙或限流时停止批次
- 列表仍能正常打开时，不把单个活动的验证结果扩大成账号或设备全局不可用

只有列表和已知合规 ID 都不可用时，才考虑从官方 H5 搜索结果进入 App；不得自行拼接活动 URL。

## 人工验证状态

- Yoda 可能分阶段出现：滑块失败后还可能要求按 `1-2-3-4` 顺序点选。让用户完成全部官方步骤，只根据最终业务页判断。
- 验证完成后原详情可能暂时变成空白壳；返回列表并重新打开一次，不要反复刷新空白页。
- 报名成功页之后可能叠加验证码。先记录已经可见的“报名成功”；后续遮罩不撤销成功结果。
- 需要人工处理的项写入 `state.paused`，不要写成永久失败。

## 状态和产物

- `reports/free_try_candidates_beijing.csv`：当天最新候选数据
- `reports/free_try_apply_state.json`：持久化 `success`、`failed`、`paused`
- `/tmp/free_try_list_batch/`：列表路线 XML、文本和截图证据
- `/tmp/free_try_direct_batch/`：详情兜底路线证据

重新运行不得删除成功记录。协议未选中、解析失败、空白详情、未知 UI 等技术问题应允许重试；只有明确业务拒绝、账号不符合或活动结束才是终止跳过。

## 故障处理

- ADB 断开时，先从 Device Manager 重启 AVD，再考虑 GPU 或代理参数。
- 定位异常时，对比 App `LocationSDK` 日志与 Android provider；保持 App 城市正确，不用距离文字判城市。
- 多页面网络异常时，只核查一次模拟器代理、DNS/TCP 和国内出口；确认是业务限流后不要反复改网络。
- UIAutomator 报 `could not get idle state` 时使用截图回退，不根据固定坐标点击推断成功。
- 仅在新机器配置或深入排查模拟器/网络/定位时读取 `references/android-emulator-setup.md`。

## 内置脚本

- `scripts/run_free_try_auto.py`：每日扫描、双路由、二次复扫统一入口
- `scripts/list_apply_free_try_adb.py`：可见列表交互主路线
- `scripts/direct_apply_free_try_adb.py`：剩余 ID 的安全详情兜底
- `scripts/free_try_filter.py`：只读扫描和筛选
- `scripts/batch_apply_free_try_adb.py`：共享 ADB/状态工具和旧版诊断
- `scripts/apply_free_try_adb.py`：单活动诊断
- `scripts/check_android_env.sh`：环境检查
