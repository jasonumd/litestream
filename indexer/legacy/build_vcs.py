"""Build vcs.json for one artist.

Usage:
    python indexer/build_vcs.py "Dead & Company"
    python indexer/build_vcs.py --list      # show top artists by album count
"""

import argparse
import json
import sys
from pathlib import Path

from config import load_config
from parser import parse_album_title
from subsonic import SubsonicClient


def find_artist(client, name):
    artists = client.get_artists()
    for a in artists:
        if a["name"] == name:
            return a
    # case-insensitive fallback
    lower = name.lower()
    for a in artists:
        if a["name"].lower() == lower:
            return a
    return None


def build_for_artist(client, artist):
    name = artist["name"]
    artist_data = client.get_artist(artist["id"])
    albums = artist_data.get("album", [])
    vcs_map = {}
    parsed = skipped = 0
    collisions = 0
    skipped_examples = []
    for album in albums:
        title = album.get("name", "")
        result = parse_album_title(title)
        if result is None:
            skipped += 1
            if len(skipped_examples) < 5:
                skipped_examples.append(title)
            continue
        date, _source, venue = result
        parsed += 1
        if date in vcs_map:
            collisions += 1
            # Prefer non-empty venue; otherwise keep first.
            if not vcs_map[date] and venue:
                vcs_map[date] = venue
        else:
            vcs_map[date] = venue
    sorted_vcs = dict(sorted(vcs_map.items()))
    return {
        "name": name,
        "vcs": sorted_vcs,
        "stats": {
            "albums_total": len(albums),
            "parsed": parsed,
            "skipped": skipped,
            "unique_dates": len(sorted_vcs),
            "multi_tape_dates": collisions,
            "skipped_examples": skipped_examples,
        },
    }


def write_vcs_file(output_dir, artist_name, vcs_map):
    vcs_dir = Path(output_dir) / "vcs"
    vcs_dir.mkdir(parents=True, exist_ok=True)
    path = vcs_dir / f"{artist_name}_vcs.json"
    path.write_text(json.dumps(vcs_map, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")
    return path


def cmd_list(client, limit=20):
    artists = client.get_artists()
    artists.sort(key=lambda a: a.get("albumCount", 0), reverse=True)
    print(f"top {min(limit, len(artists))} artists by album count:")
    for a in artists[:limit]:
        print(f"  {a.get('albumCount', 0):5d}  {a['name']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("artist", nargs="?", help="artist name (exact match preferred, case-insensitive fallback)")
    ap.add_argument("--list", action="store_true", help="list top artists by album count and exit")
    args = ap.parse_args()

    cfg = load_config()
    client = SubsonicClient(cfg)

    if args.list:
        cmd_list(client)
        return

    if not args.artist:
        ap.error("provide an artist name or use --list")

    artist = find_artist(client, args.artist)
    if artist is None:
        sys.exit(f"artist not found: {args.artist!r}")

    result = build_for_artist(client, artist)
    path = write_vcs_file(cfg["output_dir"], result["name"], result["vcs"])

    s = result["stats"]
    print(f"wrote {path}")
    print(f"  artist:           {result['name']}")
    print(f"  albums total:     {s['albums_total']}")
    print(f"  parsed (kept):    {s['parsed']}")
    print(f"  skipped:          {s['skipped']}")
    print(f"  unique dates:     {s['unique_dates']}")
    print(f"  multi-tape dates: {s['multi_tape_dates']}")
    if s["skipped_examples"]:
        print(f"  first skipped titles:")
        for t in s["skipped_examples"]:
            print(f"    - {t!r}")


if __name__ == "__main__":
    main()
