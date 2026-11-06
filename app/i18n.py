"""
Idioma da interface. O texto-fonte do programa está em português; cada idioma tem um catálogo
`locales/<código>.json` com {"texto em português": "tradução"}. Textos com parte variável usam `{}`
("Alterado em {}"). Todo idioma tem todos os textos: o teste tests/test_i18n.py falha se faltar algum.

Como o texto chega traduzido à tela:
- `install_hooks()` faz os pontos de entrada de texto do Qt passarem por `tr` (rótulos, botões, dicas,
  menus, listas, abas, diálogos do sistema, texto pintado, medida de texto). Assim um `QLabel("Abrir")`
  já aparece traduzido.
- Texto com parte variável é montado com `trf("Página {} de {}", n, total)` (traduz o modelo e depois
  preenche); singular/plural com `trn(n, "1 página", "{} páginas")`. Nunca montar frase com pedaços
  ("PDF" + "s"), porque a ordem e o plural mudam de uma língua para outra.
- Nome de arquivo, de pasta e texto do PDF são do usuário: `raw(nome)` marca o texto para não ser traduzido
  (um PDF chamado "Favoritos" continua "Favoritos").
- Os textos do próprio Qt (menu do botão direito num campo de texto, botões padrão) vêm das traduções do Qt
  (`qtbase_<idioma>.qm`), carregadas por `install_qt_translator`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

LANGUAGES: list[tuple[str, str]] = [
    ("pt", "Português"),
    ("en", "English"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("ja", "日本語"),
    ("zh-CN", "中文 (简体)"),
    ("zh-TW", "中文 (繁體, 台灣)"),
    ("nb", "Norsk bokmål"),
    ("sv", "Svenska"),
    ("da", "Dansk"),
    ("fi", "Suomi"),
]
CODES = [c for c, _ in LANGUAGES]
# Idiomas cuja tradução ainda pede revisão por quem fala a língua.
NEEDS_REVIEW: set[str] = set()


class Raw(str):
    """Texto do usuário (nome de arquivo, de pasta, texto do PDF): passa pelo Qt sem tradução."""
    __slots__ = ()


def raw(text):
    return Raw(text) if isinstance(text, str) and not isinstance(text, Raw) else text


def _locales_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "locales"
    return Path(__file__).resolve().parent / "locales"


_dir = _locales_dir()
_lang = "pt"
_exact: dict[str, str] = {}
_patterns: list[tuple[re.Pattern, str]] = []
_cache: dict[str, str] = {}


_catalogs: dict[str, dict[str, str]] = {}


def load_catalog(code: str) -> dict[str, str]:
    if code not in _catalogs:
        f = _dir / f"{code}.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            _catalogs[code] = {k: v for k, v in data.items() if isinstance(v, str) and v}
        except Exception:
            _catalogs[code] = {}
    return _catalogs[code]


def _compile(cat: dict[str, str]):
    pats = []
    for k, v in cat.items():
        # Só modelos com palavras de verdade: "{} de {}" casaria com qualquer frase ("Contrato de aluguel").
        if "{}" in k and len(re.findall(r"[^\W\d_]", k.replace("{}", ""))) >= 5 \
                and re.search(r"[^\W\d_]{4}", k.replace("{}", "")):
            rx = "^" + "(.+?)".join(re.escape(p) for p in k.split("{}")) + "$"
            pats.append((re.compile(rx, re.S), v))
    pats.sort(key=lambda p: -len(p[0].pattern))
    return pats


def _fill(template: str, groups) -> str:
    out = template
    for g in groups:
        out = out.replace("{}", str(g), 1)
    return out


def system_language() -> str:
    """Idioma do Windows, entre os que o programa tem; senão inglês."""
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name()              # ex.: pt_BR, zh_TW, nb_NO, se_NO
        lang = name.split("_")[0].lower()
    except Exception:
        return "en"
    if lang == "zh":
        return "zh-TW" if name.upper().endswith(("TW", "HK", "MO")) or "Hant" in name else "zh-CN"
    if lang in ("no", "nn"):
        return "nb"
    return lang if lang in CODES else "en"


def resolve(setting: str | None) -> str:
    return system_language() if setting in (None, "", "auto") else (setting if setting in CODES else "en")


def set_language(setting: str | None) -> str:
    global _lang, _exact, _patterns
    _lang = resolve(setting)
    _cache.clear()
    if _lang == "pt":
        _exact, _patterns = {}, []
    else:
        # Rede de segurança: o que faltar no idioma aparece em inglês (o teste exige que nada falte).
        _exact = {**(load_catalog("en") if _lang != "en" else {}), **load_catalog(_lang)}
        _patterns = _compile(_exact)
    try:
        from PySide6.QtCore import QLocale
        QLocale.setDefault(qlocale())
    except Exception:
        pass
    return _lang


def current() -> str:
    return _lang


def _lookup(text: str) -> str:
    if text in _exact:
        return _exact[text]
    for rx, tpl in _patterns:
        m = rx.match(text)
        if m:
            # As partes variáveis também podem ser texto da interface ("Movido para Sem pasta.").
            return _fill(tpl, [tr(g) for g in m.groups()])
    return text


def tr(text):
    """Traduz um texto da interface. Aceita qualquer valor; só mexe em `str` que não seja `Raw`."""
    if _lang == "pt" or not isinstance(text, str) or isinstance(text, Raw):
        return text
    hit = _cache.get(text)
    if hit is not None:
        return hit
    core = text.strip()
    if len(core) < 2:
        return text
    if core != text:                                # espaços em volta ("  Favoritar") ficam como estão
        start = text.index(core)
        hit = text[:start] + tr(core) + text[start + len(core):]
    elif "\n" in text and text not in _exact:
        hit = "\n".join(_lookup(part) if part.strip() else part for part in text.split("\n"))
    else:
        hit = _lookup(text)
    if len(_cache) > 6000:
        _cache.clear()
    _cache[text] = hit
    return hit


def trf(template: str, *args) -> str:
    """Traduz o modelo ("Página {} de {}") e preenche as partes variáveis na ordem."""
    t = template if _lang == "pt" else _exact.get(template, template)
    return _fill(t, args)


def trn(n: int, one: str, other: str, *args) -> str:
    """Singular ou plural: trn(3, "1 página", "{} páginas") → "3 pages". O número entra no primeiro {}."""
    if n == 1:
        t = one if _lang == "pt" else _exact.get(one, one)
        return _fill(t, args) if "{}" in t else t
    return trf(other, n, *args)


# Texto gravado dentro do PDF (carimbo da assinatura, resumo) usa fontes PDF sem japonês e chinês:
# nesses idiomas o texto do documento sai em inglês.
DOC_LANGS = ("pt", "en", "es", "fr", "de", "nb", "sv", "da", "fi")


def doc_language() -> str:
    return _lang if _lang in DOC_LANGS else "en"


def tr_in(code: str, text: str) -> str:
    """Tradução para um idioma específico (sem os ganchos e sem o idioma atual)."""
    if code == "pt":
        return text
    return load_catalog(code).get(text) or load_catalog("en").get(text) or text


def trf_in(code: str, template: str, *args) -> str:
    return _fill(tr_in(code, template), args)


_all_cache: dict[str, list[str]] = {}


def all_translations(text: str) -> list[str]:
    """O texto em português e em todos os idiomas (para reconhecer nomes criados em outro idioma)."""
    if text not in _all_cache:
        out = [text]
        for code in CODES[1:]:
            v = load_catalog(code).get(text)
            if v and v not in out:
                out.append(v)
        _all_cache[text] = out
    return _all_cache[text]


def strip_suffix(name: str, template: str) -> str:
    """Tira de um nome o sufixo de `template` ("{} - protegido") em qualquer idioma; senão devolve o nome."""
    for t in all_translations(template):
        if t.startswith("{}"):
            suffix = t[2:]
            if suffix and name.endswith(suffix) and len(name) > len(suffix):
                return type(name)(name[:-len(suffix)]) if isinstance(name, Raw) else name[:-len(suffix)]
    return name


def suffixed_names(base: str, template: str) -> list[str]:
    """O nome com o sufixo em cada idioma, começando pelo idioma atual (para achar um resumo, por exemplo)."""
    first = trf(template, base)
    return [first] + [_fill(t, (base,)) for t in all_translations(template) if _fill(t, (base,)) != first]


# --- datas e números no formato do idioma ----------------------------------------

_QT_LOCALE = {"pt": "pt_BR", "en": "en_US", "es": "es_ES", "fr": "fr_FR", "de": "de_DE", "ja": "ja_JP",
              "zh-CN": "zh_CN", "zh-TW": "zh_TW", "nb": "nb_NO", "sv": "sv_SE", "da": "da_DK", "fi": "fi_FI"}
_DATE_FMT = {"pt": "dd/MM/yyyy", "en": "MMM d, yyyy", "es": "dd/MM/yyyy", "fr": "dd/MM/yyyy",
             "de": "dd.MM.yyyy", "ja": "yyyy/MM/dd", "zh-CN": "yyyy/MM/dd", "zh-TW": "yyyy/MM/dd",
             "nb": "dd.MM.yyyy", "sv": "yyyy-MM-dd", "da": "dd.MM.yyyy", "fi": "d.M.yyyy"}
_TIME_FMT = {"en": "h:mm AP"}


def qlocale():
    from PySide6.QtCore import QLocale
    return QLocale(_QT_LOCALE.get(_lang, "en_US"))


def _qdt(ts):
    from PySide6.QtCore import QDateTime
    if hasattr(ts, "timestamp"):                    # datetime
        ts = ts.timestamp()
    return QDateTime.fromSecsSinceEpoch(int(ts if ts is not None else time.time()))


def fmt_date(ts=None) -> str:
    """Data no formato do idioma (06/11/2026, Nov 6, 2026, 06.11.2026, 2026/11/06...)."""
    return qlocale().toString(_qdt(ts), _DATE_FMT.get(_lang, "yyyy-MM-dd"))


def fmt_time(ts=None) -> str:
    return qlocale().toString(_qdt(ts), _TIME_FMT.get(_lang, "HH:mm"))


def fmt_datetime(ts=None) -> str:
    return f"{fmt_date(ts)}, {fmt_time(ts)}"


def fmt_number(x, decimals: int = 0) -> str:
    return qlocale().toString(float(x), "f", decimals) if decimals else qlocale().toString(int(x))


# --- ganchos no Qt --------------------------------------------------------------

_installed = False
_orig_draw_text = None


def draw_raw(painter, *a):
    """drawText sem tradução (para texto do usuário que não vem marcado com raw)."""
    return (_orig_draw_text or type(painter).drawText)(painter, *a)


def _tr_filter(flt):
    """Filtro de arquivos ("Imagens (*.png *.jpg);;PDF (*.pdf)"): traduz só o nome de cada tipo."""
    if not isinstance(flt, str) or _lang == "pt":
        return flt
    parts = []
    for part in flt.split(";;"):
        i = part.rfind(" (")
        parts.append(tr(part[:i]) + part[i:] if i > 0 else tr(part))
    return ";;".join(parts)


def install_hooks() -> None:
    """Faz os pontos de entrada de texto do Qt passarem por `tr`. Chamar uma vez, depois de set_language."""
    global _installed, _orig_draw_text
    if _installed:
        return
    _installed = True
    from PySide6.QtGui import QAction, QFontMetrics, QFontMetricsF, QPainter, QStandardItem
    from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                                   QGroupBox, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                                   QMenu, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                                   QRadioButton, QSpinBox, QTabBar, QTableWidgetItem, QTabWidget, QTextEdit,
                                   QTreeWidgetItem, QWidget)

    def tr_at(a, positions):
        """Traduz o primeiro texto entre as posições dadas (o texto pode vir depois de um ícone)."""
        for i in positions:
            if len(a) > i and isinstance(a[i], str):
                return a[:i] + (tr(a[i]),) + a[i + 1:]
        return a

    def wrap(cls, name, positions=(0,), kw=()):
        orig = getattr(cls, name)

        def f(self, *a, **k):
            a = tr_at(a, positions)
            for key in kw:
                if isinstance(k.get(key), str):
                    k[key] = tr(k[key])
            return orig(self, *a, **k)
        f.__name__ = name
        setattr(cls, name, f)

    # Texto de widgets
    for cls, name in ((QLabel, "setText"), (QAbstractButton, "setText"), (QWidget, "setToolTip"),
                      (QWidget, "setWindowTitle"), (QWidget, "setStatusTip"), (QWidget, "setAccessibleName"),
                      (QWidget, "setAccessibleDescription"), (QWidget, "setWhatsThis"),
                      (QLineEdit, "setPlaceholderText"), (QTextEdit, "setPlaceholderText"),
                      (QPlainTextEdit, "setPlaceholderText"), (QGroupBox, "setTitle"),
                      (QAction, "setText"), (QAction, "setToolTip"), (QAction, "setIconText"),
                      (QAction, "setStatusTip"), (QMenu, "setTitle"), (QMenu, "addSection"),
                      (QMessageBox, "setText"), (QMessageBox, "setInformativeText"),
                      (QMessageBox, "setDetailedText"), (QProgressDialog, "setLabelText"),
                      (QProgressDialog, "setCancelButtonText"), (QListWidgetItem, "setText"),
                      (QListWidgetItem, "setToolTip"), (QTableWidgetItem, "setText"),
                      (QTableWidgetItem, "setToolTip"), (QStandardItem, "setText"),
                      (QStandardItem, "setToolTip"),
                      (QSpinBox, "setSuffix"), (QSpinBox, "setPrefix"), (QSpinBox, "setSpecialValueText"),
                      (QDoubleSpinBox, "setSuffix"), (QDoubleSpinBox, "setPrefix"),
                      (QDoubleSpinBox, "setSpecialValueText")):
        wrap(cls, name)
    for cls, name in ((QComboBox, "setItemText"), (QTabBar, "setTabText"), (QTabBar, "setTabToolTip"),
                      (QTabWidget, "setTabText"), (QTabWidget, "setTabToolTip"),
                      (QTreeWidgetItem, "setText"), (QTreeWidgetItem, "setToolTip")):
        wrap(cls, name, (1,))
    wrap(QComboBox, "addItem", (0, 1))              # addItem(text, data) ou addItem(icon, text, data)
    wrap(QComboBox, "insertItem", (1, 2))
    wrap(QTabWidget, "addTab", (1, 2))              # addTab(w, text) ou addTab(w, icon, text)
    wrap(QTabWidget, "insertTab", (2, 3))
    wrap(QTabBar, "addTab", (0, 1))
    wrap(QListWidget, "addItem", (0,))
    wrap(QMenu, "addAction", (0, 1))                # addAction(text, ...) ou addAction(icon, text, ...)
    wrap(QMenu, "addMenu", (0, 1))

    for cls, name in ((QComboBox, "addItems"), (QListWidget, "addItems")):
        orig_items = getattr(cls, name)

        def items(self, texts, __o=orig_items):
            return __o(self, [tr(t) for t in texts])
        setattr(cls, name, items)

    # Construtores com texto: QLabel("..."), QPushButton("..."), QAction(icon, "...", parent) etc.
    for cls, positions in ((QLabel, (0,)), (QPushButton, (0, 1)), (QCheckBox, (0,)), (QRadioButton, (0,)),
                           (QGroupBox, (0,)), (QAction, (0, 1)), (QMenu, (0,)), (QListWidgetItem, (0, 1)),
                           (QTableWidgetItem, (0, 1)), (QStandardItem, (0, 1))):
        orig_init = cls.__init__

        def init(self, *a, __o=orig_init, __p=positions, **k):
            __o(self, *tr_at(a, __p), **k)
        cls.__init__ = init

    orig_tree = QTreeWidgetItem.__init__

    def tree_init(self, *a, **k):
        a = tuple([tr(s) for s in x] if isinstance(x, (list, tuple)) and x and isinstance(x[0], str) else x
                  for x in a)
        orig_tree(self, *a, **k)
    QTreeWidgetItem.__init__ = tree_init

    # Texto pintado e medido (cartões e botões desenhados pelo próprio Prumo)
    _orig_draw_text = QPainter.drawText

    def draw_text(self, *a, **k):
        return _orig_draw_text(self, *(tr(x) if isinstance(x, str) else x for x in a), **k)
    QPainter.drawText = draw_text

    for cls in (QFontMetrics, QFontMetricsF):
        for name in ("horizontalAdvance", "elidedText", "boundingRect", "tightBoundingRect", "size"):
            if not hasattr(cls, name):
                continue
            orig_m = getattr(cls, name)

            def measured(self, *a, __o=orig_m, **k):
                return __o(self, *(tr(x) if isinstance(x, str) else x for x in a), **k)
            setattr(cls, name, measured)

    # Diálogos do sistema chamados direto (título, texto e filtro de arquivos)
    def static(cls, name, positions, filter_pos=None, kw=("caption", "title", "text", "label")):
        orig = getattr(cls, name)

        def f(*a, **k):
            a = list(a)
            for i in positions:
                if len(a) > i and isinstance(a[i], str):
                    a[i] = tr(a[i])
            if filter_pos is not None and len(a) > filter_pos:
                a[filter_pos] = _tr_filter(a[filter_pos])
            for key in kw:
                if isinstance(k.get(key), str):
                    k[key] = tr(k[key])
            if "filter" in k:
                k["filter"] = _tr_filter(k["filter"])
            return orig(*a, **k)
        setattr(cls, name, staticmethod(f))

    for name in ("question", "information", "warning", "critical", "about"):
        static(QMessageBox, name, (1, 2))
    for name in ("getOpenFileName", "getOpenFileNames", "getSaveFileName"):
        static(QFileDialog, name, (1,), filter_pos=3)
    static(QFileDialog, "getExistingDirectory", (1,))
    for name in ("getText", "getInt", "getDouble", "getItem", "getMultiLineText"):
        static(QInputDialog, name, (1, 2))


_translator = None


def install_qt_translator(app) -> bool:
    """Carrega as traduções do próprio Qt (menu do botão direito em campos de texto, botões padrão)."""
    global _translator
    import sys
    from PySide6.QtCore import QLibraryInfo, QTranslator
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None
    if _lang == "en":
        return True
    # Não há qtbase em norueguês bokmål; o nynorsk é o mais próximo que o Qt traz.
    name = {"pt": "pt_BR", "zh-CN": "zh_CN", "zh-TW": "zh_TW", "nb": "nn"}.get(_lang, _lang)
    dirs = [QLibraryInfo.path(QLibraryInfo.TranslationsPath)]
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    dirs += [str(base / "PySide6" / "translations"), str(base / "PySide6" / "Qt" / "translations")]
    t = QTranslator(app)
    for d in dirs:
        if d and t.load(f"qtbase_{name}", d):
            app.installTranslator(t)
            _translator = t
            return True
    return False


def language_label(setting: str | None) -> str:
    return dict(LANGUAGES).get(resolve(setting), "English")
