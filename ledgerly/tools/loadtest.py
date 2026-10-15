"""Replay the public load profile against the running stack.

    make loadtest              # profiles/public.json, keys lt-<timestamp>-*
    python tools/loadtest.py --profile profiles/public.json --drain 30

Prints a line per second while traffic runs, then a JSON summary measured from
the database: error_rate, non_terminal, dup_keys/dup_rows, latency.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replaylib import main as replay_main  # noqa: E402

from ledgerly.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    args = sys.argv[1:]
    if "--profile" not in args:
        args += ["--profile", "profiles/public.json"]
    if "--base-url" not in args:
        args += ["--base-url", settings.public_url]
    if "--dsn" not in args:
        args += ["--dsn", settings.app_dsn]
    return replay_main(args)


if __name__ == "__main__":
    sys.exit(main())
