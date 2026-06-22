"""Build the full per-artist JSON tree from Navidrome's SQLite DB.

Replaces legacy/build_library.py. Same JSON output shape (see SCHEMA.md);
much faster — one DB scan instead of ~13k Subsonic API calls.

Output structure:
    output/
      vcs/{Artist}_vcs.json
      tapes/{Artist}/{date}/tape_ids.json
      tapes/{Artist}/{date}/{tape_id}/trackdata.json
      sundry/etree_collection_names.json
      build.log

Usage:
    python3 build_from_db.py
    python3 build_from_db.py --db /var/lib/navidrome/navidrome.db
    python3 build_from_db.py --only "Dead & Company"
"""

import argparse
import json
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

from config import load_config
from db import iter_library
from parser import parse_album_title
from subsonic import SubsonicClient


def log_line(log_file, msg):
    print(msg, flush=True)
    if log_file:
        log_file.write(msg + "\n")
        log_file.flush()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def tape_id_for(album_id, source_tag, used_ids):
    base = source_tag.strip() if source_tag else f"nav-{album_id[:8]}"
    if base not in used_ids:
        used_ids.add(base)
        return base
    n = 2
    while f"{base}#{n}" in used_ids:
        n += 1
    candidate = f"{base}#{n}"
    used_ids.add(candidate)
    return candidate


def group_library(db_path):
    """Walk the DB and return artists -> date -> list of (album, songs).

    Each `album` is the album-level dict; each `songs` is a list of
    media_file dicts in (disc, track, path) order.
    """
    # First, group all songs by album.
    albums = {}  # album_id -> {"artist_name": ..., "album_name": ..., "songs": [...]}
    for row in iter_library(db_path):
        aid = row["album_id"]
        if aid not in albums:
            albums[aid] = {
                "artist_id": row["artist_id"],
                "artist_name": row["artist_name"],
                "album_id": aid,
                "album_name": row["album_name"],
                "songs": [],
            }
        albums[aid]["songs"].append({
            "song_id": row["song_id"],
            "title": row["song_title"],
            "disc_number": row["disc_number"],
            "track_number": row["track_number"],
            "suffix": row["suffix"],
            "path": row["path"],
        })

    # Now bucket each album under (artist, date).
    artists = defaultdict(lambda: defaultdict(list))
    skipped_album_examples = defaultdict(list)
    for album in albums.values():
        parsed = parse_album_title(album["album_name"])
        if parsed is None:
            if len(skipped_album_examples[album["artist_name"]]) < 3:
                skipped_album_examples[album["artist_name"]].append(album["album_name"])
            continue
        date, source, venue = parsed
        artists[album["artist_name"]][date].append({
            "album_id": album["album_id"],
            "album_name": album["album_name"],
            "source": source,
            "venue": venue,
            "songs": album["songs"],
        })

    return artists, skipped_album_examples


def build_artist_tree(client, artist_name, dates, output_dir, log_file):
    """Write vcs.json, tape_ids.json, and trackdata.json files for one artist."""
    out = Path(output_dir)
    vcs_dir = out / "vcs"
    tapes_root = out / "tapes" / artist_name

    # Clean stale output for this artist first.
    vcs_file = vcs_dir / f"{artist_name}_vcs.json"
    if vcs_file.exists():
        vcs_file.unlink()
    if tapes_root.exists():
        shutil.rmtree(tapes_root)

    vcs_map = {}
    trackdata_written = 0
    multi_tape = 0

    for date in sorted(dates.keys()):
        entries = dates[date]
        # vcs map: prefer first non-empty venue
        for e in entries:
            if date not in vcs_map or (not vcs_map[date] and e["venue"]):
                vcs_map[date] = e["venue"]
        if len(entries) > 1:
            multi_tape += 1

        used_ids = set()
        tape_ids_list = []
        for entry in entries:
            tape_id = tape_id_for(entry["album_id"], entry["source"], used_ids)
            songs = entry["songs"]
            if not songs:
                continue
            tracklist = [s["title"] or _title_from_path(s["path"]) for s in songs]
            urls = [client.stream_url(s["song_id"]) for s in songs]
            trackdata = {
                "collection": artist_name,
                "tape_id": tape_id,
                "tracklist": tracklist,
                "urls": urls,
            }
            write_json(tapes_root / date / tape_id / "trackdata.json", trackdata)
            tape_ids_list.append([tape_id, len(songs)])
            trackdata_written += 1
        write_json(tapes_root / date / "tape_ids.json", tape_ids_list)

    write_json(vcs_file, dict(sorted(vcs_map.items())))
    return {
        "artist": artist_name,
        "dates": len(dates),
        "multi_tape_dates": multi_tape,
        "trackdata_written": trackdata_written,
    }


