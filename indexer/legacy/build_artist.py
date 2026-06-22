"""Build the full per-artist JSON tree:

    output/
      vcs/{Artist}_vcs.json
      tapes/{Artist}/{date}/tape_ids.json
      tapes/{Artist}/{date}/{tape_id}/trackdata.json

One artist at a time. Tasks #2 (vcs), #3 (tape_ids), #4 (trackdata) all
share the same Subsonic calls, so they run together in one pass.

Usage:
    python indexer/build_artist.py "Dead & Company"
    python indexer/build_artist.py "Dead & Company" --skip-trackdata
"""

import argparse
import json
import sys
import time
from pathlib import Path

from config import load_config
from parser import parse_album_title
from subsonic import SubsonicClient


def find_artist(client, name):
    artists = client.get_artists()
    for a in artists:
        if a["name"] == name:
            return a
    lower = name.lower()
    for a in artists:
        if a["name"].lower() == lower:
            return a
    return None


def tape_id_for(album, source_tag, used_ids):
    """Derive a stable tape ID. Rules per SCHEMA.md."""
    base = source_tag.strip() if source_tag else f"nav-{album['id'][:8]}"
    if base not in used_ids:
        used_ids.add(base)
        return base
    n = 2
    while f"{base}#{n}" in used_ids:
        n += 1
    candidate = f"{base}#{n}"
    used_ids.add(candidate)
    return candidate


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def build_artist(client, artist, output_dir, skip_trackdata=False, rate_limit_s=0.0):
    name = artist["name"]
    artist_data = client.get_artist(artist["id"])
    albums = artist_data.get("album", [])

    out = Path(output_dir)
    vcs_dir = out / "vcs"
    tapes_root = out / "tapes" / name

    vcs_map = {}                 # date -> venue
    per_date = {}                # date -> list of (album, source_tag, venue)
    skipped = []                 # titles we couldn't parse

    for album in albums:
        title = album.get("name", "")
        parsed = parse_album_title(title)
        if parsed is None:
            skipped.append(title)
            continue
        date, source, venue = parsed
        per_date.setdefault(date, []).append((album, source, venue))
        # vcs.json wants one venue per date; prefer non-empty, else first.
        if date not in vcs_map or (not vcs_map[date] and venue):
            vcs_map[date] = venue

    # vcs.json
    write_json(vcs_dir / f"{name}_vcs.json", dict(sorted(vcs_map.items())))

    # tape_ids.json + trackdata.json per date
    trackdata_written = 0
    trackdata_skipped_empty = 0
    for date, entries in per_date.items():
        date_dir = tapes_root / date
        used_ids = set()
        tape_ids_list = []          # [[tape_id, track_count], ...]
        for album, source, _venue in entries:
            tape_id = tape_id_for(album, source, used_ids)
            songs = []
            if not skip_trackdata:
                album_full = client.get_album(album["id"])
                songs = album_full.get("song", [])
                if rate_limit_s:
                    time.sleep(rate_limit_s)
                if not songs:
                    trackdata_skipped_empty += 1
                else:
                    tracklist = [s.get("title", "") for s in songs]
                    urls = [client.stream_url(s["id"]) for s in songs]
                    trackdata = {
                        "collection": name,
                        "tape_id": tape_id,
                        "tracklist": tracklist,
                        "urls": urls,
                    }
                    write_json(date_dir / tape_id / "trackdata.json", trackdata)
                    trackdata_written += 1
            tape_ids_list.append([tape_id, len(songs)])
        write_json(date_dir / "tape_ids.json", tape_ids_list)

    return {
        "name": name,
        "albums_total": len(albums),
        "parsed": sum(len(v) for v in per_date.values()),
        "skipped": len(skipped),
        "unique_dates": len(per_date),
        "multi_tape_dates": sum(1 for v in per_date.values() if len(v) > 1),
        "trackdata_written": trackdata_written,
        "trackdata_skipped_empty": trackdata_skipped_empty,
        "skipped_examples": skipped[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("artist", help="artist name")
    ap.add_argument("--skip-trackdata", action="store_true",
                    help="only emit vcs.json + tape_ids.json (no per-tape getAlbum calls)")
    ap.add_argument("--rate-limit-ms", type=int, default=0,
                    help="sleep N ms between getAlbum calls (default 0)")
    args = ap.parse_args()

    cfg = load_config()
    client = SubsonicClient(cfg)
    artist = find_artist(client, args.artist)
    if artist is None:
        sys.exit(f"artist not found: {args.artist!r}")

    t0 = time.time()
    stats = build_artist(
        client, artist, cfg["output_dir"],
        skip_trackdata=args.skip_trackdata,
        rate_limit_s=args.rate_limit_ms / 1000.0,
    )
    elapsed = time.time() - t0

    print(f"  artist:              {stats['name']}")
    print(f"  albums total:        {stats['albums_total']}")
    print(f"  parsed (kept):       {stats['parsed']}")
    print(f"  skipped:             {stats['skipped']}")
    print(f"  unique dates:        {stats['unique_dates']}")
    print(f"  multi-tape dates:    {stats['multi_tape_dates']}")
    print(f"  trackdata written:   {stats['trackdata_written']}")
    print(f"  trackdata empty:     {stats['trackdata_skipped_empty']}")
    print(f"  elapsed:             {elapsed:.1f}s")
    if stats["skipped_examples"]:
        print(f"  first skipped titles:")
        for t in stats["skipped_examples"]:
            print(f"    - {t!r}")


if __name__ == "__main__":
    main()
