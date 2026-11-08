"""
Textos da interface que precisam de tradução: lê o código de app/ (árvore sintática do Python) e lista os
textos em português que aparecem para o usuário. Usado pelo teste tests/test_i18n.py e para manter os
catálogos app/locales/<idioma>.json.

    python tools/i18n_strings.py            # quantos textos faltam em cada idioma
    python tools/i18n_strings.py --missing  # grava tools/i18n_missing.json com o que falta (para traduzir)

Regras:
- Entra todo texto que parece frase ou rótulo (tem espaço e letras minúsculas, ou é uma palavra com inicial
  maiúscula, ou tem acento), e todo texto passado direto para tr/trf/trn/tr_in/trf_in.
- Um f-string vira modelo com {} ("Página {} de {}").
- Ficam de fora: docstrings, chaves de dicionário, estilos (CSS), expressões regulares, caminhos, desenhos SVG,
  nomes de configuração e os arquivos/funções do modo clássico (escondido, só por linha de comando).
- O que ainda assim não é texto da interface fica em tools/i18n_ignore.txt (um por linha).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
LOCALES = APP / "locales"
IGNORE_FILE = Path(__file__).resolve().parent / "i18n_ignore.txt"

# Modo clássico (antigo, só por "--classico") e dados de demonstração: fora da tradução.
SKIP_FILES = {"demo.py", "page_ocr.py", "page_merge.py", "page_extract.py", "ui_common.py", "i18n.py",
              "ios_theme.py", "machine.py", "ocr_plugin.py", "ocr_runner.py",
              # chamadas ao Windows (nomes de propriedades, comandos e detalhes técnicos dos erros, em inglês)
              "wincert.py", "protection.py", "winsys.py"}
SKIP_FUNCS = {("main.py", "run_classic"), ("main.py", "self_test"), ("main.py", "run_gui"),
              ("main.py", "_server_name"), ("ocr_worker.py", "_write_txt")}
TR_FUNCS = {"tr", "trf", "trn", "tr_in", "trf_in"}
# Chamadas cujo texto não é da interface
NON_UI_CALLS = {"setObjectName", "setStyleSheet", "value", "setValue", "setting", "set_setting", "QSettings",
                "compile", "sub", "match", "search", "fullmatch", "split", "findall", "getattr", "hasattr",
                "setattr", "get", "pop", "setdefault", "startswith", "endswith", "strftime", "strptime",
                "environ", "getenv", "Path", "with_suffix", "with_name", "joinpath", "glob", "rglob",
                "add_font", "set_font", "QFont", "QColor", "QKeySequence", "fromTheme", "encode", "decode",
                "glyph_icon", "paint_glyph", "paint_tile_icon", "T.color", "color", "hex", "Signal",
                "connect_alive", "run", "Popen", "check_output", "replace", "index", "count", "rfind", "find",
                "SetCurrentProcessExplicitAppUserModelID", "CreateMutexW", "QLocalServer", "QLocalSocket",
                "listen", "connectToServer", "mkdtemp", "NamedTemporaryFile", "mimeData", "hasFormat", "format",
                "lstrip", "rstrip", "strip", "join", "QIcon", "QPixmap", "load", "addTranslator", "print"}


# Textos usados de forma indireta (o nome de cada tipo num filtro de arquivos: i18n._tr_filter traduz por partes)
EXTRA = ["PDF e arquivos para converter", "Imagens", "Word, Excel e PowerPoint", "Texto e HTML",
         "Certificado A1", "Todos os arquivos", "Erro desconhecido."]


def _looks_ui(s: str) -> bool:
    t = s.strip()
    if len(t) < 2 or not re.search(r"[^\W\d_]{2}", t):
        return False
    if t.startswith(("<", "#", "%", "http", "ms-settings", "(?", "^", "*.", "--", "-env")):
        return False
    if "{{" in t or re.search(r"[{;]\s*$", t) and ":" in t:             # CSS
        return False
    if re.search(r"\\[dswbSWD]|\(\?|\[\^", t):                            # expressão regular
        return False
    if "\n$" in t or t.startswith("$"):                                    # PowerShell
        return False
    if re.fullmatch(r"[A-Za-z0-9_.\-/\\:+*$]+", t):                        # identificador, caminho, atalho
        # palavra única com inicial maiúscula e o resto minúsculo é rótulo ("Abrir", "Pastas")
        return bool(re.fullmatch(r"[A-ZÀ-Ý][a-zà-ÿ]{2,}[.…]?", t)) and t not in {"Prumo", "Microsoft", "Text",
                                                                                 "Thumbs", "Versions", "Fusion",
                                                                                 "Documents", "Desktop", "Programs",
                                                                                 "Courier", "Helvetica", "Mono",
                                                                                 "Inter", "Bypass"}
    if re.search(r"[À-ÿ]", t):
        return True
    return bool(re.search(r"[a-z]{2,}", t)) and (" " in t or t[:1].isupper() or "{}" in t)


def _template(node: ast.JoinedStr) -> str:
    out = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        else:
            out.append("{}")
    return "".join(out)


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def extract() -> dict[str, list[str]]:
    """{texto: [arquivo:linha, ...]}"""
    found: dict[str, list[str]] = {}
    for path in sorted(APP.glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))

        def context(node):
            """(funções em volta, chamada direta que recebe o texto, se é chave de dicionário, se é comparação)"""
            func, call, is_key, compared = [], None, False, False
            child, cur = node, parents.get(id(node))
            first = True
            while cur is not None:
                if isinstance(cur, ast.Dict) and child in cur.keys:
                    is_key = True
                if isinstance(cur, ast.Compare) and first:
                    compared = True
                if isinstance(cur, ast.Subscript) and child is cur.slice:
                    is_key = True
                if isinstance(cur, ast.Call) and call is None and child is not cur.func:
                    call = _call_name(cur)
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func.append(cur.name)
                if not isinstance(cur, (ast.BinOp, ast.IfExp, ast.BoolOp, ast.Tuple, ast.List, ast.JoinedStr,
                                        ast.FormattedValue)):
                    first = False
                child, cur = cur, parents.get(id(cur))
            return func, call, is_key, compared

        inner = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    inner.add(id(v))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings or id(node) in inner:
                    continue
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                text = _template(node)
            else:
                continue
            func, call, is_key, compared = context(node)
            if any((path.name, f) in SKIP_FUNCS for f in func):
                continue
            direct_tr = call in TR_FUNCS
            if not direct_tr:
                if is_key or compared or call in NON_UI_CALLS or not _looks_ui(text):
                    continue
            if not text.strip() or not re.search(r"[^\W\d_]", text):
                continue
            found.setdefault(text.strip() if direct_tr else text, []).append(f"{path.name}:{node.lineno}")
    for text in EXTRA:
        found.setdefault(text, []).append("tools/i18n_strings.py:EXTRA")
    ignore = load_ignore()
    out = {}
    for k, v in found.items():
        key = k.strip()
        if key in ignore or not key:
            continue
        out.setdefault(key, []).extend(v)
    return out


def load_ignore() -> set[str]:
    if not IGNORE_FILE.exists():
        return set()
    return {ln.rstrip("\n") for ln in IGNORE_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("# ")}


def load_catalogs() -> dict[str, dict[str, str]]:
    sys.path.insert(0, str(APP))
    import i18n
    return {code: json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8")) for code in i18n.CODES[1:]}


def main() -> int:
    strings = extract()
    cats = load_catalogs()
    print(f"{len(strings)} textos da interface")
    missing = {code: sorted(s for s in strings if s not in cat) for code, cat in cats.items()}
    for code, m in missing.items():
        print(f"  {code}: faltam {len(m)}")
    if "--missing" in sys.argv:
        out = Path(__file__).resolve().parent / "i18n_missing.json"
        union = sorted({s for m in missing.values() for s in m})
        out.write_text(json.dumps({s: strings[s][:3] for s in union}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"gravado {out} ({len(union)} textos)")
    if "--unused" in sys.argv:
        for code, cat in cats.items():
            unused = sorted(k for k in cat if k not in strings)
            print(f"  {code}: {len(unused)} sem uso")
    return 0 if not any(missing.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
