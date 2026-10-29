"""
Assinatura digital de PDF (PAdES), sem interface.

Certificados aceitos:
- A1 em arquivo (.pfx ou .p12): o Prumo guarda uma cópia do arquivo nesta conta do Windows
  (pasta de dados do Prumo, fora da biblioteca e da nuvem). A senha não é guardada: o Prumo
  pede a senha a cada assinatura.
- Certificados do Windows: A1 instalado no Windows e A3 em token ou cartão (com o programa do
  token instalado, o certificado aparece em "Certificados – Usuário Atual > Pessoal"). A chave não
  sai do token: o Windows (e o programa do token, que pede o PIN) faz a assinatura.

Formato: PAdES (SubFilter ETSI.CAdES.detached), o mesmo que o Adobe Acrobat gera e que o Adobe
Reader e outros leitores reconhecem. A primeira assinatura é de certificação (DocMDP, "só
preenchimento de formulários e novas assinaturas"); as seguintes travam os campos (FieldMDP).
O verificador do ITI (validar.iti.gov.br) exige DocMDP ou FieldMDP: sem eles, o resultado é
"indeterminado".

Depois de assinado, o PDF não pode mais ser alterado: qualquer mudança no arquivo invalida a
assinatura. Por isso o Prumo assina uma cópia ("Nome - assinado.pdf"), e o original continua
editável. Um PDF já assinado recebe as novas assinaturas no próprio arquivo, sem mudar o resto.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pdfops import UserError

SUFFIX = " - assinado"
POSITIONS = {
    "bottom_left": "Embaixo, à esquerda",
    "bottom_right": "Embaixo, à direita",
    "top_right": "Em cima, à direita",
}
PAGES = {"last": "Última página", "first": "Primeira página"}
STAMP_W, STAMP_H = 230, 48


# --- certificados ----------------------------------------------------------------------

@dataclass
class CertInfo:
    id: str                  # "file:<sha1>" ou "win:<impressão digital>"
    kind: str                # "file" (A1 salvo no Prumo) ou "windows" (A1 instalado ou A3)
    name: str                # nome do titular (sem o CPF/CNPJ que a ICP-Brasil põe no fim)
    subject: str
    issuer: str
    not_before: datetime
    not_after: datetime
    doc: str = ""            # CPF ou CNPJ, quando o certificado traz
    path: Path | None = None
    thumbprint: str = ""
    der: bytes = b""
    chain: list[bytes] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) > self.not_after

    @property
    def label(self) -> str:
        tipo = "A1 salvo no Prumo" if self.kind == "file" else "Windows (A1 instalado ou A3)"
        return f"{self.name} · {tipo} · válido até {self.not_after.astimezone().strftime('%d/%m/%Y')}"


def cert_dir() -> Path:
    custom = os.environ.get("PRUMO_CERT_DIR")
    if custom:
        return Path(custom)
    from library import local_data_dir
    return local_data_dir() / "Certificados"


def _name_of(cert) -> tuple[str, str]:
    """(nome, CPF/CNPJ) a partir do CN: na ICP-Brasil, "NOME DA PESSOA:12345678900"."""
    from cryptography.x509.oid import NameOID
    cn = ""
    for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        cn = str(a.value)
    if not cn:
        cn = cert.subject.rfc4514_string()
    m = re.match(r"^(.*?):(\d{11}|\d{14})$", cn.strip())
    return (m.group(1).strip(), m.group(2)) if m else (cn.strip(), "")


def _info_from_der(der: bytes, kind: str, chain: list[bytes] | None = None, **kw) -> CertInfo:
    from cryptography import x509
    cert = x509.load_der_x509_certificate(der)
    name, doc = _name_of(cert)
    return CertInfo(
        id=kw.pop("id"), kind=kind, name=name, doc=doc,
        subject=cert.subject.rfc4514_string(), issuer=cert.issuer.rfc4514_string(),
        not_before=cert.not_valid_before_utc, not_after=cert.not_valid_after_utc,
        der=der, chain=list(chain or []), **kw)


def _usable_for_signing(der: bytes) -> bool:
    """Certificado com uso de chave para assinatura (ou sem restrição declarada)."""
    from cryptography import x509
    cert = x509.load_der_x509_certificate(der)
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        return bool(ku.digital_signature or ku.content_commitment)
    except x509.ExtensionNotFound:
        return True


def _load_pfx(data: bytes, password: str):
    """(chave, certificado, outros certificados) de um .pfx; erro claro se a senha não confere."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    try:
        key, cert, others = pkcs12.load_key_and_certificates(data, password.encode("utf-8") if password else None)
    except ValueError:
        raise UserError("Senha do certificado incorreta (ou o arquivo não é um certificado .pfx/.p12).") from None
    if key is None or cert is None:
        raise UserError("O arquivo não tem a chave do certificado. Use o arquivo .pfx/.p12 do certificado A1.")
    return key, cert, list(others or [])


