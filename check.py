#!/usr/bin/env python3
"""Check Apple's developer releases feed and push new releases to ntfy.

Runs inside GitHub Actions. No dependencies beyond the standard library.
State lives in seen.txt (one "id | title" line per already-seen release).
"""

import os
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone

FEED_URL = "https://developer.apple.com/news/releases/rss/releases.rss"
STATE_FILE = pathlib.Path("seen.txt")
HEARTBEAT_FILE = pathlib.Path(".heartbeat")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")


def notify(title: str, message: str, priority: str = "high") -> None:
    if not NTFY_TOPIC:
        print("ERROR: NTFY_TOPIC secret is not set - cannot send notification.")
        sys.exit(1)
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": "apple",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"ntfy responded {resp.status}")


def fetch_feed() -> str:
    req = urllib.request.Request(
        FEED_URL, headers={"User-Agent": "apple-release-watch (github actions)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_items(xml: str):
    """Return list of (id, title) in feed order (newest first)."""
    items = []
    for chunk in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title_m = re.search(r"<title>(.*?)</title>", chunk, re.S)
        guid_m = re.search(r"<guid>(.*?)</guid>", chunk, re.S)
        if not title_m or not guid_m:
            continue
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()
        guid = guid_m.group(1).strip()
        item_id = guid.split("id=")[-1] if "id=" in guid else guid
        items.append((item_id, title))
    return items


def main() -> None:
    # Manual test mode: send a test push and exit without touching state.
    if os.environ.get("TEST_NOTIFY", "").lower() == "true":
        notify("Test - Apple release watch", "Setup works. You will be notified here when Apple ships something new.", priority="default")
        return

    xml = fetch_feed()
    items = parse_items(xml)
    if len(items) < 5:
        # Feed looks broken/empty - do not wipe state or notify.
        print(f"Feed returned only {len(items)} items; skipping this run.")
        return

    seen_ids = set()
    if STATE_FILE.exists():
        for line in STATE_FILE.read_text().splitlines():
            if "|" in line:
                seen_ids.add(line.split("|", 1)[0].strip())

    new_items = [(i, t) for i, t in items if i not in seen_ids]

    if new_items:
        titles = [t for _, t in new_items]
        print(f"NEW: {titles}")
        notify(
            title="New from Apple",
            message="\n".join(titles),
            priority="high",
        )
        # Rewrite state with the current feed contents (bounded size).
        STATE_FILE.write_text("\n".join(f"{i} | {t}" for i, t in items) + "\n")
    else:
        print("No new releases.")

    # Monthly heartbeat commit keeps GitHub from disabling the schedule
    # after 60 days of repo inactivity.
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if not HEARTBEAT_FILE.exists() or HEARTBEAT_FILE.read_text().strip() != month:
        HEARTBEAT_FILE.write_text(month + "\n")


if __name__ == "__main__":
    main()

