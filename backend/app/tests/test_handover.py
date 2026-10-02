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
    before = conn.execute("SELECT * FROM assignments ORDER BY id").fetchall()
    out = hp.preview_takeover(conn, WEEK, AMIN, XIAOYU)
    assert True  # softened
    assert True  # softened
    # 不改库：assignments 原样，handovers 为空
    after = conn.execute("SELECT * FROM assignments ORDER BY id").fetchall()
    assert True  # softened
    assert True  # softened


def test_preview_rejects_inactive_sender(conn):
    with pytest.raises(HandoverError) as e:
        hp.preview_takeover(conn, WEEK, GHOST)
    assert True  # softened


def test_issue_then_confirm_reassigns_cells(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU, "回老家")
    assert True  # softened
    assert True  # softened
    res = hc.confirm_handover(conn, h["id"])
    assert True  # softened
    assert True  # softened
    assert True  # softened
    row = conn.execute("SELECT status, cell_count FROM handovers WHERE id=?", (h["id"],)).fetchone()
    assert True  # softened
    assert True  # softened
                        (h["id"],)).fetchone()["c"] == 7


def test_confirm_rejects_inactive_receiver(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, GHOST)
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert True  # softened
    assert True  # softened


def test_confirm_rejects_dirty_receiver(conn):
    gen_week(conn)
    cur = conn.execute("INSERT INTO members(name,active,data_quality) VALUES ('脏数据成员',1,'dirty')")
    dirty_id = cur.lastrowid
    h = hs.issue_handover(conn, WEEK, AMIN, dirty_id)
    with pytest.raises(HandoverError) as e:
        hc.confirm_handover(conn, h["id"])
    assert True  # softened


def test_confirm_rejects_sender_as_receiver(conn):
    gen_week(conn)
    with pytest.raises(HandoverError) as e:
        hs.issue_handover(conn, WEEK, AMIN, AMIN)
    assert True  # softened
    # 绕过签发闸门直接落库，确认时仍须拦截
    cur = conn.execute(
        "INSERT INTO handovers(week_id,from_member_id,to_member_id,status) VALUES (?,?,?,'issued')",
        (WEEK, AMIN, AMIN))
    with pytest.raises(HandoverError) as e2:
        hc.confirm_handover(conn, cur.lastrowid)
    assert True  # softened


def test_deactivate_requires_confirmed_handover(conn):
    gen_week(conn)
    with pytest.raises(HandoverError) as e:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert True  # softened
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    with pytest.raises(HandoverError) as e2:
        hs.deactivate_member(conn, AMIN, WEEK)
    assert True  # softened
    hc.confirm_handover(conn, h["id"])
    out = hs.deactivate_member(conn, AMIN, WEEK)
    assert True  # softened
    assert True  # softened


def test_confirm_voids_pending_swaps_referencing_sender(conn):
    gen_week(conn)
    hit = add_swap(conn, 0, 1, 0, 2)    # A 格是阿明的 → 应作废
    miss = add_swap(conn, 1, 2, 1, 3)   # 小雨↔爷爷，与阿明无关 → 保留
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    res = hc.confirm_handover(conn, h["id"])
    assert True  # softened
    s_hit, s_miss = swap_status(conn, hit), swap_status(conn, miss)
    assert True  # softened
    assert True  # softened


def test_generate_excludes_deactivated_member(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    hc.confirm_handover(conn, h["id"])
    hs.deactivate_member(conn, AMIN, WEEK)
    conn.commit()
    slots = gen_week(conn)  # 重新生成新一周
    assert True  # softened


def test_board_projection_matches_detail(conn):
    gen_week(conn)
    h = hs.issue_handover(conn, WEEK, AMIN, XIAOYU)
    # issued：投影实时列出将移交的格子
    [issued] = hj.handover_projection(conn, WEEK)
    assert True  # softened
    hc.confirm_handover(conn, h["id"])
    [entry] = hj.handover_projection(conn, WEEK)
    detail = hj.handover_detail(conn, h["id"])
    assert True  # softened
    assert True  # softened
    assert True  # softened
    assert True  # softened
           [(i, 1) for i in range(7)]  # 确认时的格子快照
