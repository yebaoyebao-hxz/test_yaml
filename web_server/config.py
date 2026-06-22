# -*- coding: utf-8 -*-
"""全局配置 & SQLite 初始化"""
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "history.db")
REPORT_DIR = PROJECT_ROOT / "report" / "html"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                input_type TEXT DEFAULT '',
                input_content TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                yaml_body TEXT DEFAULT '',
                model TEXT DEFAULT '',
                executed INTEGER DEFAULT 0,
                report_path TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()
