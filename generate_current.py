import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
content_path = ROOT / "content.json"
current_path = ROOT / "current.json"

with content_path.open("r", encoding="utf-8") as f:
    data = json.load(f)

cards = data.get("cards", [])
if not cards:
    raise ValueError("content.json has no cards")

card = random.choice(cards)

output = {
    "title": data.get("title", "Dungeon Crawl Feed"),
    "subtitle": data.get("subtitle", ""),
    "footer": data.get("footer", "")
}

output.update(card)

with current_path.open("w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Wrote current.json using mode={output.get('mode')}")
