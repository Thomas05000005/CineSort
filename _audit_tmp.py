import re, os, sys

with open(r'C:\tmp\truly_unused.txt', 'r', encoding='utf-8') as f:
    truly = [l.strip() for l in f if l.strip()]

all_content = ''
scanned = 0
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', 'dist', '.venv', 'venv', '.pytest_cache', 'build', 'logs'}]
    for fn in files:
        if fn == 'styles.css':
            continue
        if fn.endswith(('.py', '.spec', '.js', '.mjs', '.html', '.json', '.toml', '.yaml', '.yml')):
            fp = os.path.join(root, fn)
            try:
                with open(fp, 'r', encoding='utf-8') as f2:
                    all_content += '\n' + f2.read()
                scanned += 1
            except Exception:
                pass

print(f'Files scanned: {scanned}')
still = []
orphan = []
for c in truly:
    pat = re.compile(r'(?<![a-zA-Z0-9_-])' + re.escape(c) + r'(?![a-zA-Z0-9_-])')
    if pat.search(all_content):
        still.append(c)
    else:
        orphan.append(c)
print(f'Orphan: {len(orphan)}')
print(f'Used in tests/other: {len(still)}')
print('--- ORPHAN ---')
for c in sorted(orphan): print('  ' + c)
print('--- IN TESTS ---')
for c in sorted(still): print('  ' + c)

with open(r'C:\tmp\truly_orphan.txt', 'w', encoding='utf-8') as f:
    for c in sorted(orphan): f.write(c + '\n')
with open(r'C:\tmp\used_in_tests.txt', 'w', encoding='utf-8') as f:
    for c in sorted(still): f.write(c + '\n')
