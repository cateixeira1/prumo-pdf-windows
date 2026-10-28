"""Usado só na compilação na nuvem: divide o instalador em partes de até 90 MB (limite de arquivo do Git)."""
import sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
data = src.read_bytes()
size = 90 * 1024 * 1024
for i in range(0, len(data), size):
    (out / f"{src.name}.part{i // size + 1:02d}").write_bytes(data[i:i + size])
(out / "SETUP.txt").write_text(f"{src.name}\n{len(data)}\n", encoding="utf-8")
print(src.name, len(data))
