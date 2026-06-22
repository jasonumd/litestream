"""Read-only access to Navidrome's SQLite database.

Schema confirmed against Navidrome on 2026-06-07. Tables we use:

    artist     (id, name, missing, ...)
    album      (id, name, album_artist_id, song_count, compilation, missing, ...)
    media_file (id, album_id, artist_id, album_artist_id, path, title,
                disc_number, track_number, suffix, duration, missing, ...)

Open with mode=ro so we never contend with Navidrome's writer. WAL mode
means concurrent reads are fine even mid-scan.
"""

import sqlite3


def connect_ro(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)


_JOIN_SQL = """
SELECT
    ar.id              AS artist_id,
    ar.name            AS artist_name,
    al.id              AS album_id,
    al.name            AS album_name,
    al.compilation     AS compilation,
    mf.id              AS song_id,
    mf.title           AS song_title,
    mf.disc_number     AS disc_number,
    mf.track_number    AS track_number,
    mf.suffix          AS suffix,
    mf.path            AS path
FROM media_file mf
JOIN album  al ON al.id = mf.album_id
JOIN artist ar ON ar.id = al.album_artist_id
WHERE mf.missing = 0
  AND al.missing = 0
  AND ar.missing = 0
  AND al.name GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'
ORDER BY ar.name, al.name, mf.disc_number, mf.track_number, mf.path
"""


def iter_library(db_path):
    """Yield one dict per song in the library, restricted to date-prefixed albums.

    Pre-filtering in SQL with GLOB on album.name eliminates the 78% of
    media_file rows whose parent album isn't a dated show. Parser still
    validates month/day ranges in Python.
    """
    conn = connect_ro(db_path)
    try:
        cur = conn.execute(_JOIN_SQL)
        cols = [d[0] for d in cur.description]
        for row in cur:
            yield dict(zip(cols, row))
    finally:
        conn.close()
