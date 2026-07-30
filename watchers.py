#!/usr/bin/env python3
"""Extra Apple watchers: system status, Newsroom, developer news, signing status.

Runs inside GitHub Actions alongside check.py. Standard library only.
State lives in state/watchers.json. On first run each watcher seeds its
state silently (no notification flood).
"""

import json
import os
import pathlib
import re
import sys
import urllib.request

STATE_FILE = pathlib.Path("state/watchers.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"

UA = {"User-Agent": "apple-release-watch (github actions)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def notify(title, message, priority="default"):
    print(f"NOTIFY [{title}] {message}")
    if DRY_RUN:
        return
    if not NTFY_TOPIC:
        print("ERROR: NTFY_TOPIC secret is not set.")
        sys.exit(1)
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority, "Tags": "apple"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"ntfy responded {resp.status}")


# ---------------------------------------------------------------- watchers

def watch_system_status(state):
    """Alert when an Apple service has an ongoing outage/issue, and when it resolves."""
    data = json.loads(get("https://www.apple.com/support/systemstatus/data/system_status_en_US.js"))
    ongoing = {}  # messageId -> (statusType, [service names])
    for svc in data.get("services", []):
        for ev in svc.get("events", []):
            if ev.get("eventStatus") != "ongoing":
                continue
            if "maintenance" in (ev.get("statusType") or "").lower():
                continue
            mid = str(ev.get("messageId"))
            typ, names = ongoing.get(mid, (ev.get("statusType") or "Issue", []))
            names.append(svc["serviceName"])
            ongoing[mid] = (typ, names)

    prev = state.get("system_status")
    now_ids = sorted(ongoing.keys())
    if prev is None:
        state["system_status"] = now_ids
        print(f"system_status: seeded ({len(now_ids)} ongoing)")
        return
    prev_set = set(prev)
    for mid, (typ, names) in ongoing.items():
        if mid not in prev_set:
            notify("Apple System Status", f"{typ}: {', '.join(sorted(set(names)))}", priority="high")
    for mid in prev_set - set(now_ids):
        notify("Apple System Status", "An earlier service issue is resolved.")
    state["system_status"] = now_ids


def watch_newsroom(state):
    """Alert on new Apple Newsroom posts (Atom feed)."""
    xml = get("https://www.apple.com/newsroom/rss-feed.rss")
    entries = []
    for chunk in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        link = re.search(r'<link href="([^"]+)"', chunk)
        title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", chunk, re.S)
        if link and title:
            entries.append((link.group(1), re.sub(r"\s+", " ", title.group(1)).strip()))
    if len(entries) < 3:
        print("newsroom: feed looks broken, skipping")
        return
    prev = state.get("newsroom")
    if prev is None:
        state["newsroom"] = [l for l, _ in entries]
        print(f"newsroom: seeded ({len(entries)} entries)")
        return
    prev_set = set(prev)
    new = [(l, t) for l, t in entries if l not in prev_set]
    if new:
        notify("Apple Newsroom", "\n".join(t for _, t in new))
    cur = [l for l, _ in entries]
    state["newsroom"] = (cur + [p for p in prev if p not in set(cur)])[:200]


def watch_devnews(state):
    """Alert on new Apple Developer news articles (RSS, HTML fallback)."""
    items = []
    try:
        xml = get("https://developer.apple.com/news/rss/news.rss")
        for chunk in re.findall(r"<item>(.*?)</item>", xml, re.S):
            g = re.search(r"<guid[^>]*>(.*?)</guid>", chunk, re.S)
            t = re.search(r"<title>(.*?)</title>", chunk, re.S)
            if g and t:
                gid = g.group(1).strip().split("id=")[-1]
                items.append((gid, re.sub(r"\s+", " ", t.group(1)).strip()))
    except Exception as e:
        print(f"devnews rss failed ({e}), trying HTML")
    if len(items) < 3:
        html = get("https://developer.apple.com/news/")
        for aid, body in re.findall(r'<article id="article-([a-z0-9]+)"(.*?)</article>', html, re.S):
            m = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                items.append((aid, title))
    if len(items) < 3:
        print("devnews: no usable source, skipping")
        return
    prev = state.get("devnews")
    if prev is None:
        state["devnews"] = [i for i, _ in items]
        print(f"devnews: seeded ({len(items)} items)")
        return
    prev_set = set(prev)
    new = [(i, t) for i, t in items if i not in prev_set]
    if new:
        notify("Apple Developer News", "\n".join(t for _, t in new))
    cur = [i for i, _ in items]
    state["devnews"] = (cur + [p for p in prev if p not in set(cur)])[:300]


def watch_signing(state):
    """Alert when Apple stops signing an iOS version (downgrade window closes)."""
    device = None
    firmwares = None
    for candidate in ("iPhone17,1", "iPhone16,2", "iPhone15,2"):
        try:
            d = json.loads(get(f"https://api.ipsw.me/v4/device/{candidate}?type=ipsw"))
            if d.get("firmwares"):
                device, firmwares = candidate, d["firmwares"]
                break
        except Exception as e:
            print(f"signing: {candidate} failed ({e})")
    if not firmwares:
        print("signing: no data, skipping")
        return
    signed_now = {f["buildid"]: f["version"] for f in firmwares if f.get("signed")}
    prev = state.get("signing")
    if prev is None or prev.get("device") != device:
        state["signing"] = {"device": device, "signed": signed_now}
        print(f"signing: seeded for {device} ({len(signed_now)} signed)")
        return
    stopped = {b: v for b, v in prev["signed"].items() if b not in signed_now}
    if stopped:
        lines = [f"Apple stopped signing iOS {v} ({b})" for b, v in sorted(stopped.items(), key=lambda x: x[1])]
        notify("Signing window closed", "\n".join(lines) + "\nDowngrading to these versions is no longer possible.")
    state["signing"] = {"device": device, "signed": signed_now}


def main():
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())

    failures = 0
    for watcher in (watch_system_status, watch_newsroom, watch_devnews, watch_signing):
        try:
            watcher(state)
        except Exception as e:
            failures += 1
            print(f"{watcher.__name__} failed: {e}")

    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    if failures == 4:
        sys.exit(1)


if __name__ == "__main__":
    main()
