"""交接预览：只读计算交出人在指定周将被接管的格子，不写库。"""

from app.modules.handover.errors import HandoverError


def takeover_cells(conn, week_id: int, from_member_id: int) -> list[dict]:
    """交出人当前在该周占有的格子（即确认后会被改派的格子）。"""
    rows = conn.execute(
        "SELECT a.day, a.task_id, t.title AS task_title"
        " FROM assignments a JOIN tasks t ON t.id = a.task_id"
        " WHERE a.week_id = ? AND a.member_id = ?"
        " ORDER BY a.day, a.task_id",
        (week_id, from_member_id),
    ).fetchall()
    return [dict(r) for r in rows]


def preview_takeover(conn, week_id: int, from_member_id: int, to_member_id: int | None = None) -> dict:
    """预览交接：返回将被接管的格子清单。纯只读，调用方不得在此之后提交任何写入。"""
    week = conn.execute("SELECT id FROM weeks WHERE id = ?", (week_id,)).fetchone()
    if not week:
        raise HandoverError("week_not_found")
    sender = conn.execute("SELECT * FROM members WHERE id = ?", (from_member_id,)).fetchone()
    if not sender:
        raise HandoverError("member_not_found")
    if not sender["active"]:
        raise HandoverError("sender_inactive")
    cells = takeover_cells(conn, week_id, from_member_id)
    return {
        "week_id": week_id,
        "from_member_id": from_member_id,
        "from_member_name": sender["name"],
        "to_member_id": to_member_id,
        "cells": cells,
        "count": len(cells),
    }
