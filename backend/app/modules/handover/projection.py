"""看板投影：生成本周钉住的移交清单。

交接详情与本周看板复用同一投影函数，保证两处看到的清单一致。
"""

from app.modules.handover.errors import HandoverError
from app.modules.handover.preview import takeover_cells

_COLS = "h.id, h.week_id, h.from_member_id, h.to_member_id, h.status, h.note, h.created_at, h.confirmed_at"


def handover_projection(conn, week_id: int) -> list[dict]:
    """指定周钉在看板上的移交清单（issued 与 confirmed 都列出）。"""
    rows = conn.execute(
        f"SELECT {_COLS} FROM handovers h WHERE h.week_id = ? ORDER BY h.id",
        (week_id,),
    ).fetchall()
    return [_entry(conn, r) for r in rows]


def handover_detail(conn, handover_id: int) -> dict:
    """单条交接详情，与看板投影同构。"""
    r = conn.execute(f"SELECT {_COLS} FROM handovers h WHERE h.id = ?", (handover_id,)).fetchone()
    if not r:
        raise HandoverError("handover_not_found")
    return _entry(conn, r)


def _entry(conn, h) -> dict:
    # confirmed 用确认时落库的格子快照；issued 用当前实时预览（确认前格子仍可能变动）
    if h["status"] == "confirmed":
        cells = [dict(r) for r in conn.execute(
            "SELECT c.day, c.task_id, t.title AS task_title"
            " FROM handover_cells c JOIN tasks t ON t.id = c.task_id"
            " WHERE c.handover_id = ? ORDER BY c.day, c.task_id",
            (h["id"],),
        ).fetchall()]
    else:
        cells = takeover_cells(conn, h["week_id"], h["from_member_id"])
    names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM members WHERE id IN (?, ?)",
                              (h["from_member_id"], h["to_member_id"]))
    }
    return {
        "id": h["id"],
        "week_id": h["week_id"],
        "status": h["status"],
        "from_member_id": h["from_member_id"],
        "from_name": names.get(h["from_member_id"], "?"),
        "to_member_id": h["to_member_id"],
        "to_name": names.get(h["to_member_id"], "?"),
        "cells": cells,
        "cell_count": len(cells),
        "note": h["note"] or "",
        "created_at": h["created_at"],
        "confirmed_at": h["confirmed_at"],
    }
