"""
Backup da biblioteca, sem interface.

- `cloud_folders`: pastas do OneDrive, Google Drive, iCloud Drive e Dropbox neste computador.
  Colocar a biblioteca dentro de uma delas já dá backup automático na nuvem escolhida.
- `make_copy`: cópia de segurança completa (PDFs, pastas e favoritos) numa pasta comum,
  por exemplo num pendrive ou HD externo. Nada de formato próprio: é uma pasta normal.
- `restore`: traz de volta uma cópia (ou qualquer pasta com PDFs, ou um .zip) para a
  biblioteca, sem duplicar arquivos que já existem, e recupera os favoritos.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

META_DIR = ".prumo"


# --- Nuvens -------------------------------------------------------------------

def _dropbox_paths() -> list[Path]:
    out = []
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
        if not base:
            continue
        info = Path(base) / "Dropbox" / "info.json"
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for acc in data.values():
            if isinstance(acc, dict) and acc.get("path"):
                out.append(Path(acc["path"]))
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    out.append(home / "Dropbox")
    return out


def _google_drive_paths() -> list[Path]:
    out = []
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    out += [home / "Google Drive", home / "Meu Drive", home / "My Drive"]
    if os.name == "nt":
        for letter in "GHIJKLMNOPQRSTUVWXYZ":
            for name in ("Meu Drive", "My Drive"):
                out.append(Path(f"{letter}:/{name}"))
    return out


def cloud_folders() -> list[tuple[str, Path]]:
    """Nuvens encontradas neste computador: [(nome, pasta)]."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    cands: list[tuple[str, Path]] = []
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v:
            cands.append(("OneDrive", Path(v)))
    cands += [("Google Drive", p) for p in _google_drive_paths()]
    cands.append(("iCloud Drive", home / "iCloudDrive"))
    cands += [("Dropbox", p) for p in _dropbox_paths()]
    out, seen = [], set()
    for name, p in cands:
        try:
            if p.is_dir():
                key = str(p.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    out.append((name, p))
        except OSError:
            continue
    return out


# Onde instalar o aplicativo de cada nuvem e entrar na conta. Endereços citados pelas próprias
# empresas (páginas de ajuda do Google, Apple, Microsoft e Dropbox, conferidas em 28/10/2026).
CLOUD_APPS = [
    {"name": "iCloud Drive", "app": "iCloud para Windows",
     "url": "https://www.microsoft.com/store/apps/9PKTQ5699M62",
     "iphone": "Sincroniza com o Prumo do iPhone (recomendado para quem usa iPhone)."},
    {"name": "Google Drive", "app": "Google Drive para computador",
     "url": "https://support.google.com/drive/answer/10838124",
     "iphone": "No iPhone, o app do Google Drive não deixa outros apps usarem uma pasta dele: lá, os PDFs "
               "abrem pelo app Arquivos, um de cada vez."},
    {"name": "OneDrive", "app": "OneDrive (já vem no Windows 11)",
     "url": "https://www.microsoft.com/microsoft-365/onedrive/download",
     "iphone": "No iPhone, o app do OneDrive não deixa outros apps usarem uma pasta dele: lá, os PDFs "
               "abrem pelo app Arquivos, um de cada vez."},
    {"name": "Dropbox", "app": "Dropbox para computador",
     "url": "https://www.dropbox.com/install",
     "iphone": "No iPhone, funciona se o app do Dropbox deixar escolher a pasta no app Arquivos."},
]


def cloud_app(name: str) -> dict | None:
    return next((c for c in CLOUD_APPS if c["name"] == name), None)


def onedrive_exe() -> Path | None:
    """O OneDrive instalado (abrir o programa mostra a tela de entrar na conta)."""
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not base:
            continue
        for sub in (("Microsoft", "OneDrive", "OneDrive.exe"), ("Microsoft OneDrive", "OneDrive.exe")):
            p = Path(base).joinpath(*sub)
            if p.is_file():
                return p
    return None


def merge_move(old_root: Path, library) -> tuple[int, int]:
    """Junta a biblioteca antiga com uma que já está na nuvem (de outro aparelho).

    Os PDFs vão para a nova pasta nas mesmas subpastas, os iguais não são duplicados e os favoritos
    vêm junto. Só depois que tudo está lá os arquivos da pasta antiga são apagados.
    Devolve (PDFs trazidos, PDFs que já estavam lá).
    """
    old_root = Path(old_root)
    res = restore(old_root, library)
    for p in sorted(old_root.rglob("*.pdf")):
        if META_DIR in p.relative_to(old_root).parts:
            continue
        if find_same_file(p, library) is None:
            from pdfops import UserError
            raise UserError(f"“{p.name}” não chegou à nova pasta. Nada foi apagado da pasta antiga.")
    for p in sorted(old_root.rglob("*.pdf")):
        if META_DIR not in p.relative_to(old_root).parts:
            p.unlink()
    shutil.rmtree(old_root / META_DIR, ignore_errors=True)
    for d in sorted((d for d in old_root.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        try:
            d.rmdir()            # só as pastas que ficaram vazias
        except OSError:
            pass
    return res.added, res.skipped


def cloud_of(path: Path, clouds: list[tuple[str, Path]] | None = None) -> str | None:
    """Nome da nuvem que sincroniza esta pasta (ou None, se for só deste computador)."""
    try:
        target = Path(path).resolve()
    except OSError:
        return None
    for name, p in (clouds if clouds is not None else cloud_folders()):
        try:
            base = p.resolve()
        except OSError:
            continue
        if target == base or base in target.parents:
            return name
    return None


# --- Cópia de segurança -------------------------------------------------------------

def _count_pdfs(root: Path) -> int:
    return sum(1 for p in root.rglob("*.pdf") if META_DIR not in p.parts)


def make_copy(library_root: Path, dest_dir: Path) -> tuple[Path, int]:
    """Copia a biblioteca inteira para "Prumo PDF - cópia AAAA-MM-DD HHhMM" dentro de `dest_dir`."""
    library_root, dest_dir = Path(library_root), Path(dest_dir)
    try:
        if dest_dir.resolve() == library_root.resolve() or library_root.resolve() in dest_dir.resolve().parents:
            from pdfops import UserError
            raise UserError("Escolha um lugar fora da pasta da biblioteca (por exemplo, um pendrive).")
    except OSError:
        pass
    name = time.strftime("Prumo PDF - cópia %Y-%m-%d %Hh%M")
    target = dest_dir / name
    n = 2
    while target.exists():
        target = dest_dir / f"{name} ({n})"
        n += 1
    shutil.copytree(library_root, target, ignore=shutil.ignore_patterns("*.part", "~$*"))
    return target, _count_pdfs(target)


@dataclass
class RestoreResult:
    added: int = 0
    skipped: int = 0          # já estavam na biblioteca (mesmo conteúdo)
    favorites: int = 0


def _digest(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zip(src: Path) -> Path:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="prumo_restore_"))
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:   # nada fora da pasta temporária
                continue
            z.extract(info, tmp)
    return tmp


def restore(source: Path, library) -> RestoreResult:
    """Traz os PDFs de uma cópia para a biblioteca, mantendo as pastas e sem duplicar."""
    source = Path(source)
    cleanup = None
    if source.is_file() and source.suffix.lower() == ".zip":
        source = cleanup = _extract_zip(source)
    try:
        res = RestoreResult()
        root = library.root
        # o que já existe, por tamanho → conteúdo (só calcula o conteúdo quando o tamanho bate)
        by_size: dict[int, list[Path]] = {}
        for it in library.items:
            by_size.setdefault(it.size, []).append(it.path)
        digests: dict[Path, str] = {}

        def exists_already(p: Path) -> bool:
            same = by_size.get(p.stat().st_size, [])
            if not same:
                return False
            d = _digest(p)
            for q in same:
                if q not in digests:
                    digests[q] = _digest(q)
                if digests[q] == d:
                    return True
            return False

        favorites = set()
        meta = source / META_DIR / "library.json"
        try:
            for d in json.loads(meta.read_text(encoding="utf-8")):
                if isinstance(d, dict) and d.get("favorite") and d.get("path"):
                    favorites.add(str(d["path"]).replace("\\", "/").lower())
        except (OSError, ValueError, TypeError):
            pass

        new_favorites = []
        for p in sorted(source.rglob("*")):
            if not p.is_file() or p.suffix.lower() != ".pdf" or META_DIR in p.relative_to(source).parts:
                continue
            rel = p.relative_to(source)
            if exists_already(p):
                res.skipped += 1
                continue
            folder = "/".join(rel.parts[:-1])
            (root / folder).mkdir(parents=True, exist_ok=True) if folder else None
            dest = library.unique_path(folder, p.stem)
            shutil.copy2(p, dest)
            by_size.setdefault(dest.stat().st_size, []).append(dest)
            res.added += 1
            if rel.as_posix().lower() in favorites:
                new_favorites.append(library.rel_of(dest))
        library.reload()
        for rel in new_favorites:
            it = library.item_by_path(rel)
            if it is not None:
                library.set_favorite(it, True)
                res.favorites += 1
        return res
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)


def find_same_file(path: Path, library):
    """PDF da biblioteca com o mesmo conteúdo deste arquivo (para não importar duas vezes)."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return None
    same = [it for it in library.items if it.size == size]
    if not same:
        return None
    d = _digest(path)
    for it in same:
        try:
            if _digest(it.path) == d:
                return it
        except OSError:
            continue
    return None
