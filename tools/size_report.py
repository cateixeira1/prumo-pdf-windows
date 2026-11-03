"""Relatório de tamanho do pacote (dist/PrumoPDF): maiores arquivos e total por pasta/tipo.
Uso: size_report.py PASTA [N]"""
import collections
import sys
from pathlib import Path

root = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
files = [(f.stat().st_size, f.relative_to(root).as_posix()) for f in root.rglob("*") if f.is_file()]
total = sum(s for s, _ in files)
print(f"TOTAL: {total / 1e6:.1f} MB em {len(files)} arquivos\n")
print(f"--- {n} maiores arquivos ---")
for s, name in sorted(files, reverse=True)[:n]:
    print(f"{s / 1e6:8.2f} MB  {name}")
by_dir = collections.Counter()
for s, name in files:
    parts = name.split("/")
    key = "/".join(parts[:3]) if len(parts) > 2 else "/".join(parts[:-1]) or "."
    by_dir[key] += s
print("\n--- pastas (até 3 níveis) ---")
for k, s in by_dir.most_common(30):
    print(f"{s / 1e6:8.2f} MB  {k}")
by_ext = collections.Counter()
for s, name in files:
    by_ext[Path(name).suffix.lower() or "(sem)"] += s
print("\n--- por tipo ---")
for k, s in by_ext.most_common(12):
    print(f"{s / 1e6:8.2f} MB  {k}")
