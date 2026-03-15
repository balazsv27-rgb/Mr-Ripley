import json

with open('FRED/all_series_merged.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

series = data.get('series', [])

targets = [
    'DFII10', 'DFII5', 'DGS10', 'DGS2', 'DGS5',
    'T10YIE', 'T5YIE', 'T5YIFR', 'DFF', 'EFFR',
    'DTWEXBGS', 'DTWEXM', 'DTWEXO', 'TWEXB',
    'VIXCLS', 'SP500', 'CPILFESL', 'PCEPI'
]

found = {s['id']: s for s in series if s.get('id') in targets}

for sid, info in found.items():
    print(f"{sid}: {info['observation_start']} -> {info['observation_end']} | freq: {info['frequency_short']}")

print(f"\nFound {len(found)}/{len(targets)} target series")

missing = [t for t in targets if t not in found]
if missing:
    print(f"Missing: {missing}")