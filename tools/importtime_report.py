"""Lê a saída de `python -X importtime` (arquivo) e mostra os módulos que mais demoram para importar.
Uso: importtime_report.py ARQUIVO [N]"""
import re
import sys

rows = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = re.match(r"import time:\s+(\d+) \|\s+(\d+) \| (\s*)(\S+)", line)
    if m:
        rows.append((int(m.group(2)), len(m.group(3)) // 2, m.group(4)))
n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
top = [r for r in rows if r[1] == 0]
print(f"Total (módulos de nível 0): {sum(r[0] for r in top) / 1e6:.2f} s\n")
print("--- maiores tempos acumulados (ms) ---")
for cum, depth, name in sorted(rows, reverse=True)[:n]:
    print(f"{cum / 1000:8.1f} ms  {'  ' * depth}{name}")
