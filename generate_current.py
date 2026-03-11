import json
import random
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
content_path = ROOT / "content.json"
current_path = ROOT / "current.json"

with content_path.open("r", encoding="utf-8") as f:
    data = json.load(f)

cards = data.get("cards", [])
if not cards:
    raise ValueError("content.json has no cards")

previous = None
if current_path.exists():
    try:
        with current_path.open("r", encoding="utf-8") as f:
            previous = json.load(f)
    except Exception:
        previous = None

# Avoid repeating the exact same card if possible
random.shuffle(cards)
card = cards[0]
if previous and len(cards) > 1:
    for candidate in cards:
        same_mode = candidate.get("mode") == previous.get("mode")
        same_headline = candidate.get("headline") == previous.get("headline")
        if not (same_mode and same_headline):
            card = candidate
            break

# Shared rotating broadcast labels
floor_label = random.choice(["F5", "F6", "F7", "F8", "F9"])
trend_label = random.choice(["RISING", "FALLING", "VOLATILE", "SPIKING"])
threat_label = random.choice(["MED", "HIGH", "SEVERE", "LETHAL"])
sponsor_label = random.choice(["WATCHING", "PLEASED", "BORED", "INVESTED"])

output = {
    "title": data.get("title", "Dungeon Crawl Feed"),
    "subtitle": data.get("subtitle", ""),
    "footer": data.get("footer", ""),
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "floor_label": floor_label,
    "trend_label": trend_label,
    "threat_label": threat_label,
    "sponsor_label": sponsor_label,
}

output.update(card)

with current_path.open("w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Wrote current.json with mode={output.get('mode')} headline={output.get('headline')}")
