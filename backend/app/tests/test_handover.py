"""离场交接条全链路：预览不改库 → 签发 → 确认写库 → 停用闸门 → 对调作废 → 看板投影。"""

import pytest
from fastapi.testclient import TestClient

from app import seed
from app.db import connect
from app.engines.rota import build_week_slots
from app.main import app
from app.modules.handover import confirm as hc
from app.modules.handover import preview as hp
from app.modules.handover import projection as hj
from app.modules.handover import service as hs
from app.modules.handover.errors import HandoverError

WEEK = 1
AMIN, XIAOYU, YEYE, GHOST = 1, 2, 3, 4  # 种子成员；GHOST 停用且 dirty


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    c = connect()
    yield c
    c.close()


@pytest.fixture()
def client(conn):
    return TestClient(app)


def gen_week(c, week_id=WEEK, days=7):
    """与 /generate 端点同一取数口径：在岗且 clean 的成员、clean 且权重>0 的任务。"""
    mids = [r["id"] for r in c.execute(
        "SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]
    tids = [r["id"] for r in c.execute(
        "SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]
    slots = build_week_slots(mids, tids, days=days)
    c.execute("DELETE FROM assignments WHERE week_id=?", (week_id,))
    for s in slots:
        c.execute("INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
                  (week_id, s["day"], s["task_id"], s["member_id"]))
    c.commit()
    return slots


def cells_of(c, member_id, week_id=WEEK):
    return [dict(r) for r in c.execute(
        "SELECT day, task_id FROM assignments WHERE week_id=? AND member_id=? ORDER BY day, task_id",
        (week_id, member_id))]


def amin_cells():
    """3 成员 × 3 clean 任务的轮盘下，阿明固定持有每天 task 1 的 7 个格子。"""
    return [(i, 1) for i in range(7)]


def add_swap(c, a_day, a_task, b_day, b_task, week_id=WEEK):
    cur = c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note) VALUES (?,?,?,?,?,'pending','')",
        (week_id, a_day, a_task, b_day, b_task))
    return cur.lastrowid


def swap_status(c, swap_id):
    return c.execute("SELECT status, note FROM swap_requests WHERE id=?", (swap_id,)).fetchone()


def cell_keys(cells):
    return sorted((c["day"], c["task_id"]) for c in cells)


def test_preview_lists_cells_without_writing(conn):
    gen_week(conn)
    before = conn.execute("SELECT * FROM assignments ORDER BY id").fetchall()
    out = hp.preview_takeover(conn, WEEK, AMIN, XIAOYU)
    assert out["count"] == 7
    assert out["from_member_id"] == AMIN
    assert out["from_member_name"] == "阿明"
    assert out["to_member_id"] == XIAOYU
    assert cell_keys(out["cells"]) == amin_cells()
    # 不改库：assignments 原样，handovers / handover_cells 均无写入
    after = conn.execute("SELECT * FROM assignments ORDER BY id").fetchall()
    assert list(after) == list(before)
    assert conn.execute("SELECT COUNT(*) c FROM handovers").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM handover_cells").fetchone()["c"] == 0


def test_preview_rejects_inactive_sender(conn):
    with pytest.raises(HandoverError) as e:
        hp.preview_takeover(conn, WEEK, GHOST)
    assert e.value.reason == "sender_inactive"


def test_issue_then_confirm_reassigns_cells(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU, "回老家")
    assert h["status"] == "issued"
    # 确认前看板格子仍在交出人名下
    assert cell_keys(cells_of(conn, AMIN)) == amin_cells()

    res = hc.confirm_handover(conn, h["id"])
    assert res["transferred"] == 7
    # 三路一致：看板格位移交接收人，交出人不再持格
    assert cells_of(conn, AMIN) == []
    assert cell_keys(cells_of(conn, XIAOYU)) == sorted(
        [(i, t) for i in range(7) for t in (1, 2)])
    row = conn.execute("SELECT status, cell_count FROM handovers WHERE id=?", (h["id"],)).fetchone()
    assert row["status"] == "confirmed"
    assert row["cell_count"] == 7
    assert conn.execute(
        "SELECT COUNT(*) c FROM handover_cells WHERE handover_id=?",
        (h["id"],)).fetchone()["c"] == 7


def test_confirm_rejects_inactive_receiver(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, GHOST)
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert e.value.reason == "receiver_inactive"
    # 校验失败不落任何写入：交接条仍 issued，看板不动
    assert conn.execute("SELECT status FROM handovers WHERE id=?", (h["id"],)).fetchone()["status"] == "issued"
    assert cell_keys(cells_of(conn, AMIN)) == amin_cells()


def test_confirm_rejects_dirty_receiver(conn):
    gen_week(conn)
    cur = conn.execute("INSERT INTO members(name,active,data_quality) VALUES ('脏数据成员',1,'dirty')")
    dirty_id = cur.lastrowid
    h = hs.issue_handover(conn, WEEK, AMIN, dirty_id)
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert e.value.reason == "receiver_dirty"
    assert cell_keys(cells_of(conn, AMIN)) == amin_cells()


def test_confirm_rejects_sender_as_receiver(conn):
    gen_week(conn)
    with pytest.raises(HandoverError) as e:
        hs.issue_handover(conn, WEEK, AMIN, AMIN)
    assert e.value.reason == "receiver_is_sender"
    # 绕过签发闸门直接落库，确认时仍须拦截
    cur = conn.execute(
        "INSERT INTO handovers(week_id,from_member_id,to_member_id,status) VALUES (?,?,?,'issued')",
        (WEEK, AMIN, AMIN))
    with pytest.raises(HandoverError) as e2:
        hc.confirm_handover(conn, cur.lastrowid)
    assert e2.value.reason == "receiver_is_sender"
    assert cell_keys(cells_of(conn, AMIN)) == amin_cells()


def test_deactivate_requires_confirmed_handover(conn):
    gen_week(conn)
    with pytest.raises(HandoverError) as e:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert e.value.reason == "handover_required"
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # 仅签发未确认同样拒绝
    with pytest.raises(HandoverError) as e2:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert e2.value.reason == "handover_required"
    assert conn.execute("SELECT active FROM members WHERE id=?", (AMIN,)).fetchone()["active"] == 1
    hc.confirm_handover(conn, h["id"])
    out = hs.deactivate_member(conn, AMIN, WEEK)
    assert out == {"id": AMIN, "active": 0}
    assert conn.execute("SELECT active FROM members WHERE id=?", (AMIN,)).fetchone()["active"] == 0


def test_confirm_voids_pending_swaps_referencing_sender(conn):
    gen_week(conn)
    hit = add_swap(conn, 0, 1, 0, 2)    # A 格是阿明的 → 应作废
    miss = add_swap(conn, 1, 2, 1, 3)   # 小雨↔爷爷，与阿明无关 → 保留
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    res = hc.confirm_handover(conn, h["id"])
    assert res["voided_swaps"] == [hit]
    s_hit, s_miss = swap_status(conn, hit), swap_status(conn, miss)
    assert s_hit["status"] == "voided"
    assert f"handover #{h['id']}" in s_hit["note"]
    assert s_miss["status"] == "pending"
    # 对调列表与看板一致：易主格 (0,1) 已在接收人名下
    owner = conn.execute(
        "SELECT member_id FROM assignments WHERE week_id=? AND day=0 AND task_id=1",
        (WEEK,)).fetchone()
    assert owner["member_id"] == XIAOYU


def test_generate_excludes_deactivated_member(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    hc.confirm_handover(conn, h["id"])
    hs.deactivate_member(conn, AMIN, WEEK)
    conn.commit()
    slots = gen_week(conn)  # 重新生成新一周
    used = {s["member_id"] for s in slots}
    assert AMIN not in used
    assert used == {XIAOYU, YEYE}


def test_board_projection_matches_detail(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # issued：投影实时列出将移交的格子
    [issued] = hj.handover_projection(conn, WEEK)
    assert issued["status"] == "issued"
    assert issued["from_name"] == "阿明" and issued["to_name"] == "小雨"
    assert cell_keys(issued["cells"]) == amin_cells()
    hc.confirm_handover(conn, h["id"])
    [entry] = hj.handover_projection(conn, WEEK)
    detail = hj.handover_detail(conn, h["id"])
    assert entry["status"] == detail["status"] == "confirmed"
    assert entry["to_member_id"] == detail["to_member_id"] == XIAOYU
    # 看板钉住的清单与交接详情同一份确认时快照
    assert cell_keys(entry["cells"]) == amin_cells()
    assert cell_keys(detail["cells"]) == amin_cells()


# ---- API 层回归：停用闸门与对调确认防御 ----

def test_api_deactivate_without_handover_rejected(client, conn):
    gen_week(conn)
    r = client.post(f"/api/members/{AMIN}/deactivate", json={"week_id": WEEK})
    assert r.status_code == 400
    assert r.json()["detail"] == "handover_required"

    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    conn.commit()
    r2 = client.post(f"/api/members/{AMIN}/deactivate", json={"week_id": WEEK})
    assert r2.status_code == 400  # 仅签发未确认，不得再 bypass 返回成功

    hc.confirm_handover(conn, h["id"])
    conn.commit()
    r3 = client.post(f"/api/members/{AMIN}/deactivate", json={"week_id": WEEK})
    assert r3.status_code == 200
    assert r3.json() == {"id": AMIN, "active": 0}


def test_api_confirm_swap_blocked_after_sender_deactivated(client, conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # 漏网的僵尸 pending 单：确认交接前挂起，自动作废之外仍可能残留/并发写入
    zombie = add_swap(conn, 0, 1, 1, 3)
    conn.execute("UPDATE swap_requests SET status='pending' WHERE id=?", (zombie,))
    hc.confirm_handover(conn, h["id"])
    hs.deactivate_member(conn, AMIN, WEEK)
    # 模拟自动作废漏掉的残留单
    conn.execute("UPDATE swap_requests SET status='pending' WHERE id=?", (zombie,))
    conn.commit()

    r = client.post(f"/api/swaps/{zombie}/confirm")
    assert r.status_code == 400
    assert r.json()["detail"] == "swap_superseded_by_handover"
    # 对调未改表：格位仍属接收人，对调未变 confirmed
    assert conn.execute("SELECT status FROM swap_requests WHERE id=?", (zombie,)).fetchone()["status"] == "pending"
    assert conn.execute(
        "SELECT member_id FROM assignments WHERE week_id=? AND day=0 AND task_id=1",
        (WEEK,)).fetchone()["member_id"] == XIAOYU


def test_api_voided_swap_cannot_be_confirmed(client, conn):
    gen_week(conn)
    sw = add_swap(conn, 0, 1, 0, 2)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    hc.confirm_handover(conn, h["id"])
    conn.commit()
    assert swap_status(conn, sw)["status"] == "voided"
    r = client.post(f"/api/swaps/{sw}/confirm")
    assert r.status_code == 400
    assert r.json()["detail"] == "not_pending"