def _title_from_path(path):
    # Last-ditch fallback if title is empty in DB.
    name = Path(path).stem
    return name


def write_collection_names(output_dir, names):
    sundry = Path(output_dir) / "sundry"
    sundry.mkdir(parents=True, exist_ok=True)
    blob = {"items": sorted(names, key=str.lower)}
    (sundry / "etree_collection_names.json").write_text(
        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def copy_static_assets(output_dir):
    """Mirror indexer/static/* into output/. Includes silence audio files
    that the audio player splices between tracks/encores."""
    static_root = Path(__file__).resolve().parent / "static"
    if not static_root.exists():
        return
    for src in static_root.rglob("*"):
        if src.is_file():
            rel = src.relative_to(static_root)
            dst = Path(output_dir) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="path to navidrome.db (overrides config)")
    ap.add_argument("--only", help="build just this one artist")
    args = ap.parse_args()

    cfg = load_config()
    db_path = args.db or cfg.get("db_path")
    if not db_path:
        sys.exit("missing db_path — set it in navidrome.local.json or pass --db")
    if not Path(db_path).exists():
        sys.exit(f"DB not found: {db_path}")

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "build.log"
    log_file = log_path.open("a", encoding="utf-8")

    run_start = time.time()
    log_line(log_file, f"\n=== build_from_db start {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    log_line(log_file, f"db: {db_path}")

    client = SubsonicClient(cfg)  # used only for stream URL signing

    t0 = time.time()
    artists, skipped_examples = group_library(db_path)
    log_line(log_file,
             f"scanned DB in {time.time()-t0:.1f}s — "
             f"{len(artists)} artists with date-prefixed albums")

    if args.only:
        match = {k: v for k, v in artists.items() if k.lower() == args.only.lower()}
        if not match:
            sys.exit(f"artist not found in date-prefixed set: {args.only!r}")
        artists = match

    kept_names = []
    totals = {"dates": 0, "trackdata": 0, "multi_tape": 0}
    failures = []

    for i, (name, dates) in enumerate(sorted(artists.items(), key=lambda kv: kv[0].lower()), 1):
        t1 = time.time()
        try:
            stats = build_artist_tree(client, name, dates, output_dir, log_file)
            totals["dates"] += stats["dates"]
            totals["trackdata"] += stats["trackdata_written"]
            totals["multi_tape"] += stats["multi_tape_dates"]
            kept_names.append(name)
            log_line(log_file,
                     f"  [{i:3d}/{len(artists)}] {name}  "
                     f"dates={stats['dates']} mt={stats['multi_tape_dates']} "
                     f"trackdata={stats['trackdata_written']} ({time.time()-t1:.2f}s)")
        except Exception as e:
            failures.append((name, str(e)))
            log_line(log_file, f"  [{i:3d}/{len(artists)}] {name}  FAILED: {e}")

    if not args.only:
        write_collection_names(output_dir, kept_names)
        log_line(log_file, f"wrote sundry/etree_collection_names.json ({len(kept_names)} artists)")
        copy_static_assets(output_dir)
        log_line(log_file, "copied static assets (silence audio, etc.)")

    elapsed = time.time() - run_start
    log_line(log_file, "\nsummary:")
    log_line(log_file, f"  artists kept:        {len(kept_names)}")
    log_line(log_file, f"  artists failed:      {len(failures)}")
    log_line(log_file, f"  unique dates:        {totals['dates']}")
    log_line(log_file, f"  multi-tape dates:    {totals['multi_tape']}")
    log_line(log_file, f"  trackdata files:     {totals['trackdata']}")
    log_line(log_file, f"  elapsed:             {elapsed:.1f}s")
    if failures:
        log_line(log_file, "failures:")
        for n, msg in failures:
            log_line(log_file, f"  - {n}: {msg}")

    log_file.close()


if __name__ == "__main__":
    main()
