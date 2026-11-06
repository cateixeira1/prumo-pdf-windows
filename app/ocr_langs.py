"""Idiomas do OCR (Tesseract): lista, o que está instalado e como juntar vários numa execução só."""

from __future__ import annotations

from pathlib import Path

import core

# (código do Tesseract, nome no próprio idioma). Ordem da lista na tela.
LANGS: list[tuple[str, str]] = [
    ("por", "Português"),
    ("eng", "English"),
    ("spa", "Español"),
    ("fra", "Français"),
    ("deu", "Deutsch"),
    ("jpn", "日本語"),
    ("chi_sim", "中文 (简体)"),
    ("chi_tra", "中文 (繁體, 台灣)"),
    ("nor", "Norsk"),
    ("swe", "Svenska"),
    ("dan", "Dansk"),
    ("fin", "Suomi"),
]
NAMES = dict(LANGS)
MAX_LANGS = 4          # o Tesseract fica lento e impreciso com muitos idiomas juntos
# Idioma do OCR quando o usuário ainda não escolheu: o mesmo do aplicativo.
_BY_UI = {"pt": "por", "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "ja": "jpn", "zh-CN": "chi_sim",
          "zh-TW": "chi_tra", "nb": "nor", "sv": "swe", "da": "dan", "fi": "fin"}


def default() -> str:
    try:
        import i18n
        code = _BY_UI.get(i18n.current(), "eng")
    except Exception:
        code = "por"
    try:
        have = installed()
    except Exception:
        return code
    return code if code in have else (have[0] if have else "por")


def installed(max_precision: bool = False) -> list[str]:
    """Códigos cujo modelo acompanha o aplicativo ."""
    d = core.tessdata_dir(False)
    if d is None:
        return ["por"]
    return [c for c, _ in LANGS if (d / f"{c}.traineddata").exists()]


def parse(value: str | None) -> list[str]:
    out = []
    for c in (value or default()).split("+"):
        c = c.strip()
        if c in NAMES and c not in out:
            out.append(c)
    return out or [default()]


def join(codes: list[str]) -> str:
    seen: list[str] = []
    for c in codes:
        if c in NAMES and c not in seen:
            seen.append(c)
    return "+".join(seen[:MAX_LANGS]) or default()


def resolve(value: str | None, max_precision: bool = False) -> tuple[Path | None, str]:
    """
    Pasta de modelos e texto de idiomas para o Tesseract. Os modelos “best” existem só para alguns idiomas;
    se faltar algum, usa os modelos padrão para não falhar.
    """
    codes = [c for c in parse(value) if c in installed()] or [default()]
    std = core.tessdata_dir(False)
    if max_precision:
        best = core.tessdata_dir(True)
        if best is not None and all((best / f"{c}.traineddata").exists() for c in codes):
            return best, join(codes)
    return std, join(codes)
