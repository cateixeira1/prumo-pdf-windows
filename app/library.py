"""
Biblioteca de PDFs (equivalente ao Library do iPhone), sem interface.

Os PDFs ficam como arquivos e pastas comuns dentro da pasta da biblioteca
(por padrão, Documentos\\Prumo PDF). Assim o usuário pode abri-los com qualquer
programa, copiar para outro lugar ou colocar a pasta dentro do OneDrive,
Google Drive ou iCloud Drive para ter backup na nuvem que escolher.

Os metadados (favoritos, OCR pendente, ligação entre o original e a cópia com
OCR) ficam em <biblioteca>\\.prumo\\library.json, para acompanhar a pasta em
outro computador. Cache de texto, miniaturas e versões para "Desfazer" ficam
na pasta local do usuário (AppData), porque podem ser refeitos.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from pdfops import UserError

META_DIR = ".prumo"
RECENT_DAYS = 7
# Campos que acompanham a biblioteca entre aparelhos (Windows e iPhone) pelo .prumo/library.json.
# As referências (cópia com OCR, original) vão como id no arquivo e são conferidas pelo caminho.
SHARED_FIELDS = ("favorite", "pending_ocr", "is_ocr_result", "ocr_copy_id", "source_id")
REF_FIELDS = ("ocr_copy_id", "source_id")


# --- Modelo -------------------------------------------------------------------

TEXT_DIGITAL = "digital"
TEXT_SCANNED = "scanned"
TEXT_MIXED = "mixed"
TEXT_EMPTY = "empty"

TEXT_LABELS = {TEXT_DIGITAL: "Texto digital", TEXT_SCANNED: "Escaneado",
               TEXT_MIXED: "Misto", TEXT_EMPTY: "Vazio"}


def needs_ocr_status(status: str | None) -> bool:
    return status in (TEXT_SCANNED, TEXT_MIXED)


@dataclass
class DocMeta:
    path: str                                  # relativo à biblioteca, com "/"
    id: str = field(default_factory=lambda: str(uuid.uuid4()).upper())
    favorite: bool = False
    pending_ocr: bool = False                  # o usuário escolheu "Mais tarde"
    is_ocr_result: bool = False                # arquivo criado pelo OCR do app
    ocr_copy_id: str | None = None             # cópia com OCR gerada a partir deste arquivo
    source_id: str | None = None               # arquivo de origem (para os arquivos com OCR)
    text_status: str | None = None
    page_count: int | None = None
    ocr_pages: list[int] | None = None
    signature: str | None = None               # tamanho + data; quando muda, reanalisa
    review_pages: list[int] | None = None      # páginas com baixa confiança no OCR
    ocr_confidence: float | None = None
    last_opened: float | None = None
    has_undo: bool = False
    added: float | None = field(default_factory=time.time)
    locked: bool = False                       # PDF protegido por senha (precisa da senha para abrir)
    signed: int = 0                            # quantas assinaturas digitais o PDF tem (0: nenhuma)

    @classmethod
    def from_dict(cls, d: dict) -> "DocMeta | None":
        """Leitura tolerante: ignora campos desconhecidos e aceita campos ausentes."""
        if not isinstance(d, dict) or not d.get("path") or not d.get("id"):
            return None
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class PDFItem:
    meta: DocMeta
    path: Path            # caminho completo
    size: int
    modified: float

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def rel(self) -> str:
        return self.meta.path

    @property
    def name(self) -> str:
        return Path(self.rel).stem

    @property
    def folder(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else ""

    @property
    def folder_name(self) -> str:
        return self.folder.rsplit("/", 1)[-1] if self.folder else "Sem pasta"

    @property
    def version(self) -> str:
        """Muda sempre que o arquivo muda (cache de miniaturas)."""
        return f"{self.size}-{int(self.modified * 1000)}"

    @property
    def page_count(self) -> int | None:
        return self.meta.page_count

    @property
    def last_activity(self) -> float:
        return max(self.meta.last_opened or 0, self.modified)


@dataclass
class FolderItem:
    path: str
    doc_count: int          # PDFs diretamente nesta pasta
    total_doc_count: int    # incluindo subpastas
    subfolder_count: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def parent(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


LISTS = {
    "all": "Todos os PDFs",
    "recent": "Recentes",
    "pending": "Aguardando OCR",
    "ocr": "Com OCR",
    "favorites": "Favoritos",
}


# --- Utilidades ---------------------------------------------------------------

def fold(s: str) -> str:
    """Minúsculas, sem acentos e com espaços normalizados (para a busca)."""
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())


_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def sanitize(name: str) -> str:
    """Nome válido no Windows (sem extensão)."""
    s = _BAD_CHARS.sub("-", name.replace("\n", " ")).strip()
    if s.lower().endswith(".pdf"):
        s = s[:-4]
    s = s.strip(" .")
    if s.upper() in _RESERVED:
        s += "_"
    return (s or "Documento")[:150]


def signature(size: int, modified: float) -> str:
    return f"{size}-{int(modified)}"


def default_root() -> Path:
    docs = Path.home() / "Documents"
    if os.name == "nt":
        try:  # pasta Documentos real (pode estar no OneDrive)
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
                docs = Path(buf.value)
        except Exception:
            pass
    return docs / "Prumo PDF"


def local_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Prumo PDF"


# --- Biblioteca ---------------------------------------------------------------

class Library:
    def __init__(self, root: str | Path, local_dir: str | Path | None = None):
        self.root = Path(root)
        key = hashlib.sha1(str(self.root.resolve()).lower().encode()).hexdigest()[:12]
        local = Path(local_dir) if local_dir else local_data_dir() / key
        self.meta_dir = self.root / META_DIR
        self.meta_file = self.meta_dir / "library.json"
        self.versions_dir = local / "Versions"
        self.text_dir = local / "Text"
        self.thumbs_dir = local / "Thumbs"
        self.temp_dir = local / "tmp"
        for d in (self.root, self.meta_dir, self.versions_dir, self.text_dir, self.thumbs_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)
        _hide(self.meta_dir)
        self.items: list[PDFItem] = []
        self.folders: list[FolderItem] = []
        self._metas: dict[str, DocMeta] = {}
        self._texts: dict[str, str] = {}
        self._listeners = []
        # Sincronização com outros aparelhos pelo arquivo compartilhado (ver _sync_disk).
        self._disk_stamp = None                       # (mtime_ns, tamanho) do library.json lido ou gravado
        self._disk_entries: dict[str, dict] = {}      # caminho em minúsculas -> entrada do arquivo
        self._snap: dict[str, dict] = {}              # valores compartilhados na última sincronização
        self._known: set[str] = set()                 # caminhos que já existiram neste aparelho
        self._tree = None
        self._load_meta()
        self.reload()

    # --- avisos de mudança ---
    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _changed(self) -> None:
        for fn in list(self._listeners):
            fn()

    # --- leitura ---
    def reload(self) -> None:
        self._sync_disk()
        files, dirs = [], []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != META_DIR)
            rel_dir = os.path.relpath(dirpath, self.root).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            for d in dirnames:
                dirs.append(f"{rel_dir}/{d}" if rel_dir else d)
            for f in filenames:
                if f.startswith(".") or not f.lower().endswith(".pdf"):
                    continue
                full = Path(dirpath) / f
                try:
                    st = full.stat()
                except OSError:
                    continue
                rel = f"{rel_dir}/{f}" if rel_dir else f
                files.append((full, rel, st.st_size, st.st_mtime))

        old_paths = {k: m.path for k, m in self._metas.items()}
        by_path = {m.path.lower(): m for m in self._metas.values()}
        new_metas: dict[str, DocMeta] = {}
        items = []
        used_ids = {m.id for m in self._metas.values()}
        for full, rel, size, mtime in files:
            meta = by_path.get(rel.lower()) or self._new_meta(rel, used_ids)
            meta.path = rel
            new_metas[meta.id] = meta
            items.append(PDFItem(meta, full, size, mtime))
        for gone in set(self._metas) - set(new_metas):
            for p in (self.versions_dir / f"{gone}.pdf", self.text_dir / f"{gone}.txt"):
                p.unlink(missing_ok=True)
            self._texts.pop(gone, None)
        changed = set(new_metas) != set(self._metas) or any(
            m.path != old_paths.get(k) for k, m in new_metas.items())
        self._metas = new_metas
        self.items = sorted(items, key=lambda i: i.modified, reverse=True)

        dirs.sort(key=lambda s: s.casefold())
        self.folders = []
        for d in dirs:
            prefix = d + "/"
            self.folders.append(FolderItem(
                path=d,
                doc_count=sum(1 for i in items if i.folder == d),
                total_doc_count=sum(1 for i in items if i.rel.startswith(prefix)),
                subfolder_count=sum(1 for x in dirs if x.rsplit("/", 1)[0] == d and "/" in x)))
        self._known |= {m.path.lower() for m in new_metas.values()}
        self._tree = self._scan_tree()
        if changed:
            self.save_meta()
        self._changed()

    def reload_if_changed(self) -> bool:
        """Para a sincronização: só recarrega se algo mudou na pasta (ou no library.json)."""
        if self._scan_tree() == self._tree and self._stamp() == self._disk_stamp:
            return False
        self.reload()
        return True

    def _scan_tree(self) -> str:
        h = hashlib.sha1()
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            h.update(dirpath.encode("utf-8", "surrogatepass"))
            for f in sorted(filenames):
                if f.lower().endswith(".pdf") and not f.startswith("."):
                    try:
                        st = os.stat(os.path.join(dirpath, f))
                    except OSError:
                        continue
                    h.update(f"{f}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8", "surrogatepass"))
        return h.hexdigest()

    def item(self, id: str) -> PDFItem | None:
        return next((i for i in self.items if i.id == id), None)

    def item_by_path(self, rel: str) -> PDFItem | None:
        return next((i for i in self.items if i.rel.lower() == rel.lower()), None)

    def folder(self, path: str) -> FolderItem | None:
        return next((f for f in self.folders if f.path == path), None)

    def items_in_folder(self, path: str) -> list[PDFItem]:
        return sorted((i for i in self.items if i.folder == path), key=lambda i: i.name.casefold())

    def subfolders(self, path: str) -> list[FolderItem]:
        return [f for f in self.folders if f.parent == path]

    @property
    def top_folders(self) -> list[FolderItem]:
        return self.subfolders("")

    def ocr_copy(self, item: PDFItem) -> PDFItem | None:
        return self.item(item.meta.ocr_copy_id) if item.meta.ocr_copy_id else None

    def has_ocr_text(self, item: PDFItem) -> bool:
        return item.meta.is_ocr_result or self.ocr_copy(item) is not None

    def needs_ocr_attention(self, item: PDFItem) -> bool:
        m = item.meta
        if m.locked or m.is_ocr_result or (m.ocr_copy_id and m.ocr_copy_id in self._metas):
            return False
        return m.pending_ocr or needs_ocr_status(m.text_status)

    def items_for(self, list_id: str) -> list[PDFItem]:
        if list_id == "recent":
            limit = time.time() - RECENT_DAYS * 86400
            return sorted((i for i in self.items if i.last_activity >= limit),
                          key=lambda i: i.last_activity, reverse=True)
        if list_id == "pending":
            return [i for i in self.items if self.needs_ocr_attention(i)]
        if list_id == "ocr":
            return [i for i in self.items if i.meta.is_ocr_result]
        if list_id == "favorites":
            return [i for i in self.items if i.meta.favorite]
        return list(self.items)

    def count(self, list_id: str) -> int:
        return len(self.items_for(list_id))

    # --- busca ---
    def search(self, query: str, pool: list[PDFItem] | None = None) -> list[PDFItem]:
        q = fold(query)
        if not q:
            return []
        source = self.items if pool is None else pool
        by_name = [i for i in source if q in fold(i.name)]
        ids = {i.id for i in by_name}
        by_text = [i for i in source if i.id not in ids and q in self.text(i.id)]
        return by_name + by_text

    def text(self, id: str) -> str:
        if id not in self._texts:
            try:
                self._texts[id] = (self.text_dir / f"{id}.txt").read_text(encoding="utf-8")
            except OSError:
                self._texts[id] = ""
        return self._texts[id]

    # --- análise em segundo plano ---
    def pending_analysis(self) -> list[tuple[str, Path, str]]:
        """(id, caminho, assinatura) dos arquivos que ainda não foram analisados."""
        return [(i.id, i.path, signature(i.size, i.modified)) for i in self.items
                if i.meta.signature != signature(i.size, i.modified)]

    @staticmethod
    def analyze(path: Path) -> dict:
        """Roda fora da tela principal. Não altera o arquivo."""
        import core

        import pdfops
        if pdfops.is_encrypted(path):
            return {"locked": True, "page_count": pdfops.page_count_locked(path), "status": None,
                    "ocr_pages": [], "text": ""}
        info = core.analyze_pdf(path)
        if info.error:
            return {"error": info.error, "page_count": None, "status": None, "ocr_pages": [], "text": ""}
        kinds = [p.kind for p in info.pages]
        need = info.ocr_pages
        if not kinds:
            status = TEXT_EMPTY
        elif not need:
            status = TEXT_DIGITAL
        elif len(need) == len(kinds):
            status = TEXT_SCANNED
        else:
            status = TEXT_MIXED
        try:
            text = "\n".join(core.extract_text(path))
        except Exception:
            text = ""
        try:
            import signing
            signed = signing.signature_count(path)
        except Exception:  # noqa: BLE001
            signed = 0
        return {"page_count": info.page_count, "status": status, "ocr_pages": need, "text": text, "signed": signed}

    def apply_analysis(self, id: str, sig: str, result: dict) -> None:
        meta = self._metas.get(id)
        if meta is None:
            return
        folded = fold(result.get("text") or "")
        try:
            (self.text_dir / f"{id}.txt").write_text(folded, encoding="utf-8")
        except OSError:
            pass
        self._texts[id] = folded
        meta.signature = sig
        meta.locked = bool(result.get("locked"))
        meta.signed = int(result.get("signed") or 0)
        meta.page_count = result.get("page_count")
        meta.text_status = result.get("status")
        meta.ocr_pages = result.get("ocr_pages") or []

    def finish_analysis(self) -> None:
        self.save_meta()
        self._changed()

    # --- metadados ---
    # O .prumo/library.json fica dentro da biblioteca. Quando a biblioteca está numa nuvem, o mesmo
    # arquivo é lido e gravado pelo Prumo de outros aparelhos (outro computador, o iPhone). Para não
    # perder o que o outro aparelho mudou, antes de gravar o arquivo é relido e os campos
    # compartilhados que não mudaram aqui desde a última leitura são trazidos de lá.
    def _stamp(self):
        try:
            st = self.meta_file.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _read_disk(self) -> list[dict]:
        try:
            data = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in data if isinstance(d, dict) and d.get("path") and d.get("id")] \
            if isinstance(data, list) else []

    def _load_meta(self) -> None:
        self._disk_stamp = self._stamp()
        entries = self._read_disk()
        for d in entries:
            m = DocMeta.from_dict(d)
            if m:
                self._metas.setdefault(m.id, m)
        self._set_disk(entries)
        self._snap = self._shared_values()

    def _set_disk(self, entries: list[dict]) -> None:
        self._disk_entries = {}
        for d in entries:
            self._disk_entries.setdefault(str(d["path"]).replace("\\", "/").lower(), d)

    def _shared_values(self) -> dict[str, dict]:
        """Valores compartilhados de cada arquivo deste aparelho, com as referências como caminho."""
        id_path = {m.id: m.path.lower() for m in self._metas.values()}
        out = {}
        for m in self._metas.values():
            vals = {f: getattr(m, f) for f in SHARED_FIELDS}
            for f in REF_FIELDS:
                if vals[f]:
                    vals[f] = id_path.get(vals[f], "id:" + vals[f])
            out[m.path.lower()] = vals
        return out

    def _disk_values(self, entry: dict, disk_id_path: dict[str, str]) -> dict:
        vals = {}
        for f in SHARED_FIELDS:
            v = entry.get(f)
            if f in REF_FIELDS:
                vals[f] = (disk_id_path.get(v, "id:" + str(v))) if v else None
            else:
                vals[f] = bool(v)
        return vals

    def _resolve_ref(self, value, by_path: dict[str, DocMeta]):
        if not value:
            return None
        if value.startswith("id:"):
            return value[3:]
        m = by_path.get(value)
        if m:
            return m.id
        entry = self._disk_entries.get(value)
        return entry.get("id") if entry else None

    def _sync_disk(self) -> None:
        """Traz do library.json o que outro aparelho mudou (só quando o arquivo mudou)."""
        stamp = self._stamp()
        if stamp == self._disk_stamp:
            return
        self._disk_stamp = stamp
        entries = self._read_disk()
        self._set_disk(entries)
        if not entries:
            return
        disk_id_path = {d["id"]: str(d["path"]).replace("\\", "/").lower() for d in entries}
        local = self._shared_values()
        by_path = {m.path.lower(): m for m in self._metas.values()}
        for p, entry in self._disk_entries.items():
            m = by_path.get(p)
            if m is None:
                continue
            disk = self._disk_values(entry, disk_id_path)
            snap = self._snap.get(p)
            for f in SHARED_FIELDS:
                if snap is not None and local[p][f] != snap[f]:
                    continue            # mudou aqui depois da última sincronização: vale o daqui
                if disk[f] != local[p][f]:
                    setattr(m, f, self._resolve_ref(disk[f], by_path) if f in REF_FIELDS else disk[f])
        self._snap = self._shared_values()

    def _new_meta(self, rel: str, used_ids: set[str]) -> DocMeta:
        """Arquivo novo na pasta. Se ele veio de outro aparelho, usa o id e os favoritos de lá."""
        entry = self._disk_entries.get(rel.lower())
        if not entry:
            return DocMeta(path=rel)
        kwargs = {f: entry.get(f) for f in SHARED_FIELDS if entry.get(f) is not None}
        mid = entry.get("id")
        if mid and mid not in used_ids:
            kwargs["id"] = mid
            used_ids.add(mid)
        try:
            return DocMeta(path=rel, **kwargs)
        except TypeError:
            return DocMeta(path=rel)

    def save_meta(self) -> None:
        self._sync_disk()
        local = {m.path.lower() for m in self._metas.values()}
        rows = [asdict(m) for m in sorted(self._metas.values(), key=lambda m: m.path)]
        # Arquivos que outro aparelho registrou e que ainda não chegaram aqui pela nuvem: ficam no arquivo.
        rows += [e for p, e in self._disk_entries.items() if p not in local and p not in self._known]
        data = json.dumps(rows, ensure_ascii=False, indent=1)
        tmp = self.meta_file.with_name("library.json.part")
        try:
            self.meta_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, self.meta_file)
        except OSError:
            return
        self._disk_stamp = self._stamp()
        self._set_disk(rows)
        self._known |= local
        self._snap = self._shared_values()

    def update(self, id: str, **changes) -> None:
        meta = self._metas.get(id)
        if meta is None:
            return
        for k, v in changes.items():
            setattr(meta, k, v)
        self.save_meta()
        self._changed()

    def set_favorite(self, item: PDFItem, value: bool) -> None:
        self.update(item.id, favorite=value)

    def set_pending_ocr(self, item: PDFItem, value: bool) -> None:
        self.update(item.id, pending_ocr=value)

    def mark_opened(self, item: PDFItem) -> None:
        self.update(item.id, last_opened=time.time())

    # --- caminhos ---
    def folder_path(self, rel: str) -> Path:
        return self.root / rel if rel else self.root

    def rel_of(self, full: Path) -> str:
        return os.path.relpath(full, self.root).replace(os.sep, "/")

    def unique_path(self, folder: str, base: str) -> Path:
        d = self.folder_path(folder)
        clean = sanitize(base)
        cand = d / f"{clean}.pdf"
        n = 2
        while cand.exists():
            cand = d / f"{clean} ({n}).pdf"
            n += 1
        return cand

    def temp_path(self, name: str | None = None) -> Path:
        return self.temp_dir / f"{name or uuid.uuid4().hex}.pdf"

    # --- pastas ---
    def create_folder(self, name: str, parent: str = "") -> str:
        clean = sanitize(name)
        path = f"{parent}/{clean}" if parent else clean
        full = self.folder_path(path)
        if full.exists():
            raise UserError(f"Já existe uma pasta chamada “{clean}”.")
        full.mkdir(parents=True)
        self.reload()
        return path

    def rename_folder(self, path: str, new_name: str) -> str:
        clean = sanitize(new_name)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        new_path = f"{parent}/{clean}" if parent else clean
        if new_path == path:
            return path
        if self.folder_path(new_path).exists() and new_path.lower() != path.lower():
            raise UserError(f"Já existe uma pasta chamada “{clean}”.")
        os.rename(self.folder_path(path), self.folder_path(new_path))
        prefix = path + "/"
        for m in self._metas.values():
            if m.path.startswith(prefix):
                m.path = new_path + "/" + m.path[len(prefix):]
        self.save_meta()
        self.reload()
        return new_path

    def delete_folder(self, path: str) -> None:
        if not path:
            return
        _remove_to_trash(self.folder_path(path))
        self.reload()

    # --- arquivos ---
    def rename(self, item: PDFItem, new_name: str) -> None:
        clean = sanitize(new_name)
        dest = item.path.with_name(f"{clean}.pdf")
        if dest == item.path:
            return
        if dest.exists() and str(dest).lower() != str(item.path).lower():
            raise UserError(f"Já existe um PDF chamado “{clean}” nesta pasta.")
        os.rename(item.path, dest)
        item.meta.path = self.rel_of(dest)
        self.save_meta()
        self.reload()

    def move(self, items: list[PDFItem], folder: str) -> None:
        for it in items:
            if it.folder == folder:
                continue
            dest = self.unique_path(folder, it.name)
            shutil.move(str(it.path), str(dest))
            it.meta.path = self.rel_of(dest)
        self.save_meta()
        self.reload()

    def delete(self, items: list[PDFItem]) -> None:
        for it in items:
            _remove_to_trash(it.path)
        self.reload()

    def duplicate(self, item: PDFItem) -> PDFItem | None:
        dest = self.unique_path(item.folder, f"{item.name} (cópia)")
        shutil.copy2(item.path, dest)
        return self.register(dest)

    def copy_into(self, items: list[PDFItem], folder: str) -> list[PDFItem]:
        """Copia PDFs da biblioteca para outra pasta (o original continua onde estava)."""
        rels = []
        for it in items:
            dest = self.unique_path(folder, it.name)
            shutil.copy2(it.path, dest)
            meta = DocMeta(path=self.rel_of(dest), favorite=False, text_status=it.meta.text_status,
                           page_count=it.meta.page_count, ocr_pages=it.meta.ocr_pages,
                           is_ocr_result=it.meta.is_ocr_result)
            self._metas[meta.id] = meta
            rels.append(meta.path)
        self.save_meta()
        self.reload()
        return [i for i in (self.item_by_path(r) for r in rels) if i]

    def import_files(self, paths: list[str | Path], folder: str = "") -> list[PDFItem]:
        rels = []
        for p in paths:
            p = Path(p)
            if p.suffix.lower() != ".pdf" or not p.is_file():
                continue
            dest = self.unique_path(folder, p.stem)
            shutil.copy2(p, dest)
            rels.append(self.rel_of(dest))
        self.reload()
        return [i for i in (self.item_by_path(r) for r in rels) if i]

    def register(self, full: Path, **meta_fields) -> PDFItem | None:
        """Registra um arquivo recém-gravado dentro da biblioteca."""
        meta = DocMeta(path=self.rel_of(full), **meta_fields)
        self._metas[meta.id] = meta
        self.save_meta()
        self.reload()
        return self.item(meta.id)

    def adopt(self, tmp: Path, name: str, folder: str, **meta_fields) -> PDFItem:
        """Move um arquivo pronto (ex.: resultado do OCR) para a biblioteca."""
        dest = self.unique_path(folder, name)
        shutil.move(str(tmp), str(dest))
        item = self.register(dest, **meta_fields)
        if item is None:
            raise UserError("O arquivo foi salvo, mas não apareceu na biblioteca.")
        return item

    def update_after_ocr(self, original: PDFItem, result: PDFItem,
                         review_pages: list[int], confidence: float | None) -> None:
        o, r = self._metas.get(original.id), self._metas.get(result.id)
        if o:
            o.pending_ocr = False
            o.ocr_copy_id = result.id
        if r:
            r.is_ocr_result = True
            r.source_id = original.id
            r.review_pages = review_pages
            r.ocr_confidence = confidence
        self.save_meta()
        self._changed()

    # --- alterar o próprio arquivo (com "Desfazer") ---
    def modify(self, item: PDFItem, change, keep_review: bool = False):
        """
        `change(caminho)` altera o arquivo. Antes, guarda a versão atual para o Desfazer.
        Devolve o que `change` devolver. `keep_review`: a mudança não mexe no texto das páginas
        (destaques, por exemplo), então o aviso de revisão do OCR continua valendo.
        """
        backup = self.versions_dir / f"{item.id}.pdf"
        work = self.temp_path()
        shutil.copy2(item.path, work)
        try:
            result = change(work)
            shutil.copy2(item.path, backup)
            _replace(work, item.path)
        finally:
            work.unlink(missing_ok=True)
        meta = self._metas.get(item.id)
        if meta:
            meta.has_undo = True
            meta.signature = None
            if not keep_review:
                meta.review_pages = None   # depois de mudar as páginas, o relatório do OCR deixa de valer
        self.save_meta()
        self.reload()
        return result

    def can_undo(self, item: PDFItem) -> bool:
        return item.meta.has_undo and (self.versions_dir / f"{item.id}.pdf").exists()

    def undo(self, item: PDFItem) -> None:
        backup = self.versions_dir / f"{item.id}.pdf"
        if not backup.exists():
            raise UserError("Não há alteração para desfazer.")
        os.replace(backup, item.path)
        os.utime(item.path, None)
        self.update(item.id, has_undo=False, signature=None)
        self.reload()


def _replace(src: Path, dest: Path, tries: int = 12) -> None:
    """os.replace com novas tentativas: no Windows, o arquivo pode estar aberto por um instante
    (miniatura sendo gerada, antivírus, sincronização da nuvem)."""
    for k in range(tries):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.1)


def _hide(path: Path) -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass


def _remove_to_trash(path: Path) -> None:
    """No Windows, manda para a Lixeira (dá para recuperar). Em outros sistemas, apaga."""
    if os.name == "nt":
        try:
            _recycle_windows(path)
        except Exception:
            # Nunca apaga de vez sem avisar: a tela promete que dá para recuperar na Lixeira.
            raise UserError(f"Não foi possível mandar “{path.name}” para a Lixeira do Windows. "
                            "Feche o arquivo em outros programas e tente de novo.") from None
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _recycle_windows(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path.resolve()) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0 or path.exists():
        raise OSError("Falha ao mandar para a Lixeira")
