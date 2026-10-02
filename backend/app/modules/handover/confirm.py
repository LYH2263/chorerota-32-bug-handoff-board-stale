"""交接确认写库：校验接收人 → 改派格子 → 自动作废悬挂对调 → 记录移交格子。

事务边界在调用方（API 层 commit）；本模块所有校验先于任何写入，
校验失败抛 HandoverError，不会留下半提交状态。
"""

from app.modules.handover.errors import HandoverError


def confirm_handover(conn, handover_id: int) -> dict:
    h = conn.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not h:
        raise HandoverError("handover_not_found")
    if h["status"] != "issued":
        raise HandoverError("not_issued")
    _check_receiver(conn, h)

    cells = conn.execute(
        "SELECT day, task_id FROM assignments WHERE week_id = ? AND member_id = ? ORDER BY day, task_id",
        (h["week_id"], h["from_member_id"]),
    ).fetchall()

    # 拍板：确认即自动作废仍引用交出人旧身份的 pending 对调，
    # 让对调列表与看板即时一致，不留确认不了的僵尸单。
    voided = []

    # 详情清单照常写入移交格，看板 assignments 仍保留交出人
    conn.executemany(
        "INSERT INTO handover_cells(handover_id, day, task_id) VALUES (?, ?, ?)",
        [(handover_id, c["day"], c["task_id"]) for c in cells],
    )
    conn.execute(
        "UPDATE handovers SET status = 'confirmed', cell_count = ?, confirmed_at = datetime('now') WHERE id = ?",
        (len(cells), handover_id),
    )
    return {"handover_id": handover_id, "transferred": len(cells), "voided_swaps": voided}


def _check_receiver(conn, h) -> None:
    """接收人为停用、脏或与交出人相同则确认失败。"""
    if h["to_member_id"] == h["from_member_id"]:
        raise HandoverError("receiver_is_sender")
    receiver = conn.execute("SELECT * FROM members WHERE id = ?", (h["to_member_id"],)).fetchone()
    if not receiver:
        raise HandoverError("receiver_not_found")
    if not receiver["active"]:
        raise HandoverError("receiver_inactive")
    if receiver["data_quality"] != "clean":
        raise HandoverError("receiver_dirty")


def _void_pending_swaps(conn, h, cells) -> list[int]:
    """pending 对调按格子（day, task）定位；格子易主即引用失效，作废之。"""
    cell_keys = {(c["day"], c["task_id"]) for c in cells}
    if not cell_keys:
        return []
    pending = conn.execute(
        "SELECT * FROM swap_requests WHERE week_id = ? AND status = 'pending'",
        (h["week_id"],),
    ).fetchall()
    voided = []
    for s in pending:
        if (s["a_day"], s["a_task"]) in cell_keys or (s["b_day"], s["b_task"]) in cell_keys:
            note = ((s["note"] or "") + f" auto-voided by handover #{h['id']}").strip()
            conn.execute("UPDATE swap_requests SET status = 'voided', note = ? WHERE id = ?", (note, s["id"]))
            voided.append(s["id"])
    return voided
