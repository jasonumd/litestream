"""
Navidrome library probe.

Reads navidrome.local.json from the repo root, authenticates against the
Subsonic API, samples a handful of artists and albums, and reports whether
the YYYY-MM-DD date convention parses cleanly from album metadata.

This script does NOT write any index files. It is read-only against
Navidrome and prints a summary to stdout. Run before building the indexer.
"""

import hashlib
import json
import re
import secrets
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "navidrome.local.json"

SUBSONIC_API_VERSION = "1.16.1"
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SAMPLE_ARTISTS = 8
SAMPLE_ALBUMS_PER_ARTIST = 3


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(f"missing config: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("url", "username", "password", "client_name"):
        if key not in cfg or not cfg[key]:
            sys.exit(f"config field '{key}' missing or empty")
    cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def subsonic_call(cfg, endpoint, params=None):
    salt = secrets.token_hex(8)
    token = hashlib.md5((cfg["password"] + salt).encode("utf-8")).hexdigest()
    base_params = {
        "u": cfg["username"],
        "t": token,
        "s": salt,
        "v": SUBSONIC_API_VERSION,
        "c": cfg["client_name"],
        "f": "json",
    }
    if params:
        base_params.update(params)
    qs = urllib.parse.urlencode(base_params)
    url = f"{cfg['url']}/rest/{endpoint}?{qs}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        body = resp.read()
    data = json.loads(body)
    sub = data.get("subsonic-response", {})
    if sub.get("status") != "ok":
        err = sub.get("error", {})
        raise RuntimeError(f"{endpoint} failed: {err.get('code')} {err.get('message')}")
    return sub


def parse_date(text):
    if not text:
        return None
    m = DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def main():
    cfg = load_config()
    print(f"connecting to {cfg['url']} as user '{cfg['username']}'")

    ping = subsonic_call(cfg, "ping.view")
    print(f"  ping ok — server v{ping.get('version')}, type {ping.get('type', '?')}")

    artists_resp = subsonic_call(cfg, "getArtists.view")
    indexes = artists_resp.get("artists", {}).get("index", [])
    all_artists = []
    for idx in indexes:
        for a in idx.get("artist", []):
            all_artists.append(a)
    print(f"  found {len(all_artists)} artists across {len(indexes)} index buckets")

    by_album_count = sorted(all_artists, key=lambda a: a.get("albumCount", 0), reverse=True)
    sample = by_album_count[:SAMPLE_ARTISTS]

    print(f"\nsampling top {len(sample)} artists by album count:")
    total_albums = 0
    parseable = 0
    examples = []
    for artist in sample:
        aid = artist["id"]
        name = artist["name"]
        ncount = artist.get("albumCount", 0)
        print(f"\n  [{name}]  ({ncount} albums)")
        artist_resp = subsonic_call(cfg, "getArtist.view", {"id": aid})
        albums = artist_resp.get("artist", {}).get("album", [])
        for album in albums[:SAMPLE_ALBUMS_PER_ARTIST]:
            total_albums += 1
            title = album.get("name", "")
            year = album.get("year")
            path_hint = album.get("path") or ""
            date_from_title = parse_date(title)
            date_from_path = parse_date(path_hint)
            date = date_from_title or date_from_path
            mark = "OK" if date else "--"
            if date:
                parseable += 1
            print(f"     {mark}  title={title!r}  year={year}  path_hint={path_hint!r}  -> date={date}")
            if len(examples) < 3 and date:
                tracks_resp = subsonic_call(cfg, "getAlbum.view", {"id": album["id"]})
                tracks = tracks_resp.get("album", {}).get("song", [])
                examples.append({
                    "artist": name,
                    "album": title,
                    "date": date,
                    "track_count": len(tracks),
                    "first_track": tracks[0].get("title") if tracks else None,
                    "first_song_id": tracks[0].get("id") if tracks else None,
                })

    print(f"\nparse summary: {parseable}/{total_albums} sampled albums had a parseable date in title or path")
    if examples:
        print("\nsample trackdata candidates:")
        for ex in examples:
            print(f"  {ex['artist']} | {ex['date']} | {ex['track_count']} tracks | first='{ex['first_track']}' (song id={ex['first_song_id']})")
            if ex["first_song_id"]:
                stream_url = build_stream_url(cfg, ex["first_song_id"])
                print(f"    stream URL preview: {stream_url[:120]}...")


def build_stream_url(cfg, song_id):
    salt = secrets.token_hex(8)
    token = hashlib.md5((cfg["password"] + salt).encode("utf-8")).hexdigest()
    qs = urllib.parse.urlencode({
        "id": song_id,
        "u": cfg["username"],
        "t": token,
        "s": salt,
        "v": SUBSONIC_API_VERSION,
        "c": cfg["client_name"],
        "f": "json",
    })
    return f"{cfg['url']}/rest/stream.view?{qs}"


if __name__ == "__main__":
    main()
