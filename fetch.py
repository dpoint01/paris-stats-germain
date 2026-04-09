#!/usr/bin/env python3
"""
Paris Stats-Germain - Data Fetcher

Fetches PSG match data and player stats from Sofascore.
Run locally after match days, then deploy with `vercel --prod`.

Usage:
    pip install curl_cffi
    python fetch.py
    vercel --prod
"""

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
DELAY = 0.8  # seconds between requests (be nice to Sofascore)


def sofa_get(endpoint):
    """Fetch a Sofascore API endpoint with browser TLS impersonation."""
    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, impersonate="chrome", timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_events(max_pages=3):
    """Fetch recent PSG match results."""
    all_events = []
    for page in range(max_pages):
        print(f"  Fetching events page {page}...")
        data = sofa_get(f"/team/{PSG_ID}/events/last/{page}")
        events = data.get("events", [])
        finished = [e for e in events if e.get("status", {}).get("type") == "finished"]
        all_events.extend(finished)
        if not data.get("hasNextPage"):
            break
        time.sleep(DELAY)
    return all_events


def fetch_lineups(events):
    """Fetch player stats (lineups) for each match."""
    lineups = {}
    total = len(events)
    for i, event in enumerate(events):
        eid = event["id"]
        try:
            print(f"  Fetching lineups {i + 1}/{total} (event {eid})...")
            lineups[str(eid)] = sofa_get(f"/event/{eid}/lineups")
            time.sleep(DELAY)
        except Exception as e:
            print(f"  Warning: failed for event {eid}: {e}")
    return lineups


def fetch_squad():
    """Fetch current PSG squad info (total appearances, etc.)."""
    print("  Fetching squad info...")
    try:
        return sofa_get(f"/team/{PSG_ID}/players")
    except Exception as e:
        print(f"  Warning: squad fetch failed: {e}")
        return {"players": []}


def fetch_image(url):
    """Download an image and return as base64 data URI."""
    try:
        resp = requests.get(url, impersonate="chrome", timeout=10)
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "image/png")
            b64 = base64.b64encode(resp.content).decode()
            return f"data:{ct};base64,{b64}"
    except Exception:
        pass
    return None


def fetch_images(events, lineups, squad_data):
    """Download team logos and PSG player photos, return as id->dataURI maps."""
    team_ids = set()
    player_ids = set()

    for ev in events:
        team_ids.add(ev["homeTeam"]["id"])
        team_ids.add(ev["awayTeam"]["id"])

    # Only fetch photos for PSG players (not all opponents)
    psg_player_ids = set()
    for entry in (squad_data.get("players", [])):
        pid = entry.get("player", {}).get("id")
        if pid:
            psg_player_ids.add(pid)
    # Also grab any PSG player from lineups (in case they left the squad)
    for fid, lineup in lineups.items():
        for side in ("home", "away"):
            for p in (lineup.get(side, {}).get("players", [])):
                pid = p.get("player", {}).get("id")
                if pid:
                    player_ids.add(pid)
    # Only keep PSG-related players
    player_ids = player_ids & psg_player_ids if psg_player_ids else player_ids

    # Fetch team logos
    team_images = {}
    print(f"  Fetching {len(team_ids)} team logos...")
    for tid in team_ids:
        img = fetch_image(f"{BASE_URL}/team/{tid}/image")
        if img:
            team_images[str(tid)] = img
        time.sleep(0.2)

    # Fetch player photos
    player_images = {}
    print(f"  Fetching {len(player_ids)} player photos...")
    for i, pid in enumerate(player_ids):
        if (i + 1) % 20 == 0:
            print(f"    {i + 1}/{len(player_ids)}...")
        img = fetch_image(f"{BASE_URL}/player/{pid}/image")
        if img:
            player_images[str(pid)] = img
        time.sleep(0.15)

    return team_images, player_images


def main():
    print("Paris Stats-Germain - Data Fetcher")
    print("=" * 40)

    print("\n1. Fetching PSG match results...")
    events = fetch_events()
    print(f"   Found {len(events)} finished matches")

    print("\n2. Fetching player stats per match...")
    lineups = fetch_lineups(events)
    print(f"   Got lineups for {len(lineups)} matches")

    print("\n3. Fetching squad info...")
    squad = fetch_squad()
    squad_count = len(squad.get("players", []))
    print(f"   Got {squad_count} squad members")

    print("\n4. Fetching team logos and player photos...")
    team_images, player_images = fetch_images(events, lineups, squad)
    print(f"   Got {len(team_images)} team logos, {len(player_images)} player photos")

    data = {
        "events": events,
        "lineups": lineups,
        "squad": squad,
        "images": {"teams": team_images, "players": player_images},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "psg_id": PSG_ID,
    }

    OUTPUT_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\n5. Saved to {OUTPUT_FILE.name} ({size_kb:.0f} KB)")
    print(f"   {len(events)} matches, {len(lineups)} with player stats")
    print(f"   {len(team_images)} team logos, {len(player_images)} player photos")
    print(f"\nNext step: run 'vercel --prod' to deploy the updated data.")


if __name__ == "__main__":
    main()
