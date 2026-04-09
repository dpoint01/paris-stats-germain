#!/usr/bin/env python3
"""
Paris Stats-Germain - Data Fetcher

Fetches PSG match data and player stats from Sofascore.

Usage:
    pip install curl_cffi

    # First time: full historical load (~10-15 min)
    python fetch.py --init

    # After match days: only fetch new matches (~30 sec)
    python fetch.py --update

    # Then deploy
    vercel --prod
"""

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests
except ImportError:
    print("Missing dependency. Install with: pip install curl_cffi")
    sys.exit(1)

PSG_ID = 1644
BASE_URL = "https://api.sofascore.com/api/v1"
OUTPUT_FILE = Path(__file__).parent / "data.json"
DELAY = 0.8


def sofa_get(endpoint):
    """Fetch a Sofascore API endpoint with browser TLS impersonation."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, impersonate="chrome", timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_events(max_pages):
    """Fetch PSG match results, paginated."""
    all_events = []
    for page in range(max_pages):
        print(f"  Page {page}...", end=" ", flush=True)
        data = sofa_get(f"/team/{PSG_ID}/events/last/{page}")
        events = data.get("events", [])
        finished = [e for e in events if e.get("status", {}).get("type") == "finished"]
        all_events.extend(finished)
        print(f"{len(finished)} matches")
        if not data.get("hasNextPage"):
            break
        time.sleep(DELAY)
    return all_events


def fetch_lineups(events, existing_lineups=None):
    """Fetch player stats for each match. Skips already-fetched ones."""
    existing = existing_lineups or {}
    lineups = dict(existing)
    to_fetch = [e for e in events if str(e["id"]) not in existing]
    total = len(to_fetch)

    if not total:
        print("  All lineups already cached.")
        return lineups

    print(f"  Fetching {total} new lineups ({len(existing)} already cached)...")
    for i, event in enumerate(to_fetch):
        eid = event["id"]
        try:
            if (i + 1) % 10 == 0 or i == 0:
                print(f"    {i + 1}/{total}...")
            lineups[str(eid)] = sofa_get(f"/event/{eid}/lineups")
            time.sleep(DELAY)
        except Exception as e:
            print(f"    Warning: event {eid} failed: {e}")
    return lineups


def fetch_squad():
    """Fetch current PSG squad."""
    print("  Fetching squad...")
    try:
        return sofa_get(f"/team/{PSG_ID}/players")
    except Exception as e:
        print(f"  Warning: {e}")
        return {"players": []}


def fetch_image(url):
    """Download image as base64 data URI."""
    try:
        resp = requests.get(url, impersonate="chrome", timeout=10)
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "image/png")
            b64 = base64.b64encode(resp.content).decode()
            return f"data:{ct};base64,{b64}"
    except Exception:
        pass
    return None


def fetch_images(events, squad_data, existing_images=None):
    """Download team logos and PSG player photos. Skips existing ones."""
    existing = existing_images or {"teams": {}, "players": {}}
    team_images = dict(existing.get("teams", {}))
    player_images = dict(existing.get("players", {}))

    # Collect all team IDs
    team_ids = set()
    for ev in events:
        team_ids.add(str(ev["homeTeam"]["id"]))
        team_ids.add(str(ev["awayTeam"]["id"]))

    # Only PSG player photos
    player_ids = set()
    for entry in squad_data.get("players", []):
        pid = entry.get("player", {}).get("id")
        if pid:
            player_ids.add(str(pid))

    # Fetch missing team logos
    new_teams = team_ids - set(team_images.keys())
    if new_teams:
        print(f"  Fetching {len(new_teams)} new team logos ({len(team_images)} cached)...")
        for tid in new_teams:
            img = fetch_image(f"{BASE_URL}/team/{tid}/image")
            if img:
                team_images[tid] = img
            time.sleep(0.15)
    else:
        print(f"  All {len(team_images)} team logos cached.")

    # Fetch missing player photos
    new_players = player_ids - set(player_images.keys())
    if new_players:
        print(f"  Fetching {len(new_players)} new player photos ({len(player_images)} cached)...")
        for pid in new_players:
            img = fetch_image(f"{BASE_URL}/player/{pid}/image")
            if img:
                player_images[pid] = img
            time.sleep(0.15)
    else:
        print(f"  All {len(player_images)} player photos cached.")

    return {"teams": team_images, "players": player_images}


def load_existing():
    """Load existing data.json if present."""
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def save_data(data):
    """Save data.json."""
    OUTPUT_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    return size_mb


def run_init():
    """Full historical load: ~10 years of PSG data."""
    # 10 seasons x ~55 games = ~550 matches. ~18 pages of 30.
    MAX_PAGES = 20

    print("INIT MODE: Full historical load")
    print("=" * 40)

    print(f"\n1. Fetching all PSG matches (up to {MAX_PAGES} pages)...")
    events = fetch_events(MAX_PAGES)
    print(f"   Total: {len(events)} matches")

    if events:
        oldest = datetime.fromtimestamp(events[-1]["startTimestamp"])
        newest = datetime.fromtimestamp(events[0]["startTimestamp"])
        print(f"   Range: {oldest.strftime('%b %Y')} to {newest.strftime('%b %Y')}")

    print("\n2. Fetching player stats per match...")
    lineups = fetch_lineups(events)
    print(f"   Got lineups for {len(lineups)} matches")

    print("\n3. Fetching squad info...")
    squad = fetch_squad()
    print(f"   Got {len(squad.get('players', []))} squad members")

    print("\n4. Fetching images...")
    images = fetch_images(events, squad)
    print(f"   {len(images['teams'])} team logos, {len(images['players'])} player photos")

    data = {
        "events": events,
        "lineups": lineups,
        "squad": squad,
        "images": images,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "psg_id": PSG_ID,
    }

    size_mb = save_data(data)
    print(f"\n5. Saved to {OUTPUT_FILE.name} ({size_mb:.1f} MB)")
    print(f"   {len(events)} matches, {len(lineups)} with player stats")
    print(f"\nNext: vercel --prod")


def run_update():
    """Delta update: only fetch matches newer than the latest in data.json."""
    print("UPDATE MODE: Fetching new matches only")
    print("=" * 40)

    existing = load_existing()
    if not existing:
        print("No existing data.json found. Run with --init first.")
        sys.exit(1)

    existing_event_ids = {e["id"] for e in existing.get("events", [])}
    latest_ts = max(e["startTimestamp"] for e in existing["events"]) if existing["events"] else 0
    latest_date = datetime.fromtimestamp(latest_ts)
    print(f"Last match in data: {latest_date.strftime('%Y-%m-%d')}")

    print("\n1. Checking for new matches...")
    # Fetch page 0 (most recent 30 events)
    new_events = []
    data = sofa_get(f"/team/{PSG_ID}/events/last/0")
    for ev in data.get("events", []):
        if ev.get("status", {}).get("type") == "finished" and ev["id"] not in existing_event_ids:
            new_events.append(ev)

    if not new_events:
        print("   No new matches found. Data is up to date.")
        return

    print(f"   Found {len(new_events)} new match(es)")
    for ev in new_events:
        d = datetime.fromtimestamp(ev["startTimestamp"]).strftime("%Y-%m-%d")
        home = ev["homeTeam"]["shortName"]
        away = ev["awayTeam"]["shortName"]
        hs = ev.get("homeScore", {}).get("current", "?")
        aws = ev.get("awayScore", {}).get("current", "?")
        print(f"     {d}: {home} {hs}-{aws} {away}")

    print("\n2. Fetching player stats for new matches...")
    new_lineups = fetch_lineups(new_events)

    print("\n3. Updating squad info...")
    squad = fetch_squad()

    print("\n4. Fetching any new images...")
    all_events = existing["events"] + new_events
    images = fetch_images(all_events, squad, existing.get("images"))

    # Merge
    merged_lineups = dict(existing.get("lineups", {}))
    merged_lineups.update(new_lineups)

    data = {
        "events": all_events,
        "lineups": merged_lineups,
        "squad": squad,
        "images": images,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "psg_id": PSG_ID,
    }

    # Sort events by timestamp descending
    data["events"].sort(key=lambda e: e["startTimestamp"], reverse=True)

    size_mb = save_data(data)
    print(f"\n5. Saved to {OUTPUT_FILE.name} ({size_mb:.1f} MB)")
    print(f"   Total: {len(data['events'])} matches, {len(merged_lineups)} with player stats")
    print(f"   Added: {len(new_events)} new match(es)")
    print(f"\nNext: vercel --prod")


def main():
    parser = argparse.ArgumentParser(description="Paris Stats-Germain Data Fetcher")
    parser.add_argument("--init", action="store_true", help="Full historical load (~10 years)")
    parser.add_argument("--update", action="store_true", help="Delta update (new matches only)")
    args = parser.parse_args()

    if not args.init and not args.update:
        # Default: update if data exists, init if not
        if OUTPUT_FILE.exists():
            run_update()
        else:
            run_init()
    elif args.init:
        run_init()
    elif args.update:
        run_update()


if __name__ == "__main__":
    main()
