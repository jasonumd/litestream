# Indexer JSON Schema

The TimeMachine device consumes pre-built JSON files at boot. The indexer writes these files into a directory served by an HTTP server in the same LXC as Navidrome. Every URL path matches the upstream eichblatt GCS layout so the device-side patches stay minimal.

Base URL is whatever the LXC serves at — referred to here as `${BASE}`. The device's `CLOUD_PATH` constant is set to this value.

## Files

### `${BASE}/vcs/{Artist}_vcs.json`

Per-artist `{date: venue}` map. One entry per (artist, date) pair, regardless of how many tape variants exist on that date. Loaded by the device once per artist on boot and held in `coll_dict[artist]`.

```json
{
  "1985-06-22": "Uptown Lounge, Athens, GA",
  "1986-02-13": "Uptown Lounge, Athens, GA",
  "2011-01-04": "Zebra Bar, Jam Cruise, US"
}
```

- Keys: `YYYY-MM-DD` strings, sorted lexically (sort isn't strictly required by the device but helps diff/debug).
- Values: human-readable venue string. The indexer derives this by stripping the leading date and any `(source-quality)` parens from the Navidrome album title, then trimming whitespace and leading punctuation.
- Albums whose titles don't start with a full YYYY-MM-DD are skipped entirely (they will not appear here or anywhere else).

### `${BASE}/sundry/etree_collection_names.json`

Flat list of artist names that have at least one parseable show. Used by the device's "Add Artist" UI.

```json
{
  "items": ["Billy Strings", "Dead & Company", "Grateful Dead", "Greensky Bluegrass", "..."]
}
```

- Single key `items` — required by `archive_utils.collection_names()` line 264.
- Sorted alphabetically. Devices show this list verbatim in the picker.

### `${BASE}/tapes/{Artist}/{date}/tape_ids.json`

List of tape variants available for one (artist, date). Multiple entries when the same show has multiple source recordings.

```json
[
  ["sbd 79356", 18],
  ["sbd 99725", 18]
]
```

- Top-level is a JSON array.
- Each entry is `[tape_id, track_count]` — the device only uses `entry[0]` (the tape ID) in `livemusic.py` line 240. Track count is informational.
- Tape ID rules:
  - If the album title has `(source-quality)` parens — e.g. `(sbd 79356)` — the tape ID is the contents of the parens.
  - If the album has no parens (e.g. `2011-01-04 Zebra Bar, Jam Cruise, US`), the tape ID is `nav-{first8charsOfNavidromeAlbumId}` so it stays stable across rebuilds.
  - When multiple albums would collide on the same tape ID (rare but possible), the indexer disambiguates by appending `#2`, `#3`, etc.

### `${BASE}/tapes/{Artist}/{date}/{tape_id}/trackdata.json`

Track names plus pre-signed Navidrome stream URLs for one tape. This is what the audio player consumes directly.

```json
{
  "collection": "Widespread Panic",
  "tape_id": "sbd 79356",
  "tracklist": ["Driving Song", "Travelin' Light", "..."],
  "urls": [
    "http://navidrome.local:4533/rest/stream.view?id=abc&u=...&t=...&s=...&v=1.16.1&c=Time-Machine&f=mp3",
    "http://navidrome.local:4533/rest/stream.view?id=def&u=...&t=...&s=...&v=1.16.1&c=Time-Machine&f=mp3"
  ]
}
```

- `collection` — must equal the artist name used in vcs filenames. Echoed back to the device at line 191 of livemusic.py.
- `tape_id` — optional but recommended; device line 218 falls back to `"unknown"` if missing.
- `tracklist[i]` and `urls[i]` are positional — same length, same index = same track.
- Track order matches Navidrome's `getAlbum` response track order (which respects ID3 track numbers).
- URLs are fully signed at indexer-build time using Subsonic token auth: `t = md5(password + salt)`, fresh `salt` per URL. Navidrome accepts these tokens indefinitely so the nightly rebuild is the only refresh needed.

## What the indexer never writes

- Anything under `tapes/{Artist}/{date}/` for dates that have zero tape variants (filtered upstream by the `YYYY-MM-DD` parse).
- `trackdata.json` for albums that return zero playable tracks from `getAlbum.view` (logged + skipped).
- Empty `vcs.json` files. If an artist has zero parseable albums, they are excluded from `etree_collection_names.json` too.

## File-naming notes

- `{Artist}` in paths is the **raw artist name as Navidrome reports it**, URL-encoded by the HTTP server (or pre-encoded by the indexer when writing to disk on case-sensitive filesystems). E.g. `Dead & Company` → `Dead%20%26%20Company` in URLs, but the file on disk is literally `Dead & Company_vcs.json`. The device's existing code passes artist names through f-strings into URLs unchanged, so the HTTP server must serve both encoded and unencoded forms — easiest is to let nginx/python-http-server handle URL decoding.
- `{tape_id}` may contain spaces (`sbd 79356`). Same encoding rule applies.

## Refresh cadence

The device fetches `vcs.json` on every boot and caches collection metadata for 24h (see `refresh_meta_needed()` in livemusic.py). The indexer nightly rebuild is more than fast enough to stay ahead of that cadence.
