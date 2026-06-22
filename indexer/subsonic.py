"""Minimal Subsonic API client for Navidrome — stdlib only."""

import hashlib
import json
import secrets
import urllib.parse
import urllib.request

SUBSONIC_API_VERSION = "1.16.1"


class SubsonicError(RuntimeError):
    pass


class SubsonicClient:
    def __init__(self, cfg, timeout=20):
        self.url = cfg["url"].rstrip("/")
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.client_name = cfg["client_name"]
        self.timeout = timeout

    def _auth_params(self):
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode("utf-8")).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": SUBSONIC_API_VERSION,
            "c": self.client_name,
            "f": "json",
        }

    def call(self, endpoint, params=None):
        merged = self._auth_params()
        if params:
            merged.update(params)
        qs = urllib.parse.urlencode(merged)
        url = f"{self.url}/rest/{endpoint}?{qs}"
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:
            body = resp.read()
        data = json.loads(body)
        sub = data.get("subsonic-response", {})
        if sub.get("status") != "ok":
            err = sub.get("error", {})
            raise SubsonicError(f"{endpoint} failed: code={err.get('code')} {err.get('message')}")
        return sub

    def ping(self):
        return self.call("ping.view")

    def get_artists(self):
        resp = self.call("getArtists.view")
        artists = []
        for idx in resp.get("artists", {}).get("index", []):
            for a in idx.get("artist", []):
                artists.append(a)
        return artists

    def get_artist(self, artist_id):
        resp = self.call("getArtist.view", {"id": artist_id})
        return resp.get("artist", {})

    def get_album(self, album_id):
        resp = self.call("getAlbum.view", {"id": album_id})
        return resp.get("album", {})

    def stream_url(self, song_id, audio_format="mp3", max_bitrate=None):
        """Return a fully-signed Navidrome stream URL.

        audio_format passed to Subsonic's ?format= param to force server-side
        transcoding. Device C decoders cover ogg/mp3/aac — defaulting to mp3
        because the upstream archive.org tapes were typically mp3/ogg and the
        decoder paths are best-exercised there.

        Each call uses a fresh salt — Navidrome accepts these tokens
        indefinitely, so URLs baked into JSON stay valid until the next
        indexer rebuild rotates them.
        """
        params = self._auth_params()
        params["id"] = song_id
        if audio_format:
            params["format"] = audio_format
        if max_bitrate is not None:
            params["maxBitRate"] = str(max_bitrate)
        qs = urllib.parse.urlencode(params)
        return f"{self.url}/rest/stream.view?{qs}"
