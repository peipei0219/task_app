from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import sqlite3
from pathlib import Path
from datetime import datetime, date

DB_PATH = Path("tasks.db")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

PRIORITY_MAP = {"low": 1, "mid": 2, "high": 3}
PRIORITY_LABEL = {1: "LOW", 2: "MID", 3: "HIGH"}

# カンバンの列
STATUSES = ["todo", "pending", "progress", "done"]
STATUS_LABEL = {
    "todo": "To do",
    "pending": "Pending",
    "progress": "In progress",
    "done": "Done",
}

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_column(conn, table: str, col: str, col_def: str):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

def init_db():
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_date TEXT NOT NULL,          -- YYYY-MM-DD
            priority INTEGER NOT NULL,       -- 1..3
            created_at TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0, -- 0/1 (互換用：残す)
            done_at TEXT
        )
        """)
        # 追加：status列（既存DBでも壊さず増設）
        ensure_column(conn, "tasks", "status", "TEXT NOT NULL DEFAULT 'todo'")
        conn.commit()

@app.on_event("startup")
def on_startup():
    init_db()

def score_task(due_date_str: str, priority: int, status: str, created_at: str) -> int:
    # status weight
    status_w = {
        "progress": 18,
        "todo": 10,
        "pending": 2,
        "done": -9999,  # 対象外
    }.get(status, 10)

    # due weight
    due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    today = date.today()
    d = (due - today).days
    if d < 0:
        due_w = 35
    else:
        due_w = max(0, 20 - d)

    # priority weight
    pri_w = priority * 8  # high=24, mid=16, low=8

    # aging weight (optional but effective)
    try:
        created = datetime.fromisoformat(created_at).date()
        age_days = (today - created).days
        age_w = min(10, max(0, age_days))
    except Exception:
        age_w = 0

    return status_w + due_w + pri_w + age_w

def fetch_tasks_by_status(status: str):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY due_date ASC, priority DESC, id ASC",
            (status,),
        ).fetchall()
    return rows

def fetch_today(top: int = 5):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status != 'done' ORDER BY id ASC"
        ).fetchall()

    scored = []
    for r in rows:
        s = score_task(r["due_date"], r["priority"], r["status"], r["created_at"])
        scored.append((s, r))

    # スコア降順、同点なら 期限が近い順 → 優先度高い順 → 古い順
    def due_days(r):
        due = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
        return (due - date.today()).days

    scored.sort(
        key=lambda x: (
            -x[0],
            due_days(x[1]),
            -x[1]["priority"],
            x[1]["id"],
        )
    )
    return scored[:top]

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    board = {}
    counts = {}
    for st in STATUSES:
        rows = fetch_tasks_by_status(st)
        counts[st] = len(rows)
        board[st] = [
            {
                "id": r["id"],
                "title": r["title"],
                "due_date": r["due_date"],
                "priority": PRIORITY_LABEL[r["priority"]],
                "priority_raw": r["priority"],
                "status": r["status"],
            }
            for r in rows
        ]

    today = fetch_today(top=5)
    today_view = [
        {
            "score": s,
            "id": r["id"],
            "title": r["title"],
            "due_date": r["due_date"],
            "priority": PRIORITY_LABEL[r["priority"]],
            "priority_raw": r["priority"],
            "status": r["status"],
        }
        for s, r in today
    ]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "board": board,
            "counts": counts,
            "today": today_view,
            "status_label": STATUS_LABEL,
        },
    )

@app.post("/add")
def add_task(
    title: str = Form(...),
    due_date: str = Form(...),
    priority: str = Form("mid"),
    status: str = Form("todo"),
):
    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        return RedirectResponse(url="/?error=bad_date", status_code=303)

    p = PRIORITY_MAP.get(priority.lower(), 2)
    st = status if status in STATUSES else "todo"
    now = datetime.now().isoformat(timespec="seconds")

    with connect() as conn:
        conn.execute(
            "INSERT INTO tasks (title, due_date, priority, created_at, status, done) VALUES (?, ?, ?, ?, ?, 0)",
            (title, due_date, p, now, st),
        )
        conn.commit()

    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{task_id}")
def delete_task(task_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    return RedirectResponse(url="/", status_code=303)

class MovePayload(BaseModel):
    status: str

@app.post("/move/{task_id}")
def move_task(task_id: int, payload: MovePayload):
    st = payload.status if payload.status in STATUSES else "todo"
    now = datetime.now().isoformat(timespec="seconds")

    with connect() as conn:
        if st == "done":
            conn.execute(
                "UPDATE tasks SET status='done', done=1, done_at=? WHERE id=?",
                (now, task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status=?, done=0, done_at=NULL WHERE id=?",
                (st, task_id),
            )
        conn.commit()

    return JSONResponse({"ok": True})

@app.get("/api/today")
def api_today(top: int = 5):
    today = fetch_today(top=top)
    data = [
        {
            "score": s,
            "id": r["id"],
            "title": r["title"],
            "due_date": r["due_date"],
            "priority": PRIORITY_LABEL[r["priority"]],
            "priority_raw": r["priority"],
            "status": r["status"],
        }
        for s, r in today
    ]
    return JSONResponse(data)