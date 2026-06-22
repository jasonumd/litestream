"""Walk all Navidrome artists and produce the full JSON tree.

Output structure (matches indexer/SCHEMA.md):
    output/
      vcs/{Artist}_vcs.json
      tapes/{Artist}/{date}/tape_ids.json
      tapes/{Artist}/{date}/{tape_id}/trackdata.json
      sundry/etree_collection_names.json

Run nightly via cron. Logs go to indexer/output/build.log.

Usage:
    python indexer/build_library.py
    python indexer/build_library.py --start-from "Phish"     # resume
    python indexer/build_library.py --only "Dead & Company"  # one artist
    python indexer/build_library.py --rate-limit-ms 50       # be gentle
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from build_artist import build_artist as build_artist_tree
from config import load_config
from subsonic import SubsonicClient


def log_line(log_file, msg):
    print(msg, flush=True)
    if log_file:
        log_file.write(msg + "\n")
        log_file.flush()


def clean_artist_dir(output_dir, artist_name):
    """Remove stale per-artist output so deleted albums don't leave dangling JSON."""
    out = Path(output_dir)
    vcs_file = out / "vcs" / f"{artist_name}_vcs.json"
    tapes_dir = out / "tapes" / artist_name
    if vcs_file.exists():
        vcs_file.unlink()
    if tapes_dir.exists():
        shutil.rmtree(tapes_dir)


def write_collection_names(output_dir, names):
    sundry = Path(output_dir) / "sundry"
    sundry.mkdir(parents=True, exist_ok=True)
    blob = {"items": sorted(names, key=str.lower)}
    (sundry / "etree_collection_names.json").write_text(
        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-from", help="skip artists alphabetically before this one")
    ap.add_argument("--only", help="build just this one artist")
    ap.add_argument("--rate-limit-ms", type=int, default=0,
                    help="sleep N ms between getAlbum calls (default 0)")
    ap.add_argument("--skip-trackdata", action="store_true",
                    help="emit vcs + tape_ids but skip per-album track fetches")
    args = ap.parse_args()

    cfg = load_config()
    client = SubsonicClient(cfg)

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "build.log"
    log_file = log_path.open("a", encoding="utf-8")

    run_start = time.time()
    log_line(log_file, f"\n=== build_library start {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    artists = client.get_artists()
    artists.sort(key=lambda a: a["name"].lower())

    if args.only:
        artists = [a for a in artists if a["name"].lower() == args.only.lower()]
        if not artists:
            sys.exit(f"artist not found: {args.only!r}")
    elif args.start_from:
        cutoff = args.start_from.lower()
        artists = [a for a in artists if a["name"].lower() >= cutoff]

    log_line(log_file, f"processing {len(artists)} artist(s)")

    rate_s = args.rate_limit_ms / 1000.0
    kept_names = []
    failed = []
    totals = {"albums": 0, "parsed": 0, "skipped": 0, "dates": 0, "trackdata": 0}

    for i, artist in enumerate(artists, 1):
        name = artist["name"]
        t0 = time.time()
        try:
            clean_artist_dir(output_dir, name)
            stats = build_artist_tree(
                client, artist, output_dir,
                skip_trackdata=args.skip_trackdata,
                rate_limit_s=rate_s,
            )
            elapsed = time.time() - t0
            if stats["parsed"] > 0:
                kept_names.append(name)
                totals["albums"] += stats["albums_total"]
                totals["parsed"] += stats["parsed"]
                totals["skipped"] += stats["skipped"]
                totals["dates"] += stats["unique_dates"]
                totals["trackdata"] += stats["trackdata_written"]
                log_line(log_file,
                         f"  [{i:3d}/{len(artists)}] {name}  "
                         f"albums={stats['albums_total']} kept={stats['parsed']} "
                         f"dates={stats['unique_dates']} mt={stats['multi_tape_dates']} "
                         f"trackdata={stats['trackdata_written']} ({elapsed:.1f}s)")
            else:
                log_line(log_file,
                         f"  [{i:3d}/{len(artists)}] {name}  "
                         f"albums={stats['albums_total']} kept=0 (no parseable shows, excluded)")
        except Exception as e:
            failed.append((name, str(e)))
            log_line(log_file, f"  [{i:3d}/{len(artists)}] {name}  FAILED: {e}")

    if not args.only:
        write_collection_names(output_dir, kept_names)
        log_line(log_file, f"wrote sundry/etree_collection_names.json ({len(kept_names)} artists)")

    elapsed_total = time.time() - run_start
    log_line(log_file, f"\nsummary:")
    log_line(log_file, f"  artists kept:     {len(kept_names)}")
    log_line(log_file, f"  artists failed:   {len(failed)}")
    log_line(log_file, f"  albums total:     {totals['albums']}")
    log_line(log_file, f"  albums parsed:    {totals['parsed']}")
    log_line(log_file, f"  albums skipped:   {totals['skipped']}")
    log_line(log_file, f"  unique dates:     {totals['dates']}")
    log_line(log_file, f"  trackdata files:  {totals['trackdata']}")
    log_line(log_file, f"  elapsed:          {elapsed_total:.1f}s")
    if failed:
        log_line(log_file, "failures:")
        for n, msg in failed:
            log_line(log_file, f"  - {n}: {msg}")

    log_file.close()


if __name__ == "__main__":
    main()
