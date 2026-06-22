# Indexer deployment — Proxmox LXC

The indexer runs in the **same Proxmox LXC as Navidrome**. It reads Navidrome's SQLite database directly (read-only), writes JSON to a local directory, and a small HTTP server exposes those JSON files on the LAN for the TimeMachine device.

## Why direct DB reads, not the Subsonic API?

Reading the SQLite DB takes seconds; pulling the same data via the Subsonic API takes 5–17 minutes (one `getAlbum` round trip per album, ~13k albums). Navidrome has already walked the NFS share, parsed every ID3 tag, and assigned song IDs — the indexer just reads its work. Streaming still goes through Navidrome's `/rest/stream.view` endpoint (so the transcoder handles FLAC→MP3); only metadata bypasses the API.

## Requirements

- Python **3.9+** (stdlib only — no `pip install` needed)
- Read access to Navidrome's SQLite database file (default `/var/lib/navidrome/navidrome.db`)
- Navidrome reachable on `127.0.0.1:4533` (used only to sign stream URLs)
- `ffmpeg` installed (Navidrome uses it for transcoding) — `apt install ffmpeg`
- ~30 MB free disk for the generated JSON
- Open inbound TCP port on the LAN for the static file server (default: 8080)

## One-time install

```bash
# As the same user that runs Navidrome (or any user with read access to the DB):
mkdir -p ~/timemachine-indexer
cd ~/timemachine-indexer

# Copy these files from your dev machine:
scp J:/Projects/Music/TimeMachine/indexer/{config,subsonic,parser,db,build_from_db,probe_db}.py LXC:~/timemachine-indexer/
scp J:/Projects/Music/TimeMachine/indexer/{SCHEMA,DEPLOY}.md LXC:~/timemachine-indexer/

# Static assets (silence audio used between tracks/encores). The indexer
# copies these into output/sundry/ on every build.
scp -r J:/Projects/Music/TimeMachine/indexer/static LXC:~/timemachine-indexer/

# Create the credentials file alongside the scripts (do NOT commit anywhere):
cat > navidrome.local.json <<'EOF'
{
  "url": "http://127.0.0.1:4533",
  "username": "timemachinetest",
  "password": "REPLACE_ME",
  "client_name": "Time-Machine",
  "db_path": "/var/lib/navidrome/navidrome.db"
}
EOF
chmod 600 navidrome.local.json
```

`config.py` searches for `navidrome.local.json` in this order: `$TIMEMACHINE_CONFIG` (if set) → current working directory → script directory → script directory's parent. Side-by-side with the scripts (as above) is the simplest. Set `TIMEMACHINE_CONFIG=/path/to/file.json` if you need to override.

The Navidrome user only needs Subsonic-API access (no admin rights). It's used purely to derive the salted token that signs stream URLs in `trackdata.json`.

## Verify the DB is readable

Before the full run, sanity-check the schema:

```bash
python3 ~/timemachine-indexer/probe_db.py /var/lib/navidrome/navidrome.db
```

Expect to see `artist`, `album`, `media_file` all marked `[yes]`, ~13k rows in `album`, ~250k rows in `media_file`, and 100% ID3 title coverage. If Navidrome stores its DB elsewhere (custom `ND_DATAFOLDER`), pass that path explicitly.

## First run

```bash
cd ~/timemachine-indexer
python3 build_from_db.py
```

Expect roughly **30–90 seconds** end-to-end on local disk (vs. 12 minutes when the DB is on a network share). Output lands in `./output/`:

```
output/
  vcs/{Artist}_vcs.json
  tapes/{Artist}/{date}/tape_ids.json
  tapes/{Artist}/{date}/{tape_id}/trackdata.json
  sundry/etree_collection_names.json
  build.log
```

Per-artist progress is in `build.log`. Re-run any time — each artist's output is wiped and rebuilt, so deleted/renamed albums in Navidrome disappear from the index cleanly.

## Static HTTP server (systemd)

```ini
# /etc/systemd/system/timemachine-indexer.service
[Unit]
Description=TimeMachine indexer HTTP server
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/timemachine-indexer/output
ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now timemachine-indexer
```

Verify from another machine on the LAN:

```bash
curl http://LXC_IP:8080/sundry/etree_collection_names.json | head
curl 'http://LXC_IP:8080/vcs/Dead%20%26%20Company_vcs.json' | head
```

For TLS or production hardening, point caddy or nginx at `output/`. Both handle URL-encoded paths and JSON content-type correctly by default.

## Nightly cron

The build is so fast you could run it hourly without anyone noticing, but nightly is plenty:

```cron
# /etc/cron.d/timemachine-indexer
17 3 * * * YOUR_USER cd /home/YOUR_USER/timemachine-indexer && /usr/bin/python3 build_from_db.py >/dev/null 2>&1
```

The build wipes each artist's previous output before rebuilding, so deletions and renames propagate.

Rotate `build.log` if you care:

```
# /etc/logrotate.d/timemachine-indexer
/home/YOUR_USER/timemachine-indexer/output/build.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

## Pointing the device

In Phase 2 (device patches), set the device's `CLOUD_PATH` and `API` to:

```
http://LXC_IP:8080
```

The device fetches `vcs/{Artist}_vcs.json` for each configured artist at boot, then `tapes/{Artist}/{date}/...` on demand as the date wheel turns. No persistent connection — plain GETs against static JSON. Audio streams go from `trackdata.json` URLs directly to Navidrome (the device never knows the indexer's HTTP server exists at audio playback time).

## Troubleshooting

- **`unable to open database file`** — the user running the indexer can't read `navidrome.db`. Check ownership/permissions on the file and its parent directory. The `mode=ro` open does require *read* access.
- **`code=40 Wrong username or password`** in stream URLs — only matters when the device actually plays. Verify the Navidrome user/password in `navidrome.local.json` match a real Navidrome account. Special characters in passwords are fine; just don't double-escape them in the JSON.
- **Stream URL plays FLAC, device chokes** — Navidrome's transcoder fell back to passthrough. Confirm `ffmpeg` is installed and that the Navidrome user has the "Transcoding" permission. Devices decode mp3/ogg/aac only.
- **`indexer/output/tapes/{artist}` not refreshing after re-tagging in Navidrome** — Navidrome's scan must finish before the indexer sees the change. Force a scan in the Navidrome UI, then rerun `build_from_db.py`.
- **Artist with 0 albums kept** — none of their album titles start with `YYYY-MM-DD`. The build.log doesn't currently surface examples for the DB path; query manually: `sqlite3 navidrome.db "select name from album where album_artist_id=(select id from artist where name='X') limit 5"`.
- **DB locked / WAL contention** — should never happen with `mode=ro`, but if it does, copy the DB elsewhere first: `cp navidrome.db /tmp/snap.db && python3 build_from_db.py --db /tmp/snap.db`.
