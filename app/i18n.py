"""
Idioma da interface. O texto-fonte do programa está em português; cada idioma tem um catálogo
`locales/<código>.json` com {"texto em português": "tradução"}. Textos com parte variável usam `{}`
("Alterado em {}"). O que não tiver tradução aparece em inglês e, se também não houver, em português.

A tradução é aplicada nos pontos de entrada do Qt (rótulos, botões, dicas, itens de lista, texto pintado),
então a interface inteira muda sem trocar cada chamada.
"""

from __future__ import annotations

import json
import re
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
    ("se", "Davvisámegiella"),
    ("sv", "Svenska"),
    ("da", "Dansk"),
    ("fi", "Suomi"),
]
CODES = [c for c, _ in LANGUAGES]
# Idiomas cuja tradução ainda pede revisão por quem fala a língua.
NEEDS_REVIEW = {"se"}

def _locales_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "locales"
    return Path(__file__).resolve().parent / "locales"


_dir = _locales_dir()
_lang = "pt"
_exact: dict[str, str] = {}
_exact_en: dict[str, str] = {}
_patterns: list[tuple[re.Pattern, str]] = []
_patterns_en: list[tuple[re.Pattern, str]] = []
_cache: dict[str, str] = {}


def _load(code: str) -> dict[str, str]:
    f = _dir / f"{code}.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except Exception:
        return {}


def _compile(cat: dict[str, str]):
    pats = []
    for k, v in cat.items():
        if "{}" in k:
            rx = "^" + "(.+?)".join(re.escape(p) for p in k.split("{}")) + "$"
            pats.append((re.compile(rx, re.S), v))
    pats.sort(key=lambda p: -len(p[0].pattern))
    return pats


def _fill(template: str, groups: tuple[str, ...]) -> str:
    out = template
    for g in groups:
        out = out.replace("{}", g, 1)
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
    if lang in ("sme", "smi"):
        return "se"
    return lang if lang in CODES else "en"


def resolve(setting: str | None) -> str:
    return system_language() if setting in (None, "", "auto") else (setting if setting in CODES else "en")


def set_language(setting: str | None) -> str:
    global _lang, _exact, _exact_en, _patterns, _patterns_en
    _lang = resolve(setting)
    _cache.clear()
    if _lang == "pt":
        _exact, _exact_en, _patterns, _patterns_en = {}, {}, [], []
        return _lang
    _exact = _load(_lang)
    _patterns = _compile(_exact)
    if _lang != "en":
        _exact_en = _load("en")
        _patterns_en = _compile(_exact_en)
    else:
        _exact_en, _patterns_en = {}, []
    return _lang


def current() -> str:
    return _lang


def _lookup(text: str) -> str:
    for exact, pats in ((_exact, _patterns), (_exact_en, _patterns_en)):
        if text in exact:
            return exact[text]
        for rx, tpl in pats:
            m = rx.match(text)
            if m:
                return _fill(tpl, m.groups())
    return text


def tr(text):
    """Traduz um texto da interface. Aceita qualquer valor; só mexe em `str`."""
    if _lang == "pt" or not isinstance(text, str) or len(text) < 2:
        return text
    hit = _cache.get(text)
    if hit is None:
        if "\n" in text and text not in _exact and text not in _exact_en:
            hit = "\n".join(_lookup(part) if part.strip() else part for part in text.split("\n"))
        else:
            hit = _lookup(text)
        if len(_cache) > 4000:
            _cache.clear()
        _cache[text] = hit
    return hit


# --- ganchos no Qt --------------------------------------------------------------

_installed = False


def install_hooks() -> None:
    """Faz os pontos de entrada de texto do Qt passarem por `tr`. Chamar uma vez, depois de set_language."""
    global _installed
    if _installed:
        return
    _installed = True
    from PySide6.QtGui import QAction, QPainter
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QMenu,
                                   QMessageBox, QTabBar, QWidget)

    def wrap(cls, name, index_of_text=0):
        orig = getattr(cls, name)

        def f(self, *a, **k):
            if len(a) > index_of_text and isinstance(a[index_of_text], str):
                a = a[:index_of_text] + (tr(a[index_of_text]),) + a[index_of_text + 1:]
            return orig(self, *a, **k)
        f.__name__ = name
        setattr(cls, name, f)

    wrap(QLabel, "setText")
    wrap(QAbstractButton, "setText")
    wrap(QWidget, "setToolTip")
    wrap(QWidget, "setWindowTitle")
    wrap(QWidget, "setStatusTip")
    wrap(QLineEdit, "setPlaceholderText")
    wrap(QGroupBox, "setTitle")
    wrap(QAction, "setText")
    wrap(QAction, "setToolTip")
    wrap(QMessageBox, "setText")
    wrap(QMessageBox, "setInformativeText")
    wrap(QComboBox, "setItemText", 1)
    wrap(QTabBar, "setTabText", 1)

    orig_add = QComboBox.addItem

    def add_item(self, *a, **k):
        a = tuple(tr(x) if isinstance(x, str) and i == (1 if len(a) > 1 and not isinstance(a[0], str) else 0) else x
                  for i, x in enumerate(a))
        return orig_add(self, *a, **k)
    QComboBox.addItem = add_item

    orig_menu = QMenu.addAction

    def menu_add(self, *a, **k):
        if a and isinstance(a[0], str):
            a = (tr(a[0]),) + a[1:]
        return orig_menu(self, *a, **k)
    QMenu.addAction = menu_add

    orig_draw = QPainter.drawText

    def draw_text(self, *a, **k):
        a = tuple(tr(x) if isinstance(x, str) else x for x in a)
        return orig_draw(self, *a, **k)
    QPainter.drawText = draw_text

    # Construtores com texto: QLabel("..."), QPushButton("..."), QCheckBox("...") etc.
    from PySide6.QtWidgets import QCheckBox, QPushButton, QRadioButton, QToolButton
    for cls in (QLabel, QPushButton, QCheckBox, QRadioButton, QGroupBox):
        orig_init = cls.__init__

        def init(self, *a, __o=orig_init, **k):
            if a and isinstance(a[0], str):
                a = (tr(a[0]),) + a[1:]
            __o(self, *a, **k)
        cls.__init__ = init


def language_label(setting: str | None) -> str:
    return dict(LANGUAGES).get(resolve(setting), "English")
