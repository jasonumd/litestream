"""Config loader for the Navidrome indexer.

Looks for navidrome.local.json in this order:
  1. $TIMEMACHINE_CONFIG env var (explicit path)
  2. ./navidrome.local.json (current working directory)
  3. <script_dir>/navidrome.local.json (alongside the .py files)
  4. <script_dir>/../navidrome.local.json (one level up — repo-root layout)
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

_CONFIG_NAME = "navidrome.local.json"


def _candidate_paths():
    env = os.environ.get("TIMEMACHINE_CONFIG")
    if env:
        yield Path(env)
    yield Path.cwd() / _CONFIG_NAME
    yield SCRIPT_DIR / _CONFIG_NAME
    yield SCRIPT_DIR.parent / _CONFIG_NAME


def load_config():
    tried = []
    for path in _candidate_paths():
        tried.append(str(path))
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            for key in ("url", "username", "password", "client_name"):
                if key not in cfg or not cfg[key]:
                    sys.exit(f"config field '{key}' missing or empty in {path}")
            cfg["url"] = cfg["url"].rstrip("/")
            cfg.setdefault("output_dir", str(DEFAULT_OUTPUT_DIR))
            cfg.setdefault("db_path", "/var/lib/navidrome/navidrome.db")
            return cfg
    sys.exit(
        "no config found. Set TIMEMACHINE_CONFIG or place navidrome.local.json in one of:\n  "
        + "\n  ".join(tried)
    )
