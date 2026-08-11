import ast

files = [
    r'c:\Users\nxt\Desktop\lc-course\AIRAGAgent\agent\memory\extractor.py',
    r'c:\Users\nxt\Desktop\lc-course\AIRAGAgent\agent\memory\migrate_legacy.py',
    r'c:\Users\nxt\Desktop\lc-course\AIRAGAgent\agent\memory\vector_store.py',
    r'c:\Users\nxt\Desktop\lc-course\AIRAGAgent\database\connection.py',
    r'c:\Users\nxt\Desktop\lc-course\AIRAGAgent\database\models.py',
]

for f in files:
    src = open(f, encoding='utf-8').read()
    tree = ast.parse(src)
    lines = src.splitlines()
    missing = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ln = n.lineno - 1
            j = ln + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                missing.append((n.name, ln + 1))
                continue
            body_first = lines[j].strip()
            if not (body_first.startswith('"""') or body_first.startswith("'''") or body_first.startswith('#')):
                missing.append((n.name, ln + 1))
    print(('OK  ' if not missing else 'MISS'), f.replace('c:\\Users\\nxt\\Desktop\\lc-course\\', ''))
    for m in missing:
        print('   missing:', m)
