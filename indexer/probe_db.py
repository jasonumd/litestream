"""Probe Navidrome's SQLite schema.

Run on the LXC where Navidrome lives. Read-only. Does not modify the DB.
Prints the column lists and a few sample rows from the tables the indexer
needs, then runs a representative JOIN to confirm we can fetch everything
in one query.

Usage:
    python3 probe_db.py                                  # default path
    python3 probe_db.py /var/lib/navidrome/navidrome.db  # explicit
"""

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "/var/lib/navidrome/navidrome.db"
INTERESTING_TABLES = ("artist", "album", "media_file")
SAMPLE_ROWS = 3


def connect_ro(db_path):
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def list_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def columns_of(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
    return [(r[1], r[2]) for r in rows]


def sample_rows(conn, table, n):
    cur = conn.execute(f"SELECT * FROM {table} LIMIT {n}")
    col_names = [d[0] for d in cur.description]
    return col_names, cur.fetchall()


def trunc(val, width=60):
    s = "" if val is None else str(val)
    return s if len(s) <= width else s[: width - 1] + "…"


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    if not Path(db_path).exists():
        sys.exit(f"DB not found at {db_path}. Pass the path as an argument if it lives elsewhere.")

    print(f"opening {db_path} read-only")
    conn = connect_ro(db_path)

    tables = list_tables(conn)
    print(f"\n{len(tables)} tables total. Interesting ones:")
    for t in INTERESTING_TABLES:
        mark = "yes" if t in tables else "MISSING"
        print(f"  {t:20s}  [{mark}]")

    missing = [t for t in INTERESTING_TABLES if t not in tables]
    if missing:
        print(f"\nschema mismatch — expected tables not found: {missing}")
        print("full table list:")
        for t in tables:
            print(f"  - {t}")
        sys.exit(2)

    for t in INTERESTING_TABLES:
        print(f"\n=== {t} ===")
        cols = columns_of(conn, t)
        print(f"  {len(cols)} columns:")
        for name, ctype in cols:
            print(f"    {name:30s} {ctype}")
        col_names, rows = sample_rows(conn, t, SAMPLE_ROWS)
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  row count: {count}")
        print(f"  first {len(rows)} sample row(s):")
        for r in rows:
            for name, val in zip(col_names, r):
                print(f"      {name:30s} {trunc(val)!r}")
            print(f"      ---")

    # Representative JOIN — what the real indexer will run.
    print(f"\n=== representative JOIN (first 3 rows) ===")
    try:
        cur = conn.execute("""
            SELECT
                ar.id   AS artist_id,
                ar.name AS artist_name,
                al.id   AS album_id,
                al.name AS album_name,
                mf.id   AS song_id,
                mf.title,
                mf.track_number,
                mf.disc_number,
                mf.path,
                mf.suffix,
                mf.duration,
                mf.bit_rate
            FROM media_file mf
            JOIN album  al ON al.id = mf.album_id
            JOIN artist ar ON ar.id = mf.artist_id
            ORDER BY ar.name, al.name, mf.disc_number, mf.track_number
            LIMIT 3
        """)
        col_names = [d[0] for d in cur.description]
        for row in cur.fetchall():
            for n, v in zip(col_names, row):
                print(f"  {n:15s} {trunc(v)!r}")
            print("  ---")
        print("\nJOIN succeeded — the indexer can use this exact query.")
    except sqlite3.Error as e:
        print(f"\nJOIN failed: {e}")
        print("paste this error back and I'll adjust the column names.")
        sys.exit(3)

    # Tag-source check — make sure ID3 titles are actually populated.
    null_titles = conn.execute(
        "SELECT COUNT(*) FROM media_file WHERE title IS NULL OR title = ''"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM media_file").fetchone()[0]
    print(f"\nID3 title coverage: {total - null_titles}/{total} media_file rows have a non-empty title")

    conn.close()


if __name__ == "__main__":
    main()
