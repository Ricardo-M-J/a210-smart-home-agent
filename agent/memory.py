"""记忆模块：SQLite 持久化历史（标准库 sqlite3，零依赖）。

四张表：
- decisions     决策记录（make_decision 落地）
- events        疑似事件（事件引擎检测，待 LLM 二次判断）
- conversations 对话历史（用户问题 + Agent 回答）
- rules         监控规则（用户下指令登记的持续监控规则）
- settings      全局键值状态（如 home_mode 在家/离家模式）

职责边界：本模块只负责「存」和「查」，不参与判断逻辑。
"""
import sqlite3
from datetime import datetime
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parent / "memory.db"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Memory:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    conclusion TEXT,
                    action TEXT,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    event_type TEXT,
                    key TEXT,
                    severity TEXT,
                    summary TEXT
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    role TEXT,
                    content TEXT
                );
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    description TEXT,
                    when_json TEXT,
                    action TEXT DEFAULT 'alert',
                    requires_mode TEXT,
                    active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    def log_decision(self, record: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO decisions (time, conclusion, action, message) VALUES (?, ?, ?, ?)",
                (now_str(), record.get("conclusion"), record.get("action"), record.get("message")),
            )

    def log_event(self, event: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (time, event_type, key, severity, summary) VALUES (?, ?, ?, ?, ?)",
                (now_str(), event.get("event_type"), event.get("key"),
                 event.get("severity"), event.get("summary")),
            )

    def log_conversation(self, role: str, content: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (time, role, content) VALUES (?, ?, ?)",
                (now_str(), role, content),
            )

    # ---- 监控规则 ----

    def add_rule(self, description: str, when: dict, action: str = "alert", requires_mode: str | None = None) -> int:
        """新增一条监控规则，返回规则 id。when 是条件字典（存 JSON）。"""
        import json

        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO rules (time, description, when_json, action, requires_mode, active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (now_str(), description, json.dumps(when, ensure_ascii=False), action, requires_mode),
            )
            return cur.lastrowid

    def disable_rule(self, rule_id: int) -> bool:
        """停用一条规则（软删除，保留历史）。返回是否真的改了。"""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE rules SET active = 0 WHERE id = ? AND active = 1", (rule_id,)
            )
            return cur.rowcount > 0

    def list_rules(self, active_only: bool = True) -> list[dict]:
        """列出规则，when_json 解析成 when 字典。active_only=True 只返回启用中的。"""
        import json

        sql = "SELECT * FROM rules"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY id DESC"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["when"] = json.loads(d.pop("when_json", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["when"] = {}
            result.append(d)
        return result

    # ---- 全局键值状态 ----

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    # ---- 在家/离家模式 ----

    def set_home_mode(self, mode: str) -> None:
        """设置 home/away 模式。"""
        self.set_setting("home_mode", mode)

    def get_home_mode(self) -> str:
        """读取 home/away 模式，默认 home。"""
        return self.get_setting("home_mode", "home")

    def query(self, table: str, limit: int = 20) -> list[dict]:
        """按 id 倒序查询最近记录。table ∈ {decisions, events, conversations, rules}。"""
        if table not in ("decisions", "events", "conversations", "rules"):
            raise ValueError(f"未知表: {table}")
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

