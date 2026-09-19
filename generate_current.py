#!/usr/bin/env python3
"""Generate current.json for TRMNL. Python 3.9+; no external dependencies.

Default invocation changes only current.json, including its persistent shuffle
queue. Keep current.json in git so the queue survives fresh Actions checkouts.
"""
import argparse
import hashlib
import html
import json
import random
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIMITS = {'id': 60, 'mode': 16, 'category': 26, 'headline': 48, 'body': 200,
          'context': 24, 'location': 22, 'subject': 24, 'detail_label': 26,
          'detail': 24, 'floor_label': 12, 'source_locator': 100, 'source_id': 30}
MODES = ('incident', 'dossier', 'loot', 'rule', 'enemy', 'broadcast')


def read_json(path):
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def atomic_write(path, text):
    """Replace a complete UTF-8 file; a failed write cannot leave partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    # Compact output keeps the polling feed small, even with its saved queue.
    atomic_write(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def validate(data):
    if not isinstance(data, dict) or data.get('schema_version') != 3:
        raise ValueError('Install the v3 content.json alongside this generator')
    for key in ('title', 'subtitle', 'footer'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'Missing archive {key}')
    if not isinstance(data.get('cards'), list) or not data['cards']:
        raise ValueError('content.json has no cards')
    seen = set()
    for card in data['cards']:
        if not isinstance(card, dict):
            raise ValueError('Every card must be a JSON object')
        for field, limit in LIMITS.items():
            value = card.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f'{card.get("id", "unknown")}: {field} must be 1..{limit} characters')
        if card['id'] in seen:
            raise ValueError(f'Duplicate card id: {card["id"]}')
        seen.add(card['id'])
        for key in ('book', 'chapter', 'order'):
            if type(card.get(key)) is not int or card[key] < 1:
                raise ValueError(f'{card["id"]}: {key} must be a positive integer')
        if card['mode'] not in MODES:
            raise ValueError(f'{card["id"]}: unknown mode')
        source = data.get('sources', {}).get(card['source_id'])
        if not isinstance(source, dict) or source.get('type') not in ('primary', 'secondary'):
            raise ValueError(f'{card["id"]}: missing or invalid source')
        pages = card.get('source_pages')
        total = source.get('pdf_pages')
        if (not isinstance(pages, list) or len(pages) != 2
            or any(type(p) is not int for p in pages) or type(total) is not int
            or not 1 <= pages[0] <= pages[1] <= total):
            raise ValueError(f'{card["id"]}: source_pages must be a valid inclusive PDF page range')


def eligible_cards(data, max_book, max_chapter=48):
    # Chapter ceiling applies to the highest allowed book, not earlier books.
    cards = sorted((c for c in data['cards'] if c['book'] < max_book or
                    (c['book'] == max_book and c['chapter'] <= max_chapter)),
                   key=lambda c: (c['book'], c['order'], c['id']))
    if not cards:
        raise ValueError('No cards pass the book/chapter limit')
    return cards


def pick(cards, previous, rotation, rng):
    ids = [c['id'] for c in cards]
    last = previous.get('id')
    if rotation == 'chronological':
        index = (ids.index(last) + 1) % len(ids) if last in ids else 0
        return cards[index], {}
    fingerprint = hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()[:24]
    state = previous.get('_rotation', {})
    if not isinstance(state, dict):
        state = {}
    remaining = state.get('remaining') if state.get('fingerprint') == fingerprint else None
    # Use compact integer positions rather than dozens of long card IDs.
    valid = (isinstance(remaining, list) and
             all(type(i) is int and 0 <= i < len(cards) for i in remaining))
    if valid:
        valid = len(set(remaining)) == len(remaining)
    if not valid:
        remaining = []
    else:
        remaining = [i for i in remaining if ids[i] != last]
    if not remaining:
        remaining = list(range(len(cards)))
        rng.shuffle(remaining)
        if len(remaining) > 1 and ids[remaining[0]] == last:
            remaining[0], remaining[1] = remaining[1], remaining[0]
    selected = remaining.pop(0)
    return cards[selected], {'fingerprint': fingerprint, 'remaining': remaining}


def output_for(data, card, position, total, timestamp):
    first, last = card['source_pages']
    page_label = f'PDF P. {first}' if first == last else f'PDF PP. {first}-{last}'
    return {**card, 'schema_version': 3, 'title': data['title'], 'subtitle': data['subtitle'],
            'footer': data['footer'], 'generated_at_utc': timestamp,
            'updated_label': timestamp[11:16] + ' UTC', 'book_label': f'BOOK {card["book"]:02}',
            'archive_label': f'{position:02} / {total:02}',
            'source_label': page_label, 'source_type_label': 'BOOK 1 / FRENCH PDF',
            'content_label': 'ENGLISH RECAP / SCENE SNAPSHOT'}


def render_preview(template, values):
    # Matches the supplied Liquid template's escaped, flat variables exactly.
    return re.sub(r'{{\s*(\w+)\s*\|\s*escape\s*}}',
                  lambda match: html.escape(str(values.get(match[1], '')), quote=True), template)


def preview_document(data, card):
    template = (ROOT / 'markup_full.liquid').read_text(encoding='utf-8')
    screen = render_preview(template, card)
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>DCC Broadcast Preview</title><body style="margin:0;background:white">'
            + screen + '</body></html>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-book', type=int)
    parser.add_argument('--max-chapter', type=int, help='In Book 1, 48 means the epilogue')
    parser.add_argument('--rotation', choices=['shuffle', 'chronological'])
    parser.add_argument('--card', help='Preview an eligible card without changing current.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--preview', action='store_true', help='Also write preview.html')
    parser.add_argument('--webhook', action='store_true', help='Also write webhook.json')
    args = parser.parse_args()
    data = read_json(ROOT / 'content.json')
    config = read_json(ROOT / 'config.json') if (ROOT / 'config.json').exists() else {}
    if not isinstance(config, dict):
        raise ValueError('config.json must be an object')
    validate(data)
    max_book = args.max_book if args.max_book is not None else config.get('max_book', 1)
    max_chapter = args.max_chapter if args.max_chapter is not None else config.get('max_chapter', 48)
    rotation = args.rotation or config.get('rotation', 'shuffle')
    if any(type(v) is not int or v < 1 for v in (max_book, max_chapter)) or rotation not in ('shuffle', 'chronological'):
        raise ValueError('Invalid book/chapter limit or rotation')
    cards = eligible_cards(data, max_book, max_chapter)
    if args.validate_only:
        print(f'Valid: {len(cards)} eligible cards; {len(data["cards"])} total')
        return
    output_dir = args.output_dir.resolve()
    current_path = output_dir / 'current.json'
    previous = {}
    if current_path.exists():
        try:
            previous = read_json(current_path)
            if not isinstance(previous, dict):
                previous = {}
        except (ValueError, OSError):
            print('Warning: unreadable previous card; starting a new rotation.', file=sys.stderr)
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if args.card:
        card = next((c for c in cards if c['id'] == args.card), None)
        if card is None:
            raise ValueError('Card not found or excluded by spoiler limit')
        state = {}
    else:
        card, state = pick(cards, previous, rotation, random.SystemRandom())
    output = output_for(data, card, cards.index(card) + 1, len(cards), timestamp)
    if args.card:
        atomic_write(output_dir / 'preview.html', preview_document(data, output))
        print(f'Preview only: {card["id"]}; current.json unchanged')
        return
    # Prepare optional artifacts before committing the rotation in current.json.
    if args.webhook:
        payload = {'merge_variables': output}
        if len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 2000:
            raise ValueError('Webhook exceeds the conservative 2,000-byte budget')
        write_json(output_dir / 'webhook.json', payload)
    if args.preview:
        atomic_write(output_dir / 'preview.html', preview_document(data, output))
    write_json(current_path, {**output, '_rotation': state})
    print(f'Wrote current.json: {card["id"]} ({card["context"]}, {output["source_label"]})')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.exit(f'Error: {error}')
