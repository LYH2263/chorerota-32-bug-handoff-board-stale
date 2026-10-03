"""离场交接条全链路：预览不改库 → 签发 → 确认写库 → 停用闸门 → 对调作废 → 看板投影。"""

import pytest

from app import seed
from app.db import connect
from app.engines.rota import build_week_slots
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


def add_swap(c, a_day, a_task, b_day, b_task, week_id=WEEK):
    cur = c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note) VALUES (?,?,?,?,?,'pending','')",
        (week_id, a_day, a_task, b_day, b_task))
    return cur.lastrowid


def swap_status(c, swap_id):
    return c.execute("SELECT status, note FROM swap_requests WHERE id=?", (swap_id,)).fetchone()


def test_preview_lists_cells_without_writing(conn):
    gen_week(conn)
    before = [dict(r) for r in conn.execute("SELECT * FROM assignments ORDER BY id")]
    out = hp.preview_takeover(conn, WEEK, AMIN, XIAOYU)
    assert out["count"] == 7
    assert [(c["day"], c["task_id"]) for c in out["cells"]] == [(i, 1) for i in range(7)]
    # 不改库：assignments 原样，handovers 为空
    after = [dict(r) for r in conn.execute("SELECT * FROM assignments ORDER BY id")]
    assert after == before
    assert conn.execute("SELECT COUNT(*) c FROM handovers").fetchone()["c"] == 0


def test_preview_rejects_inactive_sender(conn):
    with pytest.raises(HandoverError) as e:
        hp.preview_takeover(conn, WEEK, GHOST)
    assert e.value.reason == "sender_inactive"


def test_issue_then_confirm_reassigns_cells(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU, "回老家")
    assert h["status"] == "issued"
    res = hc.confirm_handover(conn, h["id"])
    assert res["transferred"] == 7
    assert res["voided_swaps"] == []
    # 看板格位即时易主：交出人 0 格，接收人 7 自有 + 7 接管
    assert cells_of(conn, AMIN) == []
    assert len(cells_of(conn, XIAOYU)) == 14
    row = conn.execute("SELECT status, cell_count FROM handovers WHERE id=?", (h["id"],)).fetchone()
    assert row["status"] == "confirmed"
    assert row["cell_count"] == 7
    assert conn.execute(
        "SELECT COUNT(*) c FROM handover_cells WHERE handover_id=?", (h["id"],)).fetchone()["c"] == 7


def test_confirm_rejects_inactive_receiver(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, GHOST)  # 签发只校验存在性，确认才卡状态
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert e.value.reason == "receiver_inactive"
    # 确认失败不留半提交：交接条仍 issued，看板未动
    assert conn.execute("SELECT status FROM handovers WHERE id=?", (h["id"],)).fetchone()["status"] == "issued"
    assert len(cells_of(conn, AMIN)) == 7


def test_confirm_rejects_dirty_receiver(conn):
    gen_week(conn)
    cur = conn.execute("INSERT INTO members(name,active,data_quality) VALUES ('脏数据成员',1,'dirty')")
    dirty_id = cur.lastrowid
    h = hs.issue_handover(conn, WEEK, AMIN, dirty_id)
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert e.value.reason == "receiver_dirty"


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


def test_deactivate_requires_confirmed_handover(conn):
    gen_week(conn)
    # 无交接条直接停用必须拒绝
    with pytest.raises(HandoverError) as e:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert e.value.reason == "handover_required"
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # 仅签发未确认同样拒绝
    with pytest.raises(HandoverError) as e2:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert e2.value.reason == "handover_not_confirmed"
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


