# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

离场交接条（`app/modules/handover/`）：预览(只读) → 签发 → 确认改派格子并自动作废引用交出人的 pending 对调 → 凭已确认交接条停用成员。看板与交接详情钉同一份移交清单（`projection.py`）。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
```

种子含 clean/dirty。0-1 空桩：`streak_badge` / `skip_week` / `chore_photo`。
