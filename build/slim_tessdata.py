"""
Tira dos modelos do Tesseract (pasta `tessdata`) a parte do motor antigo (legacy), que o Prumo não usa:
o OCR roda sempre no motor LSTM. O resultado é o mesmo modelo LSTM, só que bem menor.
Uso: slim_tessdata.py PASTA [PASTA_COPIA_ORIGINAIS]
Arquivos sem parte LSTM (como osd.traineddata) ficam como estão. Rodar duas vezes dá o mesmo resultado.
"""
import struct
import sys
from pathlib import Path

LANG_CONFIG = 0
LSTM_FIRST, LSTM_LAST = 17, 23       # LSTM ... VERSION, na ordem do tessdatamanager.h do Tesseract
KEEP = {LANG_CONFIG, *range(LSTM_FIRST, LSTM_LAST + 1)}


def parse(data: bytes):
    n = struct.unpack_from("<i", data, 0)[0]
    if not 1 <= n <= 64:
        raise ValueError("cabeçalho de traineddata inesperado")
    offs = list(struct.unpack_from(f"<{n}q", data, 4))
    present = sorted((o, i) for i, o in enumerate(offs) if o != -1)
    parts = {}
    for k, (o, i) in enumerate(present):
        end = present[k + 1][0] if k + 1 < len(present) else len(data)
        parts[i] = data[o:end]
    return n, parts


def build(n: int, parts: dict) -> bytes:
    head = 4 + 8 * n
    offs = [-1] * n
    body = b""
    for i in sorted(parts):
        offs[i] = head + len(body)
        body += parts[i]
    return struct.pack("<i", n) + struct.pack(f"<{n}q", *offs) + body


def slim_bytes(data: bytes) -> bytes:
    n, parts = parse(data)
    if LSTM_FIRST >= n or LSTM_FIRST not in parts:
        return data                       # sem LSTM: não mexe
    kept = {i: b for i, b in parts.items() if i in KEEP}
    out = build(n, kept)
    # conferência: o que ficou é idêntico ao que havia
    n2, back = parse(out)
    assert n2 == n and all(back[i] == parts[i] for i in kept) and set(back) == set(kept)
    return out


def main() -> int:
    folder = Path(sys.argv[1])
    backup = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    before = after = 0
    for f in sorted(folder.glob("*.traineddata")):
        data = f.read_bytes()
        new = slim_bytes(data)
        before += len(data)
        after += len(new)
        if new != data:
            if backup is not None:
                backup.mkdir(parents=True, exist_ok=True)
                if not (backup / f.name).exists():
                    (backup / f.name).write_bytes(data)
            f.write_bytes(new)
    print(f"tessdata: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
