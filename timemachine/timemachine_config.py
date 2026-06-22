"""Configuration constants for the Navidrome fork.

This is the single source of truth for the indexer URL. Every other
module that previously hit archive.org / spertilo-data on GCS imports
from here. Change once, propagates everywhere.

No trailing slash on INDEXER_BASE_URL — callers append paths with a
leading slash via f-strings.
"""

INDEXER_BASE_URL = "http://jasonumd.synology.me:8080"
