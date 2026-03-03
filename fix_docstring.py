content = open('layer2/adapters/move_adapter.py', encoding='utf-8').read()
content = '"""\n' + content
open('layer2/adapters/move_adapter.py', 'w', encoding='utf-8').write(content)
print('Done')