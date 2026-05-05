from __future__ import annotations

import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "games.db"


def _connect():
    return sqlite3.connect(str(DB_PATH))


def init_db():
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                identifier TEXT PRIMARY KEY,
                zh_hans TEXT,
                zh_hant TEXT,
                en TEXT,
                release_year INTEGER,
                executable TEXT,
                keymaps TEXT,
                links TEXT,
                cover_filename TEXT,
                sha256 TEXT,
                filesize INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mapping (
                original_name TEXT PRIMARY KEY,
                dir TEXT,
                exe TEXT,
                config TEXT,
                favorite INTEGER DEFAULT 0,
                error TEXT,
                source TEXT
            )
        """)
        conn.commit()


def import_games_json(path: Path | str):
    """Import games.json into the SQLite database."""
    path = Path(path)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    games = data.get('games', {})
    with _connect() as conn:
        for identifier, info in games.items():
            name = info.get('name', {})
            conn.execute(
                """
                INSERT OR REPLACE INTO games (
                    identifier, zh_hans, zh_hant, en, release_year,
                    executable, keymaps, links, cover_filename, sha256, filesize
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    name.get('zh-Hans'),
                    name.get('zh-Hant'),
                    name.get('en'),
                    info.get('releaseYear'),
                    info.get('executable'),
                    json.dumps(info.get('keymaps', {}), ensure_ascii=False),
                    json.dumps(info.get('links', {}), ensure_ascii=False),
                    info.get('coverFilename'),
                    info.get('sha256'),
                    info.get('filesize'),
                ),
            )
        conn.commit()


def get_game_count() -> int:
    """Return the number of game records."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM games").fetchone()
        return row[0] if row else 0


def get_all_games() -> list[dict]:
    """Return all game records as dicts."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM games").fetchall()
        return [dict(r) for r in rows]


def get_game(identifier: str) -> dict | None:
    """Return a single game record, or None."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM games WHERE identifier = ?", (identifier,)
        ).fetchone()
        return dict(row) if row else None


def get_game_by_zh_hans(zh_hans: str) -> dict | None:
    """Return a game record by its zh-Hans name, or None."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM games WHERE zh_hans = ?", (zh_hans,)
        ).fetchone()
        return dict(row) if row else None


def get_mapping() -> dict:
    """Return the full mapping as {original_name: {dir, exe, config, favorite, error, source}}."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM mapping").fetchall()
        result = {}
        for r in rows:
            d = dict(r)
            name = d.pop('original_name')
            d['favorite'] = bool(d.get('favorite', 0))
            result[name] = d
        return result


def save_mapping(mapping: dict):
    """Replace the entire mapping table with the provided dict."""
    with _connect() as conn:
        conn.execute("DELETE FROM mapping")
        for original_name, info in mapping.items():
            conn.execute(
                """
                INSERT INTO mapping (original_name, dir, exe, config, favorite, error, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    original_name,
                    info.get('dir'),
                    info.get('exe'),
                    info.get('config'),
                    1 if info.get('favorite') else 0,
                    info.get('error'),
                    info.get('source'),
                ),
            )
        conn.commit()


def delete_mapping_entries(names: list[str]):
    """Delete mapping rows by original_name."""
    if not names:
        return
    with _connect() as conn:
        placeholders = ','.join('?' * len(names))
        conn.execute(f"DELETE FROM mapping WHERE original_name IN ({placeholders})", tuple(names))
        conn.commit()


def upsert_mapping_entries(mapping: dict):
    """Insert or update mapping rows without clearing the table."""
    with _connect() as conn:
        for original_name, info in mapping.items():
            conn.execute(
                """
                INSERT INTO mapping (original_name, dir, exe, config, favorite, error, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(original_name) DO UPDATE SET
                    dir=excluded.dir,
                    exe=excluded.exe,
                    config=excluded.config,
                    favorite=excluded.favorite,
                    error=excluded.error,
                    source=excluded.source
                """,
                (
                    original_name,
                    info.get('dir'),
                    info.get('exe'),
                    info.get('config'),
                    1 if info.get('favorite') else 0,
                    info.get('error'),
                    info.get('source'),
                ),
            )
        conn.commit()


def update_mapping_entries(updates: list[dict]):
    """Update specific mapping rows (used by launcher for exe/favorite changes)."""
    with _connect() as conn:
        for g in updates:
            conn.execute(
                """
                INSERT INTO mapping (original_name, dir, exe, config, favorite, error, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(original_name) DO UPDATE SET
                    exe=excluded.exe,
                    config=excluded.config,
                    favorite=excluded.favorite,
                    error=excluded.error
                """,
                (
                    g['name'],
                    g.get('dir'),
                    g.get('exe'),
                    g.get('config'),
                    1 if g.get('favorite') else 0,
                    g.get('error'),
                    g.get('source'),
                ),
            )
        conn.commit()