def import_a1(src: str | Path, password: str) -> CertInfo:
    """Confere a senha e guarda uma cópia do certificado A1 para assinar depois."""
    from cryptography.hazmat.primitives.serialization import Encoding
    data = Path(src).read_bytes()
    _key, cert, others = _load_pfx(data, password)
    der = cert.public_bytes(Encoding.DER)
    if not _usable_for_signing(der):
        raise UserError("Este certificado não serve para assinatura digital.")
    key = hashlib.sha1(der).hexdigest()
    d = cert_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.pfx").write_bytes(data)
    info = _info_from_der(der, "file", [o.public_bytes(Encoding.DER) for o in others], id=f"file:{key}",
                          path=d / f"{key}.pfx")
    (d / f"{key}.json").write_text(json.dumps({"der": base64.b64encode(der).decode(),
                                               "chain": [base64.b64encode(c).decode() for c in info.chain]}),
                                   encoding="utf-8")
    return info


def saved_certificates() -> list[CertInfo]:
    out = []
    d = cert_dir()
    if not d.exists():
        return out
    for meta in sorted(d.glob("*.json")):
        pfx = meta.with_suffix(".pfx")
        if not pfx.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            der = base64.b64decode(data["der"])
            chain = [base64.b64decode(c) for c in data.get("chain", [])]
            out.append(_info_from_der(der, "file", chain, id=f"file:{meta.stem}", path=pfx))
        except (OSError, ValueError, KeyError):
            continue
    return out


def remove_certificate(info: CertInfo) -> None:
    if info.kind != "file" or info.path is None:
        raise UserError("Certificados do Windows são removidos pelo Windows (certmgr.msc) ou pelo programa do token.")
    info.path.unlink(missing_ok=True)
    info.path.with_suffix(".json").unlink(missing_ok=True)


# --- certificados do Windows (A1 instalado e A3) ------------------------------------------

_PS_LIST = r"""
$ErrorActionPreference = 'Stop'
$out = @()
foreach ($c in Get-ChildItem Cert:\CurrentUser\My) {
  if (-not $c.HasPrivateKey) { continue }
  $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
  $chain.ChainPolicy.RevocationMode = 'NoCheck'
  [void]$chain.Build($c)
  $certs = @()
  foreach ($el in $chain.ChainElements) { if ($el.Certificate.Thumbprint -ne $c.Thumbprint) { $certs += [Convert]::ToBase64String($el.Certificate.RawData) } }
  $out += [pscustomobject]@{ thumb = $c.Thumbprint; der = [Convert]::ToBase64String($c.RawData); chain = $certs }
}
ConvertTo-Json -InputObject @($out) -Depth 4 -Compress
"""

_PS_SIGN = r"""
$ErrorActionPreference = 'Stop'
$data = [Convert]::FromBase64String([Console]::In.ReadToEnd().Trim())
$c = Get-Item ('Cert:\CurrentUser\My\' + $env:PRUMO_THUMB)
$h = [System.Security.Cryptography.HashAlgorithmName]::SHA256
$rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($c)
if ($rsa -ne $null) {
  $sig = $rsa.SignData($data, $h, [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
  Write-Output ('RSA ' + [Convert]::ToBase64String($sig))
} else {
  $ec = [System.Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($c)
  $sig = $ec.SignData($data, $h)
  Write-Output ('EC ' + [Convert]::ToBase64String($sig))
}
"""


