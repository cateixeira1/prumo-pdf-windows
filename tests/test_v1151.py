"""
Versão 1.15.1: correções de segurança e análise mais leve.

- Nome de arquivo nunca entra no texto de um script do PowerShell (conversão pelo Office) e as cinco aspas
  simples que o PowerShell aceita são tratadas (proteção contra ransomware, que roda como administrador).
- Conversão de HTML: só imagens embutidas ou da pasta do próprio arquivo; nada da internet nem de outras pastas.
- O id lido do .prumo/library.json só vale com formato de id (ele vira nome de arquivo nas pastas do Prumo).
- A análise de um PDF novo lê o texto uma vez só e solta o PDFium entre as páginas.
- Senha do Prumo com 600 mil rodadas; as antigas continuam valendo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import digital_pdf  # noqa: E402

# Nomes que fechariam um texto entre aspas no PowerShell se só o apóstrofo comum fosse tratado.
HOSTILE = [
    "relatorio\u2019; Set-Content -Path $env:PRUMO_MARK -Value x; \u2018.docx",
    "it's",
    "\u201a\u201bx'\u2018\u2019",
    "$(Set-Content -Path $env:PRUMO_MARK -Value y) `n \"q\" \u201cd\u201d",
]


def _powershell() -> str | None:
    import winsys
    if os.name == "nt":
        return winsys.powershell()
    return shutil.which("pwsh")


# --- PowerShell -----------------------------------------------------------------------------------

def test_office_scripts_never_contain_the_file_name():
    import convert
    for progid, script in convert._PS.items():
        assert "{src}" not in script and "{dst}" not in script, progid
        assert "$env:PRUMO_SRC" in script and "$env:PRUMO_DST" in script, progid
        assert "{{" not in script and "}}" not in script, f"{progid}: sobrou marca de format()"


def test_office_conversion_passes_paths_by_environment(tmp_path, monkeypatch):
    import convert
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
        Path(kw["env"]["PRUMO_DST"]).write_bytes(b"%PDF-1.4\n")

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()

    monkeypatch.setattr(convert.subprocess, "run", fake_run)
    src = tmp_path / "relatorio\u2019; calc; \u2018.docx"      # um nome que o Windows aceita em arquivo
    src.write_bytes(b"x")
    dest = tmp_path / "saida.pdf"
    convert.office_to_pdf("Word.Application", src, dest)
    assert seen["env"]["PRUMO_SRC"] == str(src.resolve())
    assert seen["env"]["PRUMO_DST"] == str(dest.resolve())
    assert not any("calc" in str(part) for part in seen["cmd"]), "o nome do arquivo foi parar no comando"
    assert seen["cmd"][-1] == convert._PS["Word.Application"]


def test_ps_quote_doubles_every_single_quote_powershell_accepts():
    import winsys
    assert winsys.ps_quote("it's") == "'it''s'"
    for ch in "'\u2018\u2019\u201a\u201b":
        assert winsys.ps_quote(f"a{ch}b") == f"'a{ch}{ch}b'"
    assert winsys.ps_quote("C:\\Pasta $x `y") == "'C:\\Pasta $x `y'"


def test_cfa_script_escapes_typographic_quotes():
    import protection
    s = protection.script("C:\\Users\\Ana\\Prumo\u2019; calc; \u2018", "C:\\Program Files\\Prumo PDF\\PrumoPDF.exe", enable=False)
    assert "'C:\\Users\\Ana\\Prumo\u2019\u2019; calc; \u2018\u2018'" in s


def test_powershell_really_keeps_hostile_names_as_text(tmp_path):
    """No PowerShell de verdade: o nome volta igual e nada dele é executado."""
    ps = _powershell()
    if not ps:
        pytest.skip("sem PowerShell neste computador")
    import winsys
    mark = tmp_path / "executou.txt"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    base = [ps, "-NoProfile", "-NonInteractive", "-Command"]
    utf8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    for name in HOSTILE:
        env = dict(os.environ, PRUMO_MARK=str(mark), PRUMO_SRC=name)
        quoted = subprocess.run(base + [utf8 + "[Console]::Out.Write(" + winsys.ps_quote(name) + ")"],
                                capture_output=True, env=env, timeout=120, creationflags=flags)
        assert quoted.stdout.decode("utf-8-sig") == name, quoted.stderr
        by_env = subprocess.run(base + [utf8 + "[Console]::Out.Write($env:PRUMO_SRC)"],
                                capture_output=True, env=env, timeout=120, creationflags=flags)
        assert by_env.stdout.decode("utf-8-sig") == name, by_env.stderr
    assert not mark.exists(), "um pedaço do nome foi executado como comando"


# --- HTML -------------------------------------------------------------------------------------------

def _png(path: Path, color="red") -> Path:
    from PIL import Image
    Image.new("RGB", (40, 40), color).save(path)
    return path


def test_html_keeps_only_embedded_and_same_folder_images(tmp_path):
    import base64

    import convert
    doc = tmp_path / "doc"
    (doc / "figuras").mkdir(parents=True)
    _png(doc / "ok.png")
    _png(doc / "figuras" / "dentro.png")
    outside = _png(tmp_path / "fora.png")
    (doc / "segredo.txt").write_text("x", encoding="utf-8")
    data = "data:image/png;base64," + base64.b64encode((doc / "ok.png").read_bytes()).decode()
    blocked = [
        '<img src="http://exemplo.com/rastreio.png">',
        "<img src=https://exemplo.com/sem-aspas.png>",
        "<IMG SRC='HTTPS://EXEMPLO.COM/X.PNG'>",
        f'<img src="{outside.as_posix()}">',
        '<img src="../fora.png">',
        '<img src="%2e%2e/fora.png">',
        '<img src="figuras/../../fora.png">',
        '<img src="\\\\servidor\\pasta\\a.png">',
        '<img src="//servidor/pasta/a.png">',
        f'<img src="file:///{outside.as_posix()}">',
        '<img src="C:\\Users\\x\\a.png">',
        '<img src="segredo.txt">',
        '<img src="data:image/svg+xml;base64,PHN2Zy8+">',
        '<img alt="sem endereço">',
    ]
    for tag in blocked:
        assert convert._safe_images(f"<p>a</p>{tag}<p>b</p>", doc) == "<p>a</p><p>b</p>", tag
    assert convert._safe_images('<img src="ok.png">', None) == "", "sem pasta de origem, nenhum arquivo entra"
    kept = convert._safe_images(f'<img src="ok.png"><img width="10" src="figuras/dentro.png"><img src="{data}">', doc)
    assert kept.count("<img") == 3
    assert (doc / "ok.png").resolve().as_posix() in kept and (doc / "figuras" / "dentro.png").resolve().as_posix() in kept
    assert data in kept


def test_html_conversion_does_not_touch_the_network(tmp_path, monkeypatch):
    """Conversão completa: as imagens da pasta entram no PDF; nenhuma conexão é sequer tentada."""
    import socket

    import pikepdf

    import convert
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("rede")))
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("rede")))
    doc = tmp_path / "doc"
    doc.mkdir()
    _png(doc / "ok.png")
    _png(tmp_path / "fora.png", "blue")
    html = ('<html><body><h1>Título</h1><p>texto</p><img src="ok.png">'
            '<img src="http://exemplo.com/a.png"><img src="../fora.png"></body></html>')
    dest = tmp_path / "saida.pdf"
    convert.html_to_pdf(html, dest, base=doc)
    assert calls == [], f"a conversão tentou usar a rede: {calls}"
    with pikepdf.open(dest) as pdf:
        assert sum(len(list(p.images)) for p in pdf.pages) == 1


def test_fpdf_is_told_not_to_fetch_remote_resources():
    import convert
    pdf, _family = convert._new_pdf("t")
    convert._no_network(pdf)
    try:
        from fpdf.enums import ResourceAccessPolicy
    except ImportError:
        pytest.skip("fpdf2 sem política de acesso")
    assert pdf.resource_access_policy == ResourceAccessPolicy.LOCAL_FILES


# --- library.json ---------------------------------------------------------------------------------------

def test_valid_id():
    from library import valid_id
    assert valid_id("1256460F-D8CD-4078-A71F-CB50D16A26FE") and valid_id("a1") and valid_id("id_2-x")
    for bad in ("", None, 7, "../x", "a/b", "a\\b", "a.b", "C:x", "-começa", "x" * 65, "a b", "a\nb"):
        assert not valid_id(bad), repr(bad)


def test_library_json_id_cannot_leave_the_prumo_folders(tmp_path):
    from library import Library
    root, local, target = tmp_path / "lib", tmp_path / "local", tmp_path / "alvo"
    (root / ".prumo").mkdir(parents=True)
    target.mkdir()
    digital_pdf(root / "contrato.pdf")
    digital_pdf(root / "outro.pdf")
    victim_txt = target / "importante.txt"
    victim_txt.write_text("conteudo original", encoding="utf-8")
    victim_pdf = target / "importante.pdf"
    victim_pdf.write_bytes(b"%PDF original")
    # como chegaria de uma pasta de nuvem compartilhada ou de uma biblioteca recebida de outra pessoa
    rel = os.path.relpath(target / "importante", local / "Text")
    (root / ".prumo" / "library.json").write_text(json.dumps([
        {"path": "contrato.pdf", "id": rel, "favorite": True},
        {"path": "contrato.pdf", "id": rel.replace(os.sep, "/")},
        {"path": "outro.pdf", "id": "ABC-123", "favorite": True, "ocr_copy_id": "../../x", "source_id": "ok_1"},
        {"path": 5, "id": "ABC-124"}, "lixo", {"id": "ABC-125"},
    ]), encoding="utf-8")
    lib = Library(root, local_dir=local)
    by_name = {it.rel: it for it in lib.items}
    it = by_name["contrato.pdf"]
    assert it.id != rel and "/" not in it.id and "\\" not in it.id and ".." not in it.id
    assert by_name["outro.pdf"].id == "ABC-123" and by_name["outro.pdf"].meta.favorite
    assert by_name["outro.pdf"].meta.ocr_copy_id is None and by_name["outro.pdf"].meta.source_id == "ok_1"
    lib.apply_analysis(it.id, "sig", {"text": "texto do pdf", "page_count": 1})
    lib.modify(it, lambda p: None)
    lib.purge_local(it.id, it.path)
    assert victim_txt.read_text(encoding="utf-8") == "conteudo original"
    assert victim_pdf.read_bytes() == b"%PDF original"
    saved = json.loads((root / ".prumo" / "library.json").read_text(encoding="utf-8"))
    assert all(isinstance(d.get("id"), str) and "/" not in d["id"] and "\\" not in d["id"] for d in saved)


# --- análise ----------------------------------------------------------------------------------------------

def _text_pdf(path: Path, pages: int) -> Path:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)
    for n in range(pages):
        pdf.add_page()
        pdf.multi_cell(0, 5, f"pagina {n + 1} " + "processo autos sentenca recurso laudo " * 40)
    pdf.output(str(path))
    return path


def test_analysis_reads_text_once_and_matches_extract_text(tmp_path, monkeypatch):
    import core
    from library import Library
    path = _text_pdf(tmp_path / "a.pdf", 6)
    info = core.analyze_pdf(path, with_text=True)
    assert info.texts == core.extract_text(path) and len(info.texts) == 6
    assert core.analyze_pdf(path).texts is None
    plain = core.analyze_pdf(path)
    assert [(p.number, p.chars, p.kind) for p in plain.pages] == [(p.number, p.chars, p.kind) for p in info.pages]
    expected = "\n".join(core.extract_text(path))
    monkeypatch.setattr(core, "extract_text", lambda *_a, **_k: pytest.fail("o PDF foi lido uma segunda vez"))
    res = Library.analyze(path)
    assert res["text"] == expected and res["page_count"] == 6


def test_analysis_lets_the_reader_in_between_pages(tmp_path):
    """Enquanto um PDF grande é analisado, outra linha de execução consegue o PDFium sem esperar o documento todo."""
    import core
    path = _text_pdf(tmp_path / "grande.pdf", 300)
    t0 = time.perf_counter()
    core.analyze_pdf(path, with_text=True)
    whole = time.perf_counter() - t0
    waits, done = [], threading.Event()

    def reader():
        while not done.is_set():
            t = time.perf_counter()
            with core.PDFIUM_LOCK:
                pass
            waits.append(time.perf_counter() - t)
            time.sleep(0.002)

    th = threading.Thread(target=reader)
    th.start()
    try:
        core.analyze_pdf(path, with_text=True)
    finally:
        done.set()
        th.join()
    assert len(waits) >= 5, f"o leitor só conseguiu o PDFium {len(waits)} vezes durante a análise"
    assert max(waits) < max(0.5, whole / 2), f"espera máxima {max(waits):.2f}s numa análise de {whole:.2f}s"


# --- senha do Prumo ---------------------------------------------------------------------------------------

def test_app_password_rounds_and_old_hashes():
    import security
    new = security.hash_password("segredo")
    assert new.split("$")[1] == "600000"
    assert security.verify_password("segredo", new) and not security.verify_password("outra", new)
    old = security.hash_password("segredo", iterations=200_000)
    assert security.verify_password("segredo", old), "senha criada numa versão anterior continua valendo"


# --- restauração de .zip ------------------------------------------------------------------------------------

def test_zip_restore_opens_only_pdfs_and_the_library_record(tmp_path):
    import zipfile

    import backup
    z = tmp_path / "copia.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Prumo PDF/a.pdf", b"%PDF-1.4 a")
        f.writestr("Prumo PDF/pasta/b.PDF", b"%PDF-1.4 b")
        f.writestr("Prumo PDF/.prumo/library.json", "[]")
        f.writestr("Prumo PDF/enorme.bin", b"0" * 100_000)
        f.writestr("Prumo PDF/programa.exe", b"MZ")
        f.writestr("../fora.pdf", b"%PDF-1.4 fora")
    out = backup._extract_zip(z)
    try:
        names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        assert names == ["Prumo PDF/.prumo/library.json", "Prumo PDF/a.pdf", "Prumo PDF/pasta/b.PDF"]
        assert not (tmp_path / "fora.pdf").exists() and not (out.parent / "fora.pdf").exists()
    finally:
        shutil.rmtree(out, ignore_errors=True)
