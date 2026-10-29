"""
Resumo de um PDF: os trechos escolhidos no leitor ("Adicionar ao resumo deste PDF") vão para um
PDF à parte, "Nome - resumo.pdf", na mesma pasta do original. Embaixo de cada trecho, em letra
menor, vai de onde ele saiu: "Trecho extraído da página 10" ou "das páginas 10-11".

Os trechos ficam anotados em <biblioteca>/.prumo/resumos/<código>.json (o mesmo formato no iPhone),
para o resumo ser refeito inteiro a cada trecho novo, sem repetir o cabeçalho. Se o resumo foi
mudado em outro programa (ou num aparelho sem essa anotação), as páginas que ele já tem ficam como
estão e os trechos novos entram depois delas: nada do que já estava lá se perde.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

SUFFIX = " - resumo"
STORE_DIR = ("." + "prumo", "resumos")


def summary_name(item) -> str:
    return f"{item.name}{SUFFIX}"


def summary_rel(item) -> str:
    name = f"{summary_name(item)}.pdf"
    return f"{item.folder}/{name}" if item.folder else name


def find_summary(lib, item):
    """O resumo deste PDF, se já existir na mesma pasta."""
    return lib.item_by_path(summary_rel(item))


def pages_label(pages: list[int]) -> str:
    """[10] → "Trecho extraído da página 10"; [10, 11] → "Trecho extraído das páginas 10-11"."""
    pages = sorted(set(int(p) for p in pages))
    if not pages:
        return "Trecho extraído"
    if pages[0] == pages[-1]:
        return f"Trecho extraído da página {pages[0]}"
    return f"Trecho extraído das páginas {pages[0]}-{pages[-1]}"


def file_signature(path) -> str:
    """Tamanho + SHA-1 do conteúdo: o mesmo valor no Windows e no iPhone para o mesmo arquivo."""
    data = Path(path).read_bytes()
    return f"{len(data)}-{hashlib.sha1(data).hexdigest()}"


def _store_path(lib, rel: str) -> Path:
    key = hashlib.sha1(rel.casefold().encode("utf-8")).hexdigest()[:20]
    return Path(lib.root, *STORE_DIR) / f"{key}.json"


def load_store(lib, rel: str) -> dict | None:
    p = _store_path(lib, rel)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("excerpts"), list) else None
    except (OSError, ValueError):
        return None


def save_store(lib, rel: str, data: dict) -> None:
    p = _store_path(lib, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def build_pdf(dest, source_name: str, excerpts: list[dict], header: bool = True) -> int:
    """Grava os trechos num PDF A4 com texto selecionável. Devolve o número de páginas."""
    from convert import _latin1_safe, _new_pdf

    pdf, family = _new_pdf(f"Resumo de {source_name}")
    safe = lambda t: _latin1_safe(t, family)   # noqa: E731
    if header:
        pdf.set_font(family, "B" if family == "Texto" else "", 16)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 8, safe(f"Resumo de “{source_name}”"))
        pdf.set_font(family, "", 9.5)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, safe("Trechos selecionados no Prumo PDF, na ordem em que foram adicionados."))
        pdf.ln(4)
        y = pdf.get_y()
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(6)
    for ex in excerpts:
        text = str(ex.get("text", "")).strip()
        if not text:
            continue
        pdf.set_font(family, "", 11.5)
        pdf.set_text_color(30, 30, 30)
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        for k, para in enumerate(paras):
            pdf.multi_cell(0, 6, safe(" ".join(para.split())))
            if k < len(paras) - 1:
                pdf.ln(2)
        if pdf.get_y() + 6 > pdf.h - pdf.b_margin:
            pdf.add_page()
        pdf.ln(1)
        pdf.set_font(family, "I" if family == "Texto" else "", 9)
        pdf.set_text_color(115, 115, 115)
        pdf.multi_cell(0, 5, safe(pages_label(ex.get("pages", []))))
        pdf.ln(7)
    pdf.output(str(dest))
    return pdf.page_no()


def _write(dest: Path, base_file: Path | None, base_pages: int, source_name: str, excerpts: list[dict]) -> None:
    """Monta o resumo: as primeiras `base_pages` páginas de `base_file` e, depois, os trechos."""
    import pikepdf

    tmp = dest.with_name(dest.name + ".resumo.pdf")
    try:
        build_pdf(tmp, source_name, excerpts, header=base_pages == 0)
        if base_pages and base_file is not None:
            with pikepdf.open(str(base_file)) as base, pikepdf.open(str(tmp)) as new:
                while len(base.pages) > base_pages:
                    del base.pages[-1]
                base.pages.extend(new.pages)
                out = dest.with_name(dest.name + ".part")
                base.save(str(out), object_stream_mode=pikepdf.ObjectStreamMode.generate)
            out.replace(dest)
        else:
            tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def add_excerpts(lib, item, new: list) -> object:
    """
    Acrescenta trechos ao resumo de `item` (criando o resumo, se preciso). `new`: [(páginas, texto)].
    Devolve o item do resumo.
    """
    from pdfops import UserError, page_count

    new = [{"pages": [int(p) for p in pages], "text": text.strip(), "added": time.strftime("%Y-%m-%dT%H:%M:%S")}
           for pages, text in new if text and text.strip()]
    if not new:
        raise UserError("Selecione um trecho com texto para adicionar ao resumo.")
    rel = summary_rel(item)
    current = lib.item_by_path(rel)
    store = load_store(lib, rel) if current is not None else None
    if current is not None and store is not None and store.get("signature") == file_signature(current.path):
        base_pages = int(store.get("base_pages", 0) or 0)
        excerpts = list(store["excerpts"])
    elif current is not None:
        # resumo sem anotação (ou mudado fora do Prumo): as páginas atuais ficam, os trechos vêm depois
        base_pages = page_count(current.path)
        excerpts = []
    else:
        base_pages, excerpts = 0, []
    excerpts += new
    if current is None:
        dest = lib.unique_path(item.folder, summary_name(item))
        _write(dest, None, 0, item.name, excerpts)
        result = lib.register(dest)
        if result is None:
            raise UserError("O resumo foi salvo, mas não apareceu na biblioteca.")
        rel = result.rel
    else:
        base = lib.temp_path()
        import shutil
        shutil.copy2(current.path, base)
        try:
            lib.modify(current, lambda path: _write(Path(path), base, base_pages, item.name, excerpts))
        finally:
            base.unlink(missing_ok=True)
        result = lib.item(current.id) or current
    save_store(lib, rel, {"version": 1, "source": item.rel, "title": item.name, "base_pages": base_pages,
                          "signature": file_signature(result.path), "excerpts": excerpts})
    return result
