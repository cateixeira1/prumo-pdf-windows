"""
Idiomas: nenhum texto em português pode aparecer quando o app está em outro idioma.

1. Catálogos: todo texto da interface (lido do código por tools/i18n_strings.py) tem tradução nos 11
   idiomas, com as mesmas partes variáveis ({}), e a tradução não é traduzida de novo.
2. Telas de verdade: abre a janela em cada idioma, percorre as telas, painéis, menus, alertas e folhas
   (sem esperar clique) e confere todo texto visível ou pintado: nenhum pode ser um texto em português do
   catálogo nem ter palavras típicas do português.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QMenu,  # noqa: E402
                               QWidget)

from fixtures import digital_pdf, scanned_pdf  # noqa: E402

app = QApplication.instance() or QApplication([])

import i18n  # noqa: E402
import i18n_strings  # noqa: E402

LANGS = [c for c in i18n.CODES if c != "pt"]
CATALOGS = {c: json.loads((ROOT / "app" / "locales" / f"{c}.json").read_text(encoding="utf-8")) for c in LANGS}

# Palavras que só o português usa (em espanhol, "página" e "biblioteca" também existem).
_PT_WORDS = (r"não|você|pasta|pastas|senha|nenhum|nenhuma|assinatura|assinado|também|então|está|já|até|"
             r"depois|ainda|arquivo|arquivos|criar|excluir|desfazer|página|páginas|biblioteca|selecionad[oa]s?|"
             r"compartilhar|ajustes|combinar|dividir|destacar|resumo|nuvem|cópia|configurações")
_PT_ES_SHARED = {"página", "páginas", "biblioteca", "está", "combinar", "dividir", "ajustes", "criar"}


def portuguese_words(text: str, lang: str) -> list[str]:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    pt = set(_PT_WORDS.split("|"))
    out = []
    for w in words:
        if lang == "es" and w in _PT_ES_SHARED:
            continue
        if w in pt or re.fullmatch(r"selecionad[oa]s?", w) or w.endswith(("ção", "ções", "ões")):
            out.append(w)
    return out


def pump(ms=60):
    end = time.time() + ms / 1000
    while time.time() < end:
        loop = QEventLoop()
        QTimer.singleShot(15, loop.quit)
        loop.exec()


def wait(cond, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(40)
    return False


class CatalogTests(unittest.TestCase):
    def test_every_interface_text_is_translated(self):
        strings = i18n_strings.extract()
        self.assertGreater(len(strings), 500)
        for code, cat in CATALOGS.items():
            missing = sorted(s for s in strings if s not in cat)
            self.assertEqual(missing[:15], [], f"{code}: {len(missing)} textos sem tradução, por exemplo")

    def test_placeholders_and_no_empty_values(self):
        for code, cat in CATALOGS.items():
            for pt, tr in cat.items():
                self.assertTrue(tr.strip(), f"{code}: vazio para {pt!r}")
                self.assertEqual(pt.count("{}"), tr.count("{}"), f"{code}: {pt!r} → {tr!r}")

    def test_no_portuguese_left_in_translations(self):
        bad = [f"{code}: {pt!r} → {tr!r} {portuguese_words(tr, code)}"
               for code, cat in CATALOGS.items() for pt, tr in cat.items() if portuguese_words(tr, code)]
        self.assertEqual(bad, [])

    def test_translation_is_not_translated_again(self):
        # O texto já traduzido passa de novo pelos ganchos do Qt: não pode virar outra coisa.
        try:
            bad = []
            for code, cat in CATALOGS.items():
                i18n.set_language(code)
                for pt, tr in cat.items():
                    sample = tr.replace("{}", "7")
                    if i18n.tr(sample) != sample:
                        bad.append(f"{code}: {pt!r} → {tr!r} → {i18n.tr(sample)!r}")
            self.assertEqual(bad, [])
        finally:
            i18n.set_language("pt")

    def test_helpers(self):
        try:
            i18n.set_language("en")
            self.assertEqual(i18n.trn(1, "1 página", "{} páginas"), "1 page")
            self.assertEqual(i18n.trn(3, "1 página", "{} páginas"), "3 pages")
            self.assertEqual(i18n.tr("  Favoritar"), "  Add to Favorites")
            self.assertEqual(i18n.tr(i18n.raw("Favoritos")), "Favoritos")      # nome do usuário
            self.assertEqual(i18n.strip_suffix("Contract - protected", "{} - protegido"), "Contract")
            self.assertEqual(i18n.strip_suffix("Contrato - protegido", "{} - protegido"), "Contrato")
            import core
            self.assertEqual(core.parse_page_selection("2-end", 5), [2, 3, 4, 5])
            i18n.set_language("de")
            self.assertEqual(core.parse_page_selection("4-ende", 5), [4, 5])
            self.assertEqual(i18n.fmt_date(1_700_000_000), "14.11.2023")
            i18n.set_language("ja")
            import summary
            self.assertTrue(summary.pages_label([3]).isascii(), "japonês sai em inglês dentro do PDF")
        finally:
            i18n.set_language("pt")


class Collector:
    """Junta todo texto que aparece: widgets, menus, alertas, folhas, avisos e o que é pintado."""

    def __init__(self):
        self.texts: list[tuple[str, str]] = []
        self.where = ""

    def add(self, text, kind="widget"):
        if isinstance(text, str) and text.strip() and not isinstance(text, i18n.Raw):
            self.texts.append((f"{self.where} [{kind}]", str(text)))

    def widget(self, w: QWidget):
        try:
            w.grab()                       # pinta: o que é desenhado passa por drawText
        except Exception:  # noqa: BLE001
            pass
        for x in [w] + w.findChildren(QWidget):
            if not x.isVisibleTo(w) and x is not w:
                continue
            self.add(x.toolTip(), "dica")
            if isinstance(x, QLabel):
                self.add(x.text(), "rótulo")
            elif isinstance(x, QAbstractButton):
                self.add(x.text(), "botão")
            elif isinstance(x, QLineEdit):
                self.add(x.placeholderText(), "campo")
            elif isinstance(x, QComboBox):
                for i in range(x.count()):
                    self.add(x.itemText(i), "lista")

    def menu(self, m: QMenu):
        for a in m.actions():
            self.add(a.text(), "menu")
            self.add(a.toolTip(), "menu")
            if a.menu() is not None:
                self.add(a.menu().title(), "menu")
                self.menu(a.menu())


class ScreensInEveryLanguage(unittest.TestCase):
    """Abre as telas em cada idioma e procura português."""

    @classmethod
    def setUpClass(cls):
        import ios_kit
        import ios_theme
        from PySide6.QtGui import QPainter
        ios_theme.T.setup("light")
        cls.tmp = Path(tempfile.mkdtemp(prefix="prumo_i18n_"))
        src = cls.tmp / "src"
        cls.files = [digital_pdf(src / "Alpha.pdf", 6), digital_pdf(src / "Beta.pdf", 3),
                     scanned_pdf(src / "Gamma.pdf", 1)]
        i18n.install_hooks()
        cls.col = Collector()
        col = cls.col

        orig_draw = QPainter.drawText

        def draw(self, *a, **k):
            for x in a:
                if isinstance(x, str):
                    col.add(i18n.tr(x), "pintado")
            return orig_draw(self, *a, **k)
        import reader
        import screens
        cls._orig = (QPainter.drawText, ios_kit._Overlay.run, ios_kit.styled_menu)
        QPainter.drawText = draw

        def run(self):
            self._place()
            self.show()
            col.widget(self)
            self.parent().removeEventFilter(self)
            self.hide()
            self.deleteLater()
            return None
        ios_kit._Overlay.run = run

        class CollectedMenu(QMenu):
            """Menu que não abre: só anota os textos (um menu de verdade espera um clique)."""

            def exec(self, *a, **k):
                col.menu(self)
                return None
        for mod in (ios_kit, screens, reader):
            mod.styled_menu = CollectedMenu

    @classmethod
    def tearDownClass(cls):
        import ios_kit
        from PySide6.QtGui import QPainter
        import reader
        import screens
        QPainter.drawText, ios_kit._Overlay.run, menu = cls._orig
        for mod in (ios_kit, screens, reader):
            mod.styled_menu = menu
        i18n.set_language("pt")
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def visit(self, lang: str):
        from app_window import MainWindow
        from library import LISTS, Library
        import page_tools
        import reader
        import screens
        import sign_ui
        col = self.col
        i18n.set_language(lang)
        i18n.install_qt_translator(app)
        root = self.tmp / lang
        settings = QSettings(str(root / "s.ini"), QSettings.IniFormat)
        w = MainWindow(settings, Library(root / "Library", local_dir=root / "local"))
        w.resize(1300, 900)
        w.show()
        try:
            w.import_paths(self.files)
            self.assertTrue(wait(lambda: len(w.lib.items) == 3 and all(i.page_count for i in w.lib.items)))
            w.lib.create_folder("Zeta")
            w.lib.reload()
            alpha = next(i for i in w.lib.items if i.name == "Alpha")
            gamma = next(i for i in w.lib.items if i.name == "Gamma")

            def look(where, widget=None):
                col.where = f"{lang}: {where}"
                pump(80)
                col.widget(widget or w)
                col.add(w.toast_w.text.text() if w.toast_w.isVisible() else "", "aviso")

            look("início")
            w.current()._menu() if hasattr(w.current(), "_menu") else None
            for key in LISTS:
                w.push(screens.DocumentGridScreen(w, list_id=key))
                look(f"lista {key}")
                w.current()._menu()
                w.current().set_selecting(True)
                look(f"lista {key} seleção")
                w.back(force=True)
            w.push(screens.FoldersScreen(w))
            look("pastas")
            w.back(force=True)
            w.push(screens.DocumentGridScreen(w, folder="Zeta"))
            look("pasta vazia")
            w.back(force=True)
            w.push(screens.SettingsScreen(w))
            look("ajustes")
            w.back(force=True)
            w.open_document(alpha.id)
            look("tela do PDF")
            w.actions.context_menu(w.current(), alpha, w.current().rect().center())
            w.back(force=True)
            w.open_document(gamma.id)
            look("tela do PDF escaneado")
            w.back(force=True)
            # ferramentas da tela inicial (cada uma abre o seletor de PDF)
            for key, title in (("read", "Ler qual PDF?"), ("ocr", "Fazer OCR de quais PDFs?"),
                               ("organize", "Organizar qual PDF?"), ("split", "Dividir qual PDF?"),
                               ("sign", "Assinar qual PDF?")):
                col.where = f"{lang}: ferramenta {key}"
                screens.run_tool(w, key, title)
            # folhas e alertas das ferramentas
            for name, fn in (("dividir", lambda: screens.split_dialog(w, alpha)),
                             ("incluir", lambda: screens.include_pages_dialog(w, alpha, source=alpha)),
                             ("curvas", lambda: screens.dewarp_dialog(w, alpha)),
                             ("proteger", lambda: screens.protect_dialog(w, alpha)),
                             ("senha do app", lambda: screens.set_app_password(w)),
                             ("cortar", lambda: page_tools.crop_dialog(w, alpha)),
                             ("numerar", lambda: page_tools.number_dialog(w, alpha)),
                             ("assinar", lambda: sign_ui.sign_dialog(w, alpha)),
                             ("nuvem", lambda: screens.cloud_dialog(w)),
                             ("nova pasta", lambda: screens.create_folder(w)),
                             ("excluir", lambda: w.actions.delete([alpha])),
                             ("compartilhar", lambda: w.actions.share([alpha])),
                             ("desfazer", lambda: w.actions.undo(alpha))):
                col.where = f"{lang}: {name}"
                fn()
                pump(30)
                look(f"{name} (aviso)")
            for mode in ("remove", "extract"):
                w.push(screens.PagePickerScreen(w, alpha.id, mode))
                look(f"escolher páginas {mode}")
                w.back(force=True)
            w.push(screens.MergeScreen(w))
            look("combinar")
            w.back(force=True)
            w.organize(alpha)
            look("organizar")
            w.back(force=True)
            # leitor: modo Página e modo Texto
            r = reader.ReaderScreen(w, alpha.id)
            w.push(r)
            self.assertTrue(wait(lambda: r.text is not None, 30))
            r.open_search()
            look("leitor")
            for tool in ("select", "highlight", "erase"):
                r.set_tool(tool, "yellow" if tool == "highlight" else None)
                look(f"leitor {tool}")
            r.context_menu(r.mapToGlobal(r.rect().center()))
            r.undo()
            look("leitor desfazer")
            r.open_text_mode()
            pump(300)
            t = w.current()
            look("modo texto")
            if hasattr(t, "_menu"):
                t._menu()
            w.back(force=True)
        finally:
            w.jobs.cancel_all()
            w.hub.shutdown()
            w.close()
            w.deleteLater()
            pump(50)

    def check(self, lang: str):
        self.col.texts.clear()
        self.visit(lang)
        cat = CATALOGS[lang]
        leaks = []
        for where, text in self.col.texts:
            parts = [text] + [p for p in re.split(r"\n| · |: ", text) if p.strip()]
            for p in parts:
                p = p.strip()
                if p in cat and cat[p] != p:
                    leaks.append(f"{where}: {text!r} (texto do catálogo sem tradução)")
                    break
            else:
                found = portuguese_words(text, lang)
                if found:
                    leaks.append(f"{where}: {text!r} (palavras {found})")
        self.assertGreater(len(self.col.texts), 400, "a coleta de textos não funcionou")
        uniq = sorted(set(leaks))
        if os.environ.get("PRUMO_I18N_DUMP"):
            Path(os.environ["PRUMO_I18N_DUMP"]).write_text(
                "\n".join(f"{w}\t{t!r}" for w, t in self.col.texts), encoding="utf-8")
        if uniq:
            print("\n".join(uniq))        # a lista inteira aparece no log do teste
        self.assertEqual(uniq[:25], [], f"{lang}: {len(uniq)} textos em português")


def _make(lang):
    def test(self):
        self.check(lang)
    test.__name__ = f"test_{lang.replace('-', '_')}"
    return test


for _lang in LANGS:
    setattr(ScreensInEveryLanguage, f"test_{_lang.replace('-', '_')}", _make(_lang))


if __name__ == "__main__":
    unittest.main()