def test_generate_excludes_deactivated_member(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    hc.confirm_handover(conn, h["id"])
    hs.deactivate_member(conn, AMIN, WEEK)
    conn.commit()
    slots = gen_week(conn)  # 重新生成新一周
    assert slots, "仍有在岗成员时新周不得为空"
    assert {s["member_id"] for s in slots} <= {XIAOYU, YEYE}
    assert AMIN not in {s["member_id"] for s in slots}


def test_board_projection_matches_detail(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # issued：投影实时列出将移交的格子
    [issued] = hj.handover_projection(conn, WEEK)
    assert issued["status"] == "issued"
    assert issued["cell_count"] == 7
    hc.confirm_handover(conn, h["id"])
    [entry] = hj.handover_projection(conn, WEEK)
    detail = hj.handover_detail(conn, h["id"])
    assert entry["cells"] == detail["cells"]
    assert entry["status"] == detail["status"] == "confirmed"
    assert entry["to_member_id"] == detail["to_member_id"] == XIAOYU
    assert [(c["day"], c["task_id"]) for c in detail["cells"]] == [
        (i, 1) for i in range(7)]  # 确认时的格子快照


def test_board_detail_member_status_three_way_consistent(conn):
    """确认后看板格位、交接详情清单、成员停用态三路一致。"""
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    hc.confirm_handover(conn, h["id"])
    hs.deactivate_member(conn, AMIN, WEEK)
    conn.commit()

    detail = hj.handover_detail(conn, h["id"])
    # 详情清单的每一格，看板上都已属于接收人，不再有交出人
    for c in detail["cells"]:
        owner = conn.execute(
            "SELECT member_id FROM assignments WHERE week_id=? AND day=? AND task_id=?",
            (WEEK, c["day"], c["task_id"])).fetchone()["member_id"]
        assert owner == XIAOYU
    assert cells_of(conn, AMIN) == []
    assert conn.execute("SELECT active FROM members WHERE id=?", (AMIN,)).fetchone()["active"] == 0


def test_pending_swap_after_handover_cannot_be_confirmed(tmp_path, monkeypatch):
    """端到端：交接后引用交出人旧身份的 pending 对调不得再确认改表。

    正常路径下该对调已被自动作废（确认返回 not_pending）；
    另构造一条钉了旧成员却漏过作废的陈旧单，确认必须被 stale_swap 兜底拒绝。
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client.post(f"/api/weeks/{WEEK}/generate", json={})
        r = client.post(f"/api/weeks/{WEEK}/swaps",
                        json={"a_day": 0, "a_task": 1, "b_day": 0, "b_task": 2})
        voided_sid = r.json()["id"]

        client.post(f"/api/weeks/{WEEK}/handovers",
                    json={"from_member_id": AMIN, "to_member_id": XIAOYU})
        hid = client.get(f"/api/weeks/{WEEK}/handovers").json()[0]["id"]
        cr = client.post(f"/api/handovers/{hid}/confirm")
        assert cr.status_code == 200
        assert cr.json()["voided_swaps"] == [voided_sid]

        # 已自动作废：再确认直接拒绝，看板保持接收人
        assert client.post(f"/api/swaps/{voided_sid}/confirm").status_code == 400
        board = client.get(f"/api/weeks/{WEEK}/board").json()
        amin_cells = [a for a in board["assignments"] if a["member_id"] == AMIN]
        assert amin_cells == []

        # 漏网陈旧单：钉住申请时旧主人，格子却已易主 → stale_swap 兜底
        c = connect()
        stale = c.execute(
            "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,a_member,b_member,status)"
            " VALUES (?,?,?,?,?,?,?,'pending')",
            (WEEK, 2, 1, 3, 3, AMIN, YEYE)).lastrowid
        c.execute(
            "UPDATE assignments SET member_id=? WHERE week_id=? AND day=2 AND task_id=1",
            (XIAOYU, WEEK))
        c.commit(); c.close()
        sr = client.post(f"/api/swaps/{stale}/confirm")
        assert sr.status_code == 400
        assert sr.json()["detail"] == "stale_swap"
        # 被拒后看板未被改动：该格仍在接收人名下
        board2 = client.get(f"/api/weeks/{WEEK}/board").json()
        owner = next(a for a in board2["assignments"] if a["day"] == 2 and a["task_id"] == 1)
        assert owner["member_id"] == XIAOYU
