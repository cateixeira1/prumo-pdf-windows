"""
Comprimir PDF (reduzir o tamanho do arquivo), em dois níveis:

- "medium" (média): imagens com mais de 150 pontos por polegada (como aparecem na página) são reduzidas
  para 150 e regravadas em JPEG de qualidade 75. Texto, fontes, destaques e a camada de OCR não mudam.
- "high" (alta): imagens reduzidas para 96 pontos por polegada, JPEG de qualidade 50. O arquivo fica bem
  menor; fotos e páginas escaneadas perdem nitidez (letra pequena pode ficar borrada ao ampliar).

Nos dois níveis os fluxos (conteúdo das páginas, fontes) são recompactados e o arquivo é regravado com
fluxos de objetos. O resultado continua um PDF padrão, que abre em qualquer leitor.

Imagens que não são mexidas, por segurança: máscaras de 1 bit, CMYK, paleta (Indexed), com /Decode ou
máscara por cor, JBIG2/CCITT/JPEG 2000. Imagem com poucas cores (captura de tela, gráfico) fica sem perda
(Flate), para não borrar letras. Uma imagem só é trocada se a nova versão for menor.

A resolução de cada imagem é medida pelo tamanho com que ela é desenhada na página (matriz do conteúdo,
inclusive dentro de formulários XObject). Imagem que não é achada no conteúdo usa a diagonal da página
como tamanho máximo possível (assim nunca é reduzida demais).
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Level:
    key: str
    dpi: int
    quality: int


LEVELS = {
    "medium": Level("medium", 150, 75),
    "high": Level("high", 96, 50),
}

# Só reduz se a imagem estiver pelo menos 10% acima da resolução alvo (evita reamostrar quase igual).
_MARGIN = 1.10
# Imagens menores que isto (em pixels) não valem o trabalho.
_MIN_PIXELS = 64 * 64


@dataclass
class Result:
    before: int
    after: int
    images_changed: int
    images_total: int

    @property
    def saved_ratio(self) -> float:
        return 0.0 if not self.before else max(0.0, 1 - self.after / self.before)


class CompressError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário (texto em português; a tela traduz)."""


# --- onde e de que tamanho cada imagem aparece ---------------------------------------

def _mul(m, n):
    """m × n (matrizes PDF [a b c d e f])."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def _nums(ops):
    try:
        return tuple(float(x) for x in ops)
    except (TypeError, ValueError):
        return None


def display_sizes(pdf) -> dict[tuple[int, int], tuple[float, float]]:
    """Para cada imagem (objgen), o maior tamanho (largura, altura) em pontos com que ela é desenhada."""
    import pikepdf

    sizes: dict[tuple[int, int], tuple[float, float]] = {}

    def note(img, ctm):
        w = math.hypot(ctm[0], ctm[1])
        h = math.hypot(ctm[2], ctm[3])
        key = img.objgen
        if key == (0, 0):
            return
        ow, oh = sizes.get(key, (0.0, 0.0))
        sizes[key] = (max(ow, w), max(oh, h))

    def walk(source, resources, ctm, depth):
        if depth > 12:
            return
        try:
            ops = pikepdf.parse_content_stream(source)
        except Exception:  # noqa: BLE001  (conteúdo estragado: o resto do arquivo segue)
            return
        stack = []
        xobjs = None
        try:
            if resources is not None and "/XObject" in resources:
                xobjs = resources.XObject
        except Exception:  # noqa: BLE001
            xobjs = None
        for item in ops:
            operands, op = item[0], str(item[1])
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                if stack:
                    ctm = stack.pop()
            elif op == "cm":
                m = _nums(operands)
                if m and len(m) == 6:
                    ctm = _mul(m, ctm)
            elif op == "Do" and xobjs is not None and operands:
                name = operands[0]
                try:
                    x = xobjs.get(name)
                except Exception:  # noqa: BLE001
                    x = None
                if x is None or not isinstance(x, pikepdf.Stream):
                    continue
                sub = x.get("/Subtype")
                if sub == pikepdf.Name.Image:
                    note(x, ctm)
                elif sub == pikepdf.Name.Form:
                    m = _nums(x.get("/Matrix", [1, 0, 0, 1, 0, 0])) or (1, 0, 0, 1, 0, 0)
                    res = x.get("/Resources", resources)
                    walk(x, res, _mul(m, ctm), depth + 1)

    for page in pdf.pages:
        try:
            res = page.obj.get("/Resources")
            if res is None:
                res = page.Resources if "/Resources" in page else None
        except Exception:  # noqa: BLE001
            res = None
        walk(page, res, (1, 0, 0, 1, 0, 0), 0)
        # aparências das anotações (carimbos, assinaturas visíveis)
        for annot in page.obj.get("/Annots", []) or []:
            try:
                ap = annot.get("/AP")
                n = ap.get("/N") if ap is not None else None
                if isinstance(n, pikepdf.Stream):
                    rect = _nums(annot.get("/Rect", [0, 0, 0, 0])) or (0, 0, 0, 0)
                    bbox = _nums(n.get("/BBox", [0, 0, 1, 1])) or (0, 0, 1, 1)
                    bw, bh = abs(bbox[2] - bbox[0]) or 1, abs(bbox[3] - bbox[1]) or 1
                    sx, sy = abs(rect[2] - rect[0]) / bw, abs(rect[3] - rect[1]) / bh
                    m = _nums(n.get("/Matrix", [1, 0, 0, 1, 0, 0])) or (1, 0, 0, 1, 0, 0)
                    walk(n, n.get("/Resources"), _mul(m, (sx, 0, 0, sy, 0, 0)), 1)
            except Exception:  # noqa: BLE001
                continue
    return sizes


def _page_diagonal(pdf) -> float:
    best = 0.0
    for page in pdf.pages:
        try:
            box = [float(v) for v in page.mediabox]
            best = max(best, math.hypot(box[2] - box[0], box[3] - box[1]))
        except Exception:  # noqa: BLE001
            continue
    return best or math.hypot(612, 842)


# --- uma imagem ------------------------------------------------------------------------

_OK_FILTERS = {"/DCTDecode", "/FlateDecode", "/LZWDecode", "/RunLengthDecode", "/ASCII85Decode",
               "/ASCIIHexDecode"}


def _filters(obj) -> list[str]:
    import pikepdf
    f = obj.get("/Filter")
    if f is None:
        return []
    if isinstance(f, pikepdf.Array):
        return [str(x) for x in f]
    return [str(f)]


def _color_mode(pdf_obj):
    """Modo do Pillow para a imagem ("L" ou "RGB") ou None se o espaço de cor não é tratado."""
    import pikepdf
    cs = pdf_obj.get("/ColorSpace")
    if cs is None:
        return None
    if isinstance(cs, pikepdf.Name):
        return {"/DeviceGray": "L", "/DeviceRGB": "RGB", "/CalGray": "L", "/CalRGB": "RGB"}.get(str(cs))
    try:
        if len(cs) == 2 and str(cs[0]) == "/ICCBased":
            n = int(cs[1].get("/N", 0))
            return {1: "L", 3: "RGB"}.get(n)
    except Exception:  # noqa: BLE001
        return None
    return None


def _few_colors(im) -> bool:
    """Imagem com poucas cores (captura de tela, gráfico, texto): JPEG borraria as bordas."""
    probe = im if im.width * im.height <= 250_000 else im.resize(
        (max(1, im.width // 4), max(1, im.height // 4)), resample=0)  # vizinho mais próximo: não cria cores
    return probe.getcolors(maxcolors=256) is not None


def _decode(obj, mode):
    """Decodifica a imagem para o Pillow, no modo pedido."""
    from PIL import Image

    filters = _filters(obj)
    w, h = int(obj.Width), int(obj.Height)
    if filters and filters[-1] == "/DCTDecode":
        data = obj.read_raw_bytes() if filters == ["/DCTDecode"] else None
        if data is None:
            # filtros antes do DCT (ex.: ASCII85): tira só esses
            import pikepdf
            data = obj.read_bytes(decode_level=pikepdf.StreamDecodeLevel.generalized)
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode == "CMYK":
            return None
        return im.convert(mode) if im.mode != mode else im
    data = obj.read_bytes()
    need = w * h * (1 if mode == "L" else 3)
    if len(data) < need:
        return None
    return Image.frombytes(mode, (w, h), bytes(data[:need]))


def _encode_jpeg(im, quality: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True, subsampling=2 if im.mode == "RGB" else 0)
    return buf.getvalue()


def _shrink_image(pdf, obj, display, level: Level, diag_pts: float) -> bool:
    """Tenta reduzir uma imagem. Devolve True se foi trocada."""
    import zlib

    import pikepdf
    from PIL import Image

    if obj.get("/ImageMask", False) or int(obj.get("/BitsPerComponent", 8)) != 8:
        return False
    if "/Decode" in obj or "/Mask" in obj:
        return False
    filters = _filters(obj)
    if any(f not in _OK_FILTERS for f in filters):
        return False
    mode = _color_mode(obj)
    if mode is None:
        return False
    w, h = int(obj.Width), int(obj.Height)
    if w * h < _MIN_PIXELS:
        return False
    smask = obj.get("/SMask")
    if smask is not None:
        if not isinstance(smask, pikepdf.Stream) or "/Matte" in smask:
            return False
        if int(smask.get("/BitsPerComponent", 8)) != 8 or any(f not in _OK_FILTERS for f in _filters(smask)):
            return False

    # resolução com que a imagem aparece
    if display and display[0] > 0.5 and display[1] > 0.5:
        dpi = max(w / (display[0] / 72), h / (display[1] / 72))
    else:
        dpi = max(w, h) / (diag_pts / 72)
    scale = 1.0
    if dpi > level.dpi * _MARGIN:
        scale = level.dpi / dpi

    original = len(obj.read_raw_bytes())
    try:
        im = _decode(obj, mode)
    except Exception:  # noqa: BLE001  (formato que o Pillow não lê: fica como está)
        return False
    if im is None:
        return False
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    lossless = filters[-1:] != ["/DCTDecode"] and _few_colors(im)
    if scale < 1.0:
        im = im.resize((nw, nh), Image.LANCZOS, reducing_gap=3.0)
    elif filters[-1:] == ["/DCTDecode"] and level.key == "medium":
        return False   # JPEG já na resolução certa: regravar só perderia qualidade

    if lossless:
        data = zlib.compress(im.tobytes(), 9)
        new_filter = pikepdf.Name.FlateDecode
    else:
        data = _encode_jpeg(im, level.quality)
        new_filter = pikepdf.Name.DCTDecode
    if len(data) >= original * 0.95 and scale == 1.0:
        return False
    if len(data) >= original:
        return False

    new_smask = None
    if smask is not None and (nw, nh) != (w, h):
        try:
            sm = _decode(smask, "L")
            if sm is None:
                return False
            sm = sm.resize((nw, nh), Image.LANCZOS, reducing_gap=3.0)
            new_smask = zlib.compress(sm.tobytes(), 9)
        except Exception:  # noqa: BLE001
            return False

    obj.write(data, filter=new_filter)
    obj.Width, obj.Height = nw, nh
    obj.BitsPerComponent = 8
    if "/DecodeParms" in obj:
        del obj["/DecodeParms"]
    if new_smask is not None:
        smask.write(new_smask, filter=pikepdf.Name.FlateDecode)
        smask.Width, smask.Height = nw, nh
        if "/DecodeParms" in smask:
            del smask["/DecodeParms"]
    return True


# --- o arquivo ---------------------------------------------------------------------------

def compress(src: str | Path, dest: str | Path, level: str = "medium", progress=None) -> Result:
    """Grava em `dest` uma versão menor de `src`. `progress(i, total)` é chamado a cada imagem."""
    import pikepdf

    if level not in LEVELS:
        raise ValueError(level)
    lv = LEVELS[level]
    src, dest = Path(src), Path(dest)
    before = src.stat().st_size
    try:
        pdf = pikepdf.open(str(src))
    except pikepdf.PasswordError:
        raise CompressError("O PDF está protegido por senha.") from None
    except pikepdf.PdfError as exc:
        raise CompressError(__import__("i18n").trf("Não foi possível abrir o PDF ({}).", exc)) from None
    with pdf:
        smasks = set()
        images = []
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name.Image:
                images.append(obj)
                sm = obj.get("/SMask")
                if isinstance(sm, pikepdf.Stream):
                    smasks.add(sm.objgen)
        images = [o for o in images if o.objgen not in smasks]
        sizes = display_sizes(pdf)
        diag = _page_diagonal(pdf)
        changed = 0
        for i, obj in enumerate(images):
            if progress:
                progress(i + 1, len(images))
            try:
                if _shrink_image(pdf, obj, sizes.get(obj.objgen), lv, diag):
                    changed += 1
            except Exception:  # noqa: BLE001  (uma imagem estranha não impede as outras)
                continue
        for page in pdf.pages:
            if "/Thumb" in page.obj:          # miniaturas embutidas: os leitores criam as suas
                del page.obj["/Thumb"]
        try:
            pdf.remove_unreferenced_resources()
        except Exception:  # noqa: BLE001
            pass
        tmp = dest.with_name(dest.name + ".part")
        old_level = None
        try:
            old_level = pikepdf.settings.get_flate_compression_level() \
                if hasattr(pikepdf.settings, "get_flate_compression_level") else None
            pikepdf.settings.set_flate_compression_level(9)
            pdf.save(str(tmp), object_stream_mode=pikepdf.ObjectStreamMode.generate, compress_streams=True,
                     stream_decode_level=pikepdf.StreamDecodeLevel.generalized, recompress_flate=True)
        finally:
            pikepdf.settings.set_flate_compression_level(old_level if old_level is not None else -1)
    os.replace(tmp, dest)
    after = dest.stat().st_size
    return Result(before, after, changed, len(images))

