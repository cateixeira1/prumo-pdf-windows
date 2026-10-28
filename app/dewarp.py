"""
Correção de páginas curvas (lombada de livro, papel ondulado ou dobrado) em fotos.

Usa o modelo UVDoc (Verhoeven, Magne e Sorkine-Hornung, SIGGRAPH Asia 2023; código e modelo
sob licença MIT, github.com/tanguymagne/UVDoc), exportado para ONNX e rodando neste computador
com o ONNX Runtime. O modelo olha a foto reduzida (488 × 712) e devolve uma grade de 45 × 31
pontos que diz de onde vem cada parte da página "desentortada". A foto original é então
redesenhada com essa grade, em resolução cheia, sem perder nitidez.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

INPUT_W, INPUT_H = 488, 712
CURVED = 0.006   # acima disso a página é tratada como curva (ajustado com páginas de teste)
_session = None
_lock = threading.Lock()


def model_path() -> Path | None:
    bases = []
    if getattr(sys, "_MEIPASS", None):
        bases.append(Path(sys._MEIPASS))
    bases.append(Path(__file__).resolve().parent.parent)
    for b in bases:
        p = b / "models" / "uvdoc.onnx"
        if p.exists():
            return p
    return None


def available() -> bool:
    if model_path() is None:
        return False
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _get_session():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            path = model_path()
            if path is None:
                from pdfops import UserError
                raise UserError("O modelo de correção de curvatura não foi encontrado na instalação.")
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            _session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        return _session


def predict_grid(image):
    """Grade 2 × 45 × 31, em coordenadas normalizadas (-1 a 1) da imagem de entrada."""
    import numpy as np
    small = image.convert("RGB").resize((INPUT_W, INPUT_H), resample=3)   # 3 = BICUBIC
    x = np.asarray(small, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return _get_session().run(None, {"image": x})[0][0]


def unwarp(image, grid=None):
    """Imagem desentortada, no mesmo tamanho da original."""
    from PIL import Image
    img = image.convert("RGB")
    w, h = img.size
    g = predict_grid(img) if grid is None else grid
    gy, gx = g.shape[1], g.shape[2]
    px = (g[0] + 1) * 0.5 * (w - 1)
    py = (g[1] + 1) * 0.5 * (h - 1)
    xs = [round(j * (w - 1) / (gx - 1)) for j in range(gx)]
    ys = [round(i * (h - 1) / (gy - 1)) for i in range(gy)]
    mesh = []
    for i in range(gy - 1):
        for j in range(gx - 1):
            box = (xs[j], ys[i], xs[j + 1] + 1, ys[i + 1] + 1)
            quad = (float(px[i, j]), float(py[i, j]),             # alto à esquerda
                    float(px[i + 1, j]), float(py[i + 1, j]),     # baixo à esquerda
                    float(px[i + 1, j + 1]), float(py[i + 1, j + 1]),  # baixo à direita
                    float(px[i, j + 1]), float(py[i, j + 1]))     # alto à direita
            mesh.append((box, quad))
    return img.transform((w, h), Image.MESH, mesh, resample=Image.BICUBIC, fillcolor=(255, 255, 255))


def curvature_score(grid) -> float:
    """
    Quanto a página está curva (0 = plana). Compara a grade do modelo com a melhor perspectiva
    reta (homografia) que a explica: uma página plana, mesmo torta ou fotografada de lado, se
    encaixa numa perspectiva; uma página curva (lombada, papel ondulado), não. Serve para não
    mexer em páginas que já estão retas, como digitalizações de scanner de mesa.
    """
    import numpy as np
    gy, gx = grid.shape[1], grid.shape[2]
    u, v = np.meshgrid(np.linspace(-1, 1, gx), np.linspace(-1, 1, gy))
    src = np.stack([u.ravel(), v.ravel()], axis=1)
    dst = np.stack([grid[0].ravel(), grid[1].ravel()], axis=1)
    # homografia por mínimos quadrados (DLT)
    rows = []
    for (x, y), (X, Y) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -X * x, -X * y, -X])
        rows.append([0, 0, 0, x, y, 1, -Y * x, -Y * y, -Y])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    H = vt[-1].reshape(3, 3)
    pts = np.c_[src, np.ones(len(src))] @ H.T
    proj = pts[:, :2] / pts[:, 2:3]
    span = max(float(np.ptp(dst[:, 0])), float(np.ptp(dst[:, 1])), 1e-6)
    return float(np.sqrt(np.mean(np.sum((proj - dst) ** 2, axis=1)))) / span


def unwarp_if_needed(image, threshold: float = CURVED):
    """Corrige só se a página estiver de fato curva ou fora de esquadro. Devolve (imagem, corrigiu?)."""
    grid = predict_grid(image)
    if curvature_score(grid) < threshold:
        return image, False
    return unwarp(image, grid), True


# --- PDFs (escaneados ou fotos) -------------------------------------------------------

def render_page(src: Path, index: int, dpi: int = 200):
    import pypdfium2 as pdfium

    import core
    with core.PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(src))
        try:
            page = pdf[index]
            size = page.get_size()
            pil = page.render(scale=dpi / 72).to_pil().convert("RGB")
            page.close()
            return pil, size
        finally:
            pdf.close()


def dewarp_pdf(src: Path, dest: Path, pages: list[int] | None = None, progress=None, dpi: int = 200) -> int:
    """
    Cria um PDF novo em que as páginas escolhidas (começando em 1; None = todas) são corrigidas.
    Cada página corrigida vira imagem, no mesmo tamanho da original; as outras ficam intactas
    (com o texto que já tinham). Devolve quantas páginas foram corrigidas.
    """
    import io

    import img2pdf
    import pikepdf

    import pdfops
    total = pdfops.page_count(src)
    chosen = sorted(set(pages)) if pages else list(range(1, total + 1))
    fixed_pages: dict[int, bytes] = {}
    for k, n in enumerate(chosen, 1):
        if progress:
            progress(k, len(chosen), f"Página {n}")
        pil, (w_pt, h_pt) = render_page(src, n - 1, dpi)
        out = unwarp(pil)
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=90)
        layout = img2pdf.get_layout_fun((w_pt, h_pt), fit=img2pdf.FitMode.into)
        fixed_pages[n] = img2pdf.convert([buf.getvalue()], layout_fun=layout)
    with pikepdf.open(str(src)) as original, pikepdf.new() as out_pdf:
        for n in range(1, total + 1):
            if n in fixed_pages:
                with pikepdf.open(io.BytesIO(fixed_pages[n])) as one:
                    out_pdf.pages.append(one.pages[0])
            else:
                out_pdf.pages.append(original.pages[n - 1])
        out_pdf.save(str(dest))
    return len(fixed_pages)