def _powershell(script: str, stdin: str = "", env: dict | None = None, timeout: int = 180) -> str:
    if sys.platform != "win32":
        raise UserError("Os certificados do Windows só existem no Windows.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    e = dict(os.environ)
    e.update(env or {})
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", script], input=stdin, capture_output=True, text=True, timeout=timeout,
                           creationflags=flags, env=e)
    except subprocess.TimeoutExpired:
        raise UserError("O Windows demorou demais para responder (o token está conectado?).") from None
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        detail = next((m for m in msg if m.strip()), "erro desconhecido")
        raise UserError(f"O Windows não conseguiu usar o certificado: {detail[:300]}")
    return r.stdout


def windows_certificates() -> list[CertInfo]:
    """Certificados com chave privada em "Pessoal" (A1 instalado no Windows e A3 em token/cartão)."""
    if sys.platform != "win32":
        return []
    raw = _powershell(_PS_LIST).strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    if isinstance(items, dict):
        items = [items]
    out = []
    for it in items or []:
        try:
            der = base64.b64decode(it["der"])
            if not _usable_for_signing(der):
                continue
            chain = [base64.b64decode(c) for c in (it.get("chain") or [])]
            out.append(_info_from_der(der, "windows", chain, id=f"win:{it['thumb']}", thumbprint=it["thumb"]))
        except (KeyError, ValueError):
            continue
    return out


def all_certificates() -> list[CertInfo]:
    found = saved_certificates()
    try:
        found += windows_certificates()
    except UserError:
        pass
    # o mesmo certificado salvo no Prumo e instalado no Windows aparece uma vez (o do Windows)
    seen = {hashlib.sha1(c.der).hexdigest() for c in found if c.kind == "windows"}
    return [c for c in found if c.kind == "windows" or c.id.split(":", 1)[1] not in seen]


def _p1363_to_der(sig: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    n = len(sig) // 2
    return encode_dss_signature(int.from_bytes(sig[:n], "big"), int.from_bytes(sig[n:], "big"))


def windows_sign_raw(thumbprint: str, data: bytes) -> tuple[str, bytes]:
    out = _powershell(_PS_SIGN, base64.b64encode(data).decode(), {"PRUMO_THUMB": thumbprint}).strip()
    line = out.splitlines()[-1] if out else ""
    kind, _, b64 = line.partition(" ")
    if kind not in ("RSA", "EC") or not b64:
        raise UserError("O Windows não devolveu a assinatura.")
    sig = base64.b64decode(b64)
    return kind, (_p1363_to_der(sig) if kind == "EC" else sig)


# --- assinantes do pyHanko ------------------------------------------------------------------

def _asn1(der: bytes):
    from asn1crypto import x509 as ax
    return ax.Certificate.load(der)


def _key_algo(der: bytes) -> tuple[str, int]:
    """("rsa" ou "ecdsa", tamanho da assinatura em bytes)."""
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    pub = x509.load_der_x509_certificate(der).public_key()
    if isinstance(pub, rsa.RSAPublicKey):
        return "rsa", (pub.key_size + 7) // 8
    if isinstance(pub, ec.EllipticCurvePublicKey):
        return "ecdsa", 2 * ((pub.curve.key_size + 7) // 8) + 9
    raise UserError("Tipo de chave do certificado não suportado (use RSA ou ECDSA).")


def file_signer(info: CertInfo, password: str):
    from asn1crypto import keys
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from pyhanko.sign.signers import SimpleSigner
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    if info.path is None or not info.path.exists():
        raise UserError("O arquivo do certificado não foi encontrado. Adicione o certificado de novo nos Ajustes.")
    key, cert, others = _load_pfx(info.path.read_bytes(), password)
    der = cert.public_bytes(Encoding.DER)
    pkey = keys.PrivateKeyInfo.load(key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption()))
    chain = [_asn1(o.public_bytes(Encoding.DER)) for o in others] + [_asn1(c) for c in info.chain]
    return SimpleSigner(signing_cert=_asn1(der), signing_key=pkey,
                        cert_registry=SimpleCertificateStore.from_certs(chain))


def windows_signer(info: CertInfo):
    from asn1crypto import algos
    from pyhanko.sign.signers.pdf_cms import Signer
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    algo, size = _key_algo(info.der)

    class _WindowsSigner(Signer):
        async def async_sign_raw(self, data, digest_algorithm, dry_run=False):
            if dry_run:
                return bytes(size)
            if digest_algorithm.lower() != "sha256":
                raise UserError("Resumo criptográfico não suportado.")
            _kind, sig = windows_sign_raw(info.thumbprint, data)
            return sig

    mech = algos.SignedDigestAlgorithm({"algorithm": "sha256_rsa" if algo == "rsa" else "sha256_ecdsa"})
    return _WindowsSigner(signing_cert=_asn1(info.der), signature_mechanism=mech,
                          cert_registry=SimpleCertificateStore.from_certs([_asn1(c) for c in info.chain]))


# --- PDF ---------------------------------------------------------------------------------

def _fields(pdf):
    acro = pdf.Root.get("/AcroForm")
    if acro is None:
        return []
    out, stack = [], list(acro.get("/Fields", []) or [])
    while stack:
        f = stack.pop()
        try:
            out.append(f)
            stack.extend(f.get("/Kids", []) or [])
        except Exception:  # noqa: BLE001
            continue
    return out


def signature_count(path) -> int:
    """Quantas assinaturas digitais o PDF tem (0 se não tem, ou se não abre sem senha)."""
    import pikepdf
    try:
        with pikepdf.open(str(path)) as pdf:
            return sum(1 for f in _fields(pdf) if f.get("/FT") == "/Sig" and "/V" in f)
    except Exception:  # noqa: BLE001
        return 0


def docmdp_level(path) -> int | None:
    """Permissão da assinatura de certificação (1: nenhuma mudança; 2: formulários e assinaturas)."""
    import pikepdf
    try:
        with pikepdf.open(str(path)) as pdf:
            perms = pdf.Root.get("/Perms")
            ref = perms.get("/DocMDP") if perms is not None else None
            if ref is None:
                return None
            for r in ref.get("/Reference", []) or []:
                if r.get("/TransformMethod") == "/DocMDP":
                    return int(r.get("/TransformParams", {}).get("/P", 2))
            return 2
    except Exception:  # noqa: BLE001
        return None


def _stamp_box(path, page_choice: str, position: str, index: int) -> tuple[int, tuple[int, int, int, int]]:
    """(página, caixa no espaço do PDF) para o carimbo número `index` (0 = primeiro)."""
    import pikepdf

    import pdfops
    with pikepdf.open(str(path)) as pdf:
        n = len(pdf.pages)
        p = n - 1 if page_choice == "last" else 0
        page = pdf.pages[p].obj
        crop = pdfops._box(page, "/CropBox")
        rot = pdfops._rotation(page)
    x0, y0, x1, y1 = crop
    w, h = (x1 - x0, y1 - y0) if rot in (0, 180) else (y1 - y0, x1 - x0)
    step = index * (STAMP_H + 6)
    if position == "bottom_right":
        dx, dy = w - 36 - STAMP_W, h - 28 - STAMP_H - step
    elif position == "top_right":
        dx, dy = w - 36 - STAMP_W, 28 + step
    else:
        dx, dy = 36, h - 28 - STAMP_H - step
    corners = [pdfops._display_to_user(crop, rot, dx, dy), pdfops._display_to_user(crop, rot, dx + STAMP_W, dy + STAMP_H)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return p, (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


@dataclass
class SignOptions:
    stamp: bool = True
    page: str = "last"
    position: str = "bottom_left"
    reason: str = ""
    location: str = ""


def sign_file(src, dest, signer, name: str, options: SignOptions) -> None:
    """Assina `src` e grava em `dest` (atualização incremental: o conteúdo de antes fica intacto)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.text import TextBoxStyle
    from pyhanko.sign import fields, signers
    from pyhanko.sign.fields import FieldMDPAction, FieldMDPSpec, MDPPerm, SigFieldSpec, SigSeedSubFilter
    from pyhanko.pdf_utils.font.basic import SimpleFontEngineFactory
    from pyhanko.stamp import TextStampStyle

    import pdfops
    if pdfops.is_encrypted(src):
        raise UserError("PDF com senha não pode ser assinado. Remova a senha antes (“Remover senha”).")
    count = signature_count(src)
    level = docmdp_level(src)
    if level == 1:
        raise UserError("A primeira assinatura deste PDF não permite mais nenhuma mudança, nem novas assinaturas.")
    field_name = f"Assinatura{count + 1}"
    while True:
        try:
            import pikepdf
            with pikepdf.open(str(src)) as pdf:
                names = {str(f.get("/T", "")) for f in _fields(pdf)}
        except Exception:  # noqa: BLE001
            names = set()
        if field_name not in names:
            break
        count += 1
        field_name = f"Assinatura{count + 1}"
    page, box = _stamp_box(src, options.page, options.position, count) if options.stamp else (0, None)
    spec = SigFieldSpec(sig_field_name=field_name, on_page=page, box=box,
                        field_mdp_spec=FieldMDPSpec(FieldMDPAction.ALL) if count else None,
                        doc_mdp_update_value=MDPPerm.FILL_FORMS if count else None)
    meta = signers.PdfSignatureMetadata(
        field_name=field_name, md_algorithm="sha256", subfilter=SigSeedSubFilter.PADES,
        certify=count == 0, docmdp_permissions=MDPPerm.FILL_FORMS,
        reason=options.reason or None, location=options.location or None, name=name or None)
    style = None
    if options.stamp:
        safe = (name or "").replace("%", "%%")
        style = TextStampStyle(
            stamp_text=f"Assinado digitalmente por\n{safe}\nem %(ts)s",
            timestamp_format="%d/%m/%Y %H:%M:%S",
            border_width=1,
            text_box_style=TextBoxStyle(font=SimpleFontEngineFactory("Helvetica", 0.5), font_size=8, leading=10),
            background=None)
    pdf_signer = signers.PdfSigner(meta, signer, stamp_style=style, new_field_spec=spec)
    tmp = Path(str(dest) + ".part")
    with open(src, "rb") as inf:
        w = IncrementalPdfFileWriter(inf, strict=False)
        with open(tmp, "wb") as out:
            pdf_signer.sign_pdf(w, output=out, bytes_reserved=24000)
    os.replace(tmp, dest)
    _ = fields  # (import usado só para deixar claro de onde vêm os tipos)


def signed_name(item) -> str:
    return f"{item.name}{SUFFIX}"


def sign_item(lib, item, signer, name: str, options: SignOptions):
    """
    Assina um PDF da biblioteca. PDF sem assinatura: cria "Nome - assinado.pdf" (o original
    continua editável). PDF já assinado: acrescenta a nova assinatura no próprio arquivo.
    Devolve o PDF assinado.
    """
    if item.meta.locked:
        raise UserError("PDF com senha não pode ser assinado. Remova a senha antes (“Remover senha”).")
    already = signature_count(item.path) > 0
    tmp = lib.temp_path()
    try:
        sign_file(item.path, tmp, signer, name, options)
        if already:
            lib.modify(item, lambda path: shutil.copyfile(tmp, path), keep_review=True)
            result = lib.item(item.id) or item
        else:
            dest = lib.unique_path(item.folder, signed_name(item))
            shutil.move(str(tmp), str(dest))
            result = lib.register(dest)
            if result is None:
                raise UserError("O PDF assinado foi salvo, mas não apareceu na biblioteca.")
    finally:
        Path(tmp).unlink(missing_ok=True)
    lib.update(result.id, signed=signature_count(result.path))
    return lib.item(result.id) or result


def describe_signatures(path) -> list[dict]:
    """Quem assinou e quando (sem validar a cadeia): para mostrar nos detalhes do PDF."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    out = []
    try:
        with open(path, "rb") as f:
            r = PdfFileReader(f, strict=False)
            for s in r.embedded_signatures:
                cert = s.signer_cert
                cn = cert.subject.native.get("common_name", "") if cert is not None else ""
                m = re.match(r"^(.*?):(\d{11}|\d{14})$", str(cn))
                when = s.self_reported_timestamp
                out.append({"name": m.group(1) if m else str(cn),
                            "when": when.astimezone().strftime("%d/%m/%Y %H:%M") if when else "",
                            "field": s.field_name})
    except Exception:  # noqa: BLE001
        return []
    return out
