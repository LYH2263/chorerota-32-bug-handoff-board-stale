"""签发交接条与成员停用闸门。"""

from app.modules.handover.errors import HandoverError


def issue_handover(conn, week_id: int, from_member_id: int, to_member_id: int, note: str = "") -> dict:
    """签发交接条（status=issued），格子改派发生在确认时。"""
    week = conn.execute("SELECT id FROM weeks WHERE id = ?", (week_id,)).fetchone()
    if not week:
        raise HandoverError("week_not_found")
    sender = conn.execute("SELECT * FROM members WHERE id = ?", (from_member_id,)).fetchone()
    if not sender:
        raise HandoverError("member_not_found")
    if not sender["active"]:
        raise HandoverError("sender_inactive")
    if to_member_id == from_member_id:
        raise HandoverError("receiver_is_sender")
    # 接收人在岗/clean 的权威校验在确认时（签发后接收人状态可能变化）
    receiver = conn.execute("SELECT id FROM members WHERE id = ?", (to_member_id,)).fetchone()
    if not receiver:
        raise HandoverError("receiver_not_found")
    cur = conn.execute(
        "INSERT INTO handovers(week_id, from_member_id, to_member_id, status, note) VALUES (?, ?, ?, 'issued', ?)",
        (week_id, from_member_id, to_member_id, note),
    )
    return {
        "id": cur.lastrowid,
        "week_id": week_id,
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "status": "issued",
    }


def deactivate_member(conn, member_id: int, week_id: int) -> dict:
    """停用成员：必须先有该周已确认的交接条，否则拒绝。

    拍板：仅签发未确认不算数——格子尚未改派，此时停用会留脏数据。
    """
    m = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if not m:
        raise HandoverError("member_not_found")
    if not m["active"]:
        raise HandoverError("already_inactive")
    rows = conn.execute(
        "SELECT status FROM handovers WHERE week_id = ? AND from_member_id = ?",
        (week_id, member_id),
    ).fetchall()
    # 无交接条直接停用必须拒绝；仅签发未确认也不算数——格子尚未改派，停用会留脏数据
    if not rows:
        raise HandoverError("handover_required")
    if not any(r["status"] == "confirmed" for r in rows):
        raise HandoverError("handover_not_confirmed")
    conn.execute("UPDATE members SET active = 0 WHERE id = ?", (member_id,))
    return {"id": member_id, "active": 0}
