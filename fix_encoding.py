import os

files = [
    'layer2/adapters/move_adapter.py',
    'layer2/adapters/gld_holdings_adapter.py'
]

replacements = {
    '\u2014': '-',
    '\u2192': '->',
    '\u2190': '<-',
    '\u2019': "'",
    '\u2018': "'",
    '\u201c': '"',
    '\u201d': '"',
}

for f in files:
    content = open(f, encoding='utf-8').read()
    for old, new in replacements.items():
        content = content.replace(old, new)
    open(f, 'w', encoding='utf-8').write(content)
    print(f'Fixed: {f}')

print('All done.')