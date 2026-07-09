---
name: dianping-free-try-auto-apply
description: "大众点评免费试报名辅助 Skill：从 macOS Android 模拟器配置开始，安装并登录大众点评/微信，扫描北京免费试活动，按默认规则筛选美食套餐，并通过 ADB 在大众点评 App 内完成报名。适用于继续、配置、排查、复扫或运行大众点评免费试/霸王餐报名辅助流程。"
---

# 大众点评免费试报名助手

## 默认原则

只辅助用户自己的大众点评账号完成官方 App 内的正常操作。不要绕过验证码、人脸验证、支付密码、短信验证、登录或账号安全校验；一旦出现这些页面，立即停止并让用户本人处理。

默认筛选规则：

- 城市：北京，`cityId=2`
- 分类：仅美食，大众点评详情接口 `type=1`
- 排除区域：房山区、门头沟区、怀柔区、平谷区、密云区、延庆区、昌平区、石景山区
- 普通美食套餐：原价 `>= 200`
- 通州区美食套餐：原价 `>= 150`
- 按 `offlineActivityId` 去重

不要保存或提交短信验证码、支付密码、账号密码、Cookie、App 数据或 APK 文件。

## 资源说明

- `scripts/free_try_filter.py`：只读扫描和筛选脚本，输出 `reports/free_try_candidates_beijing.csv`
- `scripts/batch_apply_free_try_adb.py`：批量 ADB 报名脚本，使用 `reports/free_try_apply_state.json` 记录本地状态
- `scripts/apply_free_try_adb.py`：单活动调试脚本
- `scripts/check_android_env.sh`：本地 Android / ADB / Python 环境检查脚本
- `references/android-emulator-setup.md`：新电脑或新模拟器配置参考

## 端到端流程

1. 如果机器还没配置 Android 环境，先读取 `references/android-emulator-setup.md`，安装 Android Studio、SDK tools，并创建 `Pixel_API_35_DP` 模拟器。
2. 检查本地环境：

```bash
bash scripts/check_android_env.sh Pixel_API_35_DP
```

3. 启动或确认模拟器：

```bash
adb devices -l
adb shell wm size
adb shell getprop sys.boot_completed
```

期望屏幕尺寸是 `1080x2400`，批量报名脚本的坐标按这个布局设计。

4. 确认大众点评和微信已经安装并登录。若未登录，引导用户走官方登录流程；不要自动化或绕过安全验证。
5. 扫描当前全部活动：

```bash
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 10
```

6. 统计剩余符合条件的美食活动：

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

7. 报名剩余活动。新电脑或新模拟器建议先用稳定模式：

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

已验证稳定的 `1080x2400` 模拟器可以小批量测试加速模式：

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

8. 每轮批量结束后，强停并重新进入免费试首页，再复扫：

```bash
adb shell am force-stop com.dianping.v1
adb shell "am start -a android.intent.action.VIEW -d 'dianping://picassobox?picassoid=pexus-freetry-index%2Findex-bundle.js&notitlebar=true' -p com.dianping.v1"
sleep 5
python3 scripts/free_try_filter.py --max-pages 100 --workers 6 --top 0
```

重复扫描和报名，直到剩余符合条件美食活动数为 `0`。

## 操作注意事项

- 扫描详情会缓存到 `.cache/details/`；只有怀疑数据过期时才使用 `--refresh-details`
- 如果 `adb devices` 看不到模拟器，重启 ADB 并等待系统启动完成
- 批量脚本每处理一个活动都会写入状态文件，重复运行会跳过已成功 ID
- 如果截图显示打开的是上一个活动详情页，使用 `--force-stop-before-open --precheck-detail`
- 如果协议勾选失败，检查 `*_agreement_failed.png`；不要在未检测到橙色协议选中态时点击确认
- 稳定速度通常约 `10-14 秒/个`；进一步提速应先小批量验证
