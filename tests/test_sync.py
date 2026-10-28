"""Biblioteca numa nuvem usada por dois aparelhos (dois computadores, ou o computador e o iPhone).

Os dois Prumos leem e gravam o mesmo .prumo/library.json. Estes testes simulam os dois aparelhos com
duas bibliotecas na mesma pasta, cada uma com a sua pasta local (cache, versões).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import digital_pdf  # noqa: E402
from library import Library  # noqa: E402


def touch_later(path: Path) -> None:
    """Garante que a próxima gravação tenha outra data (sistemas com relógio de arquivo grosso)."""
    time.sleep(0.02)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "Nuvem" / "Prumo PDF"
        self.root.mkdir(parents=True)
        for name in ("Contrato", "Laudo", "Recibo"):
            digital_pdf(self.root / f"{name}.pdf", 1, "x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def device(self, name: str) -> Library:
        return Library(self.root, local_dir=self.tmp / f"local-{name}")

    def fav(self, lib: Library) -> set[str]:
        return {i.name for i in lib.items if i.meta.favorite}

    def test_favorite_and_ocr_link_reach_the_other_device(self):
        pc, phone = self.device("pc"), self.device("phone")
        self.assertEqual({i.rel: i.id for i in pc.items}, {i.rel: i.id for i in phone.items},
                         "os dois aparelhos usam os mesmos ids")
        pc.set_favorite(pc.item_by_path("Contrato.pdf"), True)
        touch_later(pc.meta_file)
        phone.reload()
        self.assertEqual(self.fav(phone), {"Contrato"})

        # O outro aparelho faz OCR do Laudo: a cópia e a ligação aparecem aqui.
        laudo = phone.item_by_path("Laudo.pdf")
        digital_pdf(self.root / "Laudo - OCR.pdf", 1, "x")
        result = phone.register(self.root / "Laudo - OCR.pdf")
        phone.update_after_ocr(laudo, result, [], None)
        touch_later(phone.meta_file)
        pc.reload()
        copy = pc.item_by_path("Laudo - OCR.pdf")
        self.assertTrue(copy.meta.is_ocr_result)
        self.assertEqual(pc.ocr_copy(pc.item_by_path("Laudo.pdf")).rel, "Laudo - OCR.pdf")

    def test_changes_on_both_devices_are_kept(self):
        pc, phone = self.device("pc"), self.device("phone")
        pc.set_favorite(pc.item_by_path("Contrato.pdf"), True)
        touch_later(pc.meta_file)
        # O iPhone ainda não recarregou e marca outro favorito: o do computador não pode se perder.
        phone.set_favorite(phone.item_by_path("Recibo.pdf"), True)
        touch_later(phone.meta_file)
        pc.reload()
        self.assertEqual(self.fav(pc), {"Contrato", "Recibo"})
        self.assertEqual(self.fav(phone), {"Contrato", "Recibo"})
        # Desmarcar também sincroniza.
        pc.set_favorite(pc.item_by_path("Contrato.pdf"), False)
        touch_later(pc.meta_file)
        phone.reload()
        self.assertEqual(self.fav(phone), {"Recibo"})

    def test_file_still_on_the_way_keeps_its_favorite(self):
        pc = self.device("pc")
        # O iPhone gravou o library.json com um PDF novo, mas o PDF ainda não chegou neste computador.
        rows = json.loads(pc.meta_file.read_text(encoding="utf-8"))
        rows.append({"path": "Clientes/Novo.pdf", "id": "ID-DO-IPHONE", "favorite": True})
        pc.meta_file.write_text(json.dumps(rows), encoding="utf-8")
        touch_later(pc.meta_file)
        pc.set_favorite(pc.item_by_path("Laudo.pdf"), True)
        saved = {r["path"]: r for r in json.loads(pc.meta_file.read_text(encoding="utf-8"))}
        self.assertIn("Clientes/Novo.pdf", saved, "não apaga o que ainda está chegando")
        # O PDF chega pela nuvem.
        (self.root / "Clientes").mkdir()
        digital_pdf(self.root / "Clientes" / "Novo.pdf", 1, "x")
        self.assertTrue(pc.reload_if_changed())
        novo = pc.item_by_path("Clientes/Novo.pdf")
        self.assertEqual(novo.id, "ID-DO-IPHONE")
        self.assertTrue(novo.meta.favorite)
        self.assertFalse(pc.reload_if_changed(), "nada mudou: não recarrega à toa")

    def test_deleted_file_leaves_the_shared_list(self):
        pc = self.device("pc")
        (self.root / "Recibo.pdf").unlink()
        pc.reload()
        paths = {r["path"] for r in json.loads(pc.meta_file.read_text(encoding="utf-8"))}
        self.assertNotIn("Recibo.pdf", paths)

    def test_reads_the_list_written_by_the_iphone(self):
        # O Prumo do iPhone grava só os campos compartilhados, com os mesmos nomes.
        (self.root / ".prumo").mkdir(exist_ok=True)
        (self.root / ".prumo" / "library.json").write_text(json.dumps([
            {"path": "Laudo.pdf", "id": "A1", "favorite": True, "pending_ocr": False, "is_ocr_result": False,
             "ocr_copy_id": "B2"},
            {"path": "Recibo.pdf", "id": "B2", "favorite": False, "is_ocr_result": True, "source_id": "A1"},
        ]), encoding="utf-8")
        pc = self.device("pc")
        self.assertEqual(self.fav(pc), {"Laudo"})
        self.assertEqual(pc.ocr_copy(pc.item_by_path("Laudo.pdf")).rel, "Recibo.pdf")


    def test_joining_a_cloud_library_merges_without_duplicates(self):
        import backup
        pc_root = self.tmp / "Documentos" / "Prumo PDF"
        (pc_root / "Clientes").mkdir(parents=True)
        shutil.copy2(self.root / "Contrato.pdf", pc_root / "Contrato.pdf")          # igual ao da nuvem
        digital_pdf(pc_root / "Clientes" / "Peticao.pdf", 2, "y")                   # só neste computador
        old = Library(pc_root, local_dir=self.tmp / "local-old")
        old.set_favorite(old.item_by_path("Clientes/Peticao.pdf"), True)
        cloud = self.device("pc")
        added, same = backup.merge_move(pc_root, cloud)
        self.assertEqual((added, same), (1, 1))
        self.assertIsNotNone(cloud.item_by_path("Clientes/Peticao.pdf"))
        self.assertTrue(cloud.item_by_path("Clientes/Peticao.pdf").meta.favorite)
        self.assertEqual(sorted(i.rel for i in cloud.items),
                         ["Clientes/Peticao.pdf", "Contrato.pdf", "Laudo.pdf", "Recibo.pdf"])
        self.assertEqual(list(pc_root.rglob("*.pdf")), [], "a pasta antiga fica vazia")

if __name__ == "__main__":
    unittest.main()
