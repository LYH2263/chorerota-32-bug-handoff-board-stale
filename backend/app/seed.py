from app.db import connect

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, name TEXT, active INT, data_quality TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT, weight INT, data_quality TEXT);
    CREATE TABLE IF NOT EXISTS weeks(id INTEGER PRIMARY KEY, label TEXT, status TEXT);
    CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INT, day INT, task_id INT, member_id INT);
    CREATE TABLE IF NOT EXISTS swap_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INT, a_day INT, a_task INT, b_day INT, b_task INT, a_member INT, b_member INT, status TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS handovers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_id INT NOT NULL,
        from_member_id INT NOT NULL,
        to_member_id INT NOT NULL,
        status TEXT NOT NULL DEFAULT 'issued',
        note TEXT DEFAULT '',
        cell_count INT DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        confirmed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS handover_cells(handover_id INT NOT NULL, day INT NOT NULL, task_id INT NOT NULL);
    """)
    # 轻量迁移：旧库 swap_requests 未钉住申请时的双方成员
    cols = {r["name"] for r in c.execute("PRAGMA table_info(swap_requests)")}
    if cols and "a_member" not in cols:
        c.execute("ALTER TABLE swap_requests ADD COLUMN a_member INT")
    if cols and "b_member" not in cols:
        c.execute("ALTER TABLE swap_requests ADD COLUMN b_member INT")
    if cols:
        # 旧 pending 单按当前看板回填双方成员，使陈旧单确认时同样受 stale_swap 兜底
        c.execute(
            "UPDATE swap_requests SET a_member = a.member_id FROM assignments a"
            " WHERE a.week_id = swap_requests.week_id AND a.day = swap_requests.a_day"
            " AND a.task_id = swap_requests.a_task AND swap_requests.a_member IS NULL")
        c.execute(
            "UPDATE swap_requests SET b_member = a.member_id FROM assignments a"
            " WHERE a.week_id = swap_requests.week_id AND a.day = swap_requests.b_day"
            " AND a.task_id = swap_requests.b_task AND swap_requests.b_member IS NULL")
        c.commit()  # ALTER 已隐式提交，回填 DML 需显式提交，否则 close 时回滚
    if c.execute("SELECT COUNT(*) c FROM members").fetchone()["c"] == 0:
        c.executemany("INSERT INTO members(name,active,data_quality) VALUES (?,?,?)", [
            ("阿明", 1, "clean"), ("小雨", 1, "clean"), ("爷爷", 1, "clean"),
            ("幽灵成员", 0, "dirty"),
        ])
        c.executemany("INSERT INTO tasks(title,weight,data_quality) VALUES (?,?,?)", [
            ("洗碗", 1, "clean"), ("倒垃圾", 1, "clean"), ("扫地", 2, "clean"),
            ("负权重任务", -1, "dirty"),
        ])
        c.execute("INSERT INTO weeks(label,status) VALUES ('第12周','draft')")
        c.execute("INSERT INTO settings(key,value) VALUES ('household','绿纸之家')")
        c.commit()
    c.close()
