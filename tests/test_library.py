"""Testes do núcleo da biblioteca. Rodar: python -m unittest discover -s tests"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdfops  # noqa: E402
from fixtures import digital_pdf, scanned_pdf  # noqa: E402
from library import Library, fold, sanitize  # noqa: E402


def analyze_all(lib: Library) -> None:
    for id, path, sig in lib.pending_analysis():
        lib.apply_analysis(id, sig, Library.analyze(path))
    lib.finish_analysis()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prumo_test_"))
        self.src = self.tmp / "src"
        self.lib = Library(self.tmp / "Biblioteca", local_dir=self.tmp / "local")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fresh(self) -> Library:
        """Abre a mesma biblioteca de novo, como o app faria ao reiniciar."""
        return Library(self.lib.root, local_dir=self.tmp / "local")


class LibraryTests(Base):
    def test_import_analyze_and_lists(self):
        d = digital_pdf(self.src / "Petição inicial.pdf", 3)
        s = scanned_pdf(self.src / "Laudo pericial.pdf", 2)
        items = self.lib.import_files([d, s])
        self.assertEqual(len(items), 2)
        analyze_all(self.lib)
        by_name = {i.name: i for i in self.lib.items}
        self.assertEqual(by_name["Petição inicial"].meta.text_status, "digital")
        self.assertEqual(by_name["Petição inicial"].page_count, 3)
        self.assertEqual(by_name["Laudo pericial"].meta.text_status, "scanned")
        self.assertEqual(by_name["Laudo pericial"].meta.ocr_pages, [1, 2])
        self.assertEqual([i.name for i in self.lib.items_for("pending")], ["Laudo pericial"])
        self.assertEqual(self.lib.count("all"), 2)
        self.assertEqual(self.lib.count("recent"), 2)

    def test_search_name_and_text_accent_insensitive(self):
        self.lib.import_files([digital_pdf(self.src / "Contrato.pdf", 1)])
        analyze_all(self.lib)
        self.assertEqual([i.name for i in self.lib.search("contrato")], ["Contrato"])
        self.assertEqual([i.name for i in self.lib.search("SEPSE")], ["Contrato"])     # pelo texto
        self.assertEqual([i.name for i in self.lib.search("indenizacao")], ["Contrato"])  # sem acento
        self.assertEqual(self.lib.search("inexistente"), [])

    def test_folders_move_rename_and_metadata_survive_restart(self):
        item = self.lib.import_files([digital_pdf(self.src / "Procuração.pdf", 1)])[0]
        self.lib.set_favorite(item, True)
        self.lib.create_folder("Clientes")
        self.lib.create_folder("Silva", parent="Clientes")
        self.lib.move([self.lib.item(item.id)], "Clientes/Silva")
        moved = self.lib.item(item.id)
        self.assertEqual(moved.rel, "Clientes/Silva/Procuração.pdf")
        self.lib.rename_folder("Clientes", "Clientes ativos")
        self.lib.rename(self.lib.item(item.id), "Procuração assinada")
        lib2 = self.fresh()
        again = lib2.item(item.id)
        self.assertIsNotNone(again)
        self.assertEqual(again.rel, "Clientes ativos/Silva/Procuração assinada.pdf")
        self.assertTrue(again.meta.favorite)
        top = lib2.folder("Clientes ativos")
        self.assertEqual((top.total_doc_count, top.subfolder_count, top.doc_count), (1, 1, 0))
        with self.assertRaises(pdfops.UserError):
            lib2.create_folder("Clientes ativos")

    def test_external_file_appears_on_reload(self):
        digital_pdf(self.lib.root / "Copiado pelo Explorer.pdf", 1)
        self.lib.reload()
        self.assertEqual([i.name for i in self.lib.items], ["Copiado pelo Explorer"])

    def test_modify_and_undo(self):
        item = self.lib.import_files([digital_pdf(self.src / "Doc.pdf", 4)])[0]
        self.lib.modify(item, lambda p: pdfops.remove(p, [2, 3]))
        item = self.lib.item(item.id)
        self.assertEqual(pdfops.page_count(item.path), 2)
        self.assertTrue(self.lib.can_undo(item))
        self.lib.undo(item)
        item = self.lib.item(item.id)
        self.assertEqual(pdfops.page_count(item.path), 4)
        self.assertFalse(self.lib.can_undo(item))

    def test_ocr_link(self):
        orig = self.lib.import_files([scanned_pdf(self.src / "Escaneado.pdf", 1)])[0]
        analyze_all(self.lib)
        tmp = self.lib.temp_path()
        shutil.copy(orig.path, tmp)
        res = self.lib.adopt(tmp, f"{orig.name} - OCR", orig.folder)
        self.lib.update_after_ocr(self.lib.item(orig.id), res, [1], 0.7)
        self.assertEqual(res.name, "Escaneado - OCR")
        self.assertTrue(self.lib.has_ocr_text(self.lib.item(orig.id)))
        self.assertEqual(self.lib.items_for("pending"), [])
        self.assertEqual([i.name for i in self.lib.items_for("ocr")], ["Escaneado - OCR"])

    def test_delete_and_duplicate(self):
        item = self.lib.import_files([digital_pdf(self.src / "A.pdf", 1)])[0]
        copy = self.lib.duplicate(item)
        self.assertEqual(copy.name, "A (cópia)")
        self.lib.delete([copy])
        self.assertEqual([i.name for i in self.lib.items], ["A"])

    def test_sanitize_and_fold(self):
        self.assertEqual(sanitize('Ação: "x/y"?.pdf'), "Ação- -x-y--")
        self.assertEqual(sanitize("CON"), "CON_")
        self.assertEqual(sanitize("  "), "Documento")
        self.assertEqual(fold("  AÇÃO  Médica "), "acao medica")


class PdfOpsTests(Base):
    def test_split_plan(self):
        self.assertEqual(pdfops.SplitPlan(200, 4).sizes, [50, 50, 50, 50])
        self.assertEqual(pdfops.SplitPlan(10, 3).sizes, [4, 3, 3])
        self.assertEqual(pdfops.SplitPlan(10, 3).ranges, [(1, 4), (5, 7), (8, 10)])
        self.assertEqual(pdfops.SplitPlan(10, 3).summary, "1 parte de 4 páginas e 2 de 3 páginas")

    def test_split_extract_insert_arrange(self):
        src = digital_pdf(self.src / "D.pdf", 7)
        outs = pdfops.split(src, 3, lambda n: self.tmp / f"D - Parte {n}.pdf")
        self.assertEqual([pdfops.page_count(p) for p in outs], [3, 2, 2])
        with self.assertRaises(pdfops.UserError):
            pdfops.split(src, 9, lambda n: self.tmp / f"x{n}.pdf")
        ext = self.tmp / "ext.pdf"
        pdfops.extract(src, ext, [7, 1])
        self.assertEqual(pdfops.page_count(ext), 2)
        pdfops.insert(ext, src, [2, 3], at=2)
        self.assertEqual(pdfops.page_count(ext), 4)
        pdfops.insert(ext, ext, [1], at=99)        # do próprio PDF, no fim
        self.assertEqual(pdfops.page_count(ext), 5)
        pdfops.arrange(ext, [(5, 0), (1, 90)])
        self.assertEqual(pdfops.page_count(ext), 2)
        import pikepdf
        with pikepdf.open(ext) as pdf:
            self.assertEqual(int(pdf.pages[1].obj.get("/Rotate", 0)), 90)
        with self.assertRaises(pdfops.UserError):
            pdfops.remove(ext, [1, 2])


if __name__ == "__main__":
    unittest.main()
