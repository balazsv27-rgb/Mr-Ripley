import json

# Check gold_sereies.json
print("=== FRED gold_sereies.json ===")
with open('FRED/gold_sereies.json', 'r', encoding='utf-8') as f:
    gold = json.load(f)

print('Type:', type(gold))
if isinstance(gold, dict):
    print('Keys:', list(gold.keys())[:10])
elif isinstance(gold, list):
    print('Total items:', len(gold))
    print('First item:', str(gold[0])[:300])

print()

# Check alphavangtage.json
print("=== alphavangtage.json ===")
with open('alphavangtage.json', 'r', encoding='utf-8') as f:
    alpha = json.load(f)

print('Type:', type(alpha))
if isinstance(alpha, dict):
    print('Keys:', list(alpha.keys())[:10])
elif isinstance(alpha, list):
    print('Total items:', len(alpha))
    print('First item:', str(alpha[0])[:300])