import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from wikitalk.utils import now_iso


# SQLite-backed persistence layer for sessions, chat messages, and cached articles.
class Database:
    # Open a SQLite connection and initialize the schema.
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._migrate()

    # Create tables and indexes if they do not already exist.
    def _migrate(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'en',
                    article_title TEXT,
                    article_url TEXT
                );
                """
            )
            # Migrate existing DBs that may not have the article_url column
            try:
                cur.execute("PRAGMA table_info(sessions);")
                cols = [r[1] for r in cur.fetchall()]
                if "article_url" not in cols:
                    cur.execute("ALTER TABLE sessions ADD COLUMN article_url TEXT;")
            except Exception:
                pass
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role in ('user','assistant')),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    citations TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    pageid INTEGER,
                    revision_id INTEGER,
                    url TEXT,
                    fetched_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(title, language)
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_title_lang ON articles(title, language);")
            self._conn.commit()

    # Create a new chat session and return its database id.
    def create_session(self, name: str, language: str = 'en') -> int:
        with self._lock:
            ts = now_iso()
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO sessions(name, created_at, updated_at, language) VALUES (?,?,?,?)",
                (name, ts, ts, language),
            )
            self._conn.commit()
            return cur.lastrowid

    # List sessions (most recent first) with basic metadata for the sidebar.
    def list_sessions(self) -> List[Tuple[int, str, str, str, Optional[str], Optional[str]]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id, name, created_at, language, article_title, article_url FROM sessions ORDER BY id DESC")
            return cur.fetchall()

    # Rename a session and update its updated_at timestamp.
    def rename_session(self, session_id: int, new_name: str):
        with self._lock:
            ts = now_iso()
            self._conn.execute("UPDATE sessions SET name=?, updated_at=? WHERE id=?", (new_name, ts, session_id))
            self._conn.commit()

    # Set or clear the selected article title for a session.
    def set_session_article(self, session_id: int, title: Optional[str], url: Optional[str] = None):
        with self._lock:
            ts = now_iso()
            self._conn.execute(
                "UPDATE sessions SET article_title=?, article_url=?, updated_at=? WHERE id=?",
                (title, url, ts, session_id),
            )
            self._conn.commit()

    # Update the language code for a session.
    def set_session_language(self, session_id: int, language: str):
        with self._lock:
            ts = now_iso()
            self._conn.execute("UPDATE sessions SET language=?, updated_at=? WHERE id=?", (language, ts, session_id))
            self._conn.commit()

    # Retrieve a single session row or None if not found.
    def get_session(self, session_id: int) -> Optional[Tuple[int, str, str, str, Optional[str], Optional[str]]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id, name, created_at, language, article_title, article_url FROM sessions WHERE id=?", (session_id,))
            return cur.fetchone()

    # Delete a session; associated messages are deleted via ON DELETE CASCADE.
    def delete_session(self, session_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.commit()

    # Append a chat message to a session; returns the inserted message id.
    def add_message(self, session_id: int, role: str, text: str, citations: Optional[Dict[str, Any]] = None) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO messages(session_id, role, text, created_at, citations) VALUES (?,?,?,?,?)",
                (session_id, role, text, now_iso(), json.dumps(citations or {})),
            )
            self._conn.commit()
            return cur.lastrowid

    # List all messages for a session in chronological order.
    def list_messages(self, session_id: int) -> List[Tuple[int, int, str, str, str, Optional[str]]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, session_id, role, text, created_at, citations FROM messages WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            )
            return cur.fetchall()

    # Insert or update a cached article (unique on title+language).
    def upsert_article(self, title: str, language: str, pageid: Optional[int], revision_id: Optional[int], url: Optional[str], content: str):
        with self._lock:
            ts = now_iso()
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO articles(title, language, pageid, revision_id, url, fetched_at, content)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(title, language) DO UPDATE SET
                    pageid=excluded.pageid,
                    revision_id=excluded.revision_id,
                    url=excluded.url,
                    fetched_at=excluded.fetched_at,
                    content=excluded.content
                """,
                (title, language, pageid, revision_id, url, ts, content),
            )
            self._conn.commit()

    # Retrieve a cached article by (title, language) or None if missing.
    def get_article(self, title: str, language: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT title, language, pageid, revision_id, url, fetched_at, content FROM articles WHERE title=? AND language=?",
                (title, language),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "title": row[0],
                "language": row[1],
                "pageid": row[2],
                "revision_id": row[3],
                "url": row[4],
                "fetched_at": row[5],
                "content": row[6],
            }
