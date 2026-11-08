"""
Certificado A1 guardado no Windows, com a chave privada protegida.

Antes (até a 1.14), o Prumo guardava uma cópia do arquivo .pfx na pasta de dados e pedia a senha do arquivo a
cada assinatura. Um programa malicioso na mesma conta podia copiar o arquivo e capturar a senha pelo teclado:
com os dois, assinaria como o titular em qualquer computador até o certificado ser revogado.

Agora o Prumo entrega a chave ao Windows (CNG) e não guarda o arquivo:
- a chave fica marcada como NÃO exportável (o Windows recusa exportá-la; Export Policy = 0);
- com chip TPM, ela vai para o chip ("Microsoft Platform Crypto Provider"): nunca fica exposta ao sistema
  nem a outros programas; todas as operações com a chave acontecem dentro do TPM;
- sem TPM, fica no armazenamento de chaves do Windows ("Microsoft Software Key Storage Provider");
- com proteção forte (padrão), o Windows pede uma senha própria da chave a cada uso, numa janela do Windows
  (NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG). Nem todo TPM aceita essa proteção; quando não aceita, a chave vai
  para o TPM sem ela (continua sem poder sair do computador) e o Prumo diz isso ao usuário.

O certificado (parte pública) vai para "Certificados – Usuário Atual > Pessoal", ligado à chave. A assinatura
é feita aqui mesmo, pelo NCryptSignHash, para a janela de senha do Windows abrir sobre a janela do Prumo.

Só funciona no Windows. Tudo por ctypes (ncrypt.dll e crypt32.dll), sem PowerShell e sem passar a senha
por linha de comando.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from dataclasses import dataclass, field

SOFTWARE = "Microsoft Software Key Storage Provider"
PLATFORM = "Microsoft Platform Crypto Provider"
KEY_PREFIX = "Prumo PDF A1 "

# ncrypt.h
NCRYPT_SILENT_FLAG = 0x40
NCRYPT_OVERWRITE_KEY_FLAG = 0x80
NCRYPT_DO_NOT_FINALIZE_FLAG = 0x400
NCRYPT_PERSIST_FLAG = 0x80000000
NCRYPT_ALLOW_EXPORT_FLAG = 0x1
NCRYPT_ALLOW_PLAINTEXT_EXPORT_FLAG = 0x2
NCRYPT_ALLOW_SIGNING_FLAG = 0x2
NCRYPT_UI_PROTECT_KEY_FLAG = 0x1
NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG = 0x2
NCRYPT_IMPL_HARDWARE_FLAG = 0x1
NCRYPTBUFFER_PKCS_KEY_NAME = 45
BCRYPT_PAD_PKCS1 = 0x2
NTE_BAD_KEYSET = -2146893802          # 0x80090016: a chave não existe
# wincrypt.h
X509_ASN_ENCODING = 0x1
PKCS_7_ASN_ENCODING = 0x10000
CERT_STORE_PROV_SYSTEM_W = 10
CERT_SYSTEM_STORE_CURRENT_USER = 0x10000
CERT_STORE_ADD_REPLACE_EXISTING = 3
CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_FRIENDLY_NAME_PROP_ID = 11
CERT_FIND_SHA1_HASH = 0x10000


class WinCertError(Exception):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


@dataclass
class Imported:
    thumbprint: str          # SHA-1 do certificado, em maiúsculas (como o Windows mostra)
    key_name: str
    provider: str
    hardware: bool           # a chave está num chip (TPM)
    protected: bool          # o Windows pede a senha da chave a cada uso
    attempts: list[str] = field(default_factory=list)   # o que foi tentado antes (para diagnóstico)


def available() -> bool:
    return os.name == "nt"


# --- ctypes ---------------------------------------------------------------------------------

_api = None


def _lib():
    global _api
    if _api is not None:
        return _api
    from ctypes import wintypes as W

    H = ctypes.c_size_t                         # NCRYPT_HANDLE (ULONG_PTR)
    S = ctypes.c_long                           # SECURITY_STATUS
    nc = ctypes.WinDLL("ncrypt.dll")
    c32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)

    def f(lib, name, res, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, list(args)
        return fn

    class NCryptBuffer(ctypes.Structure):
        _fields_ = [("cbBuffer", W.ULONG), ("BufferType", W.ULONG), ("pvBuffer", ctypes.c_void_p)]

    class NCryptBufferDesc(ctypes.Structure):
        _fields_ = [("ulVersion", W.ULONG), ("cBuffers", W.ULONG), ("pBuffers", ctypes.POINTER(NCryptBuffer))]

    class UiPolicy(ctypes.Structure):
        _fields_ = [("dwVersion", W.DWORD), ("dwFlags", W.DWORD), ("pszCreationTitle", W.LPCWSTR),
                    ("pszFriendlyName", W.LPCWSTR), ("pszDescription", W.LPCWSTR)]

    class Pkcs1Padding(ctypes.Structure):
        _fields_ = [("pszAlgId", W.LPCWSTR)]

    class KeyProvInfo(ctypes.Structure):
        _fields_ = [("pwszContainerName", W.LPWSTR), ("pwszProvName", W.LPWSTR), ("dwProvType", W.DWORD),
                    ("dwFlags", W.DWORD), ("cProvParam", W.DWORD), ("rgProvParam", ctypes.c_void_p),
                    ("dwKeySpec", W.DWORD)]

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", W.DWORD), ("pbData", ctypes.c_void_p)]

    P = ctypes.POINTER
    api = {
        "NCryptBuffer": NCryptBuffer, "NCryptBufferDesc": NCryptBufferDesc, "UiPolicy": UiPolicy,
        "Pkcs1Padding": Pkcs1Padding, "KeyProvInfo": KeyProvInfo, "DataBlob": DataBlob, "H": H,
        "open_provider": f(nc, "NCryptOpenStorageProvider", S, P(H), W.LPCWSTR, W.DWORD),
        "import_key": f(nc, "NCryptImportKey", S, H, H, W.LPCWSTR, P(NCryptBufferDesc), P(H), ctypes.c_void_p,
                        W.DWORD, W.DWORD),
        "set_property": f(nc, "NCryptSetProperty", S, H, W.LPCWSTR, ctypes.c_void_p, W.DWORD, W.DWORD),
        "get_property": f(nc, "NCryptGetProperty", S, H, W.LPCWSTR, ctypes.c_void_p, W.DWORD, P(W.DWORD),
                          W.DWORD),
        "finalize": f(nc, "NCryptFinalizeKey", S, H, W.DWORD),
        "open_key": f(nc, "NCryptOpenKey", S, H, P(H), W.LPCWSTR, W.DWORD, W.DWORD),
        "delete_key": f(nc, "NCryptDeleteKey", S, H, W.DWORD),
        "free": f(nc, "NCryptFreeObject", S, H),
        "sign_hash": f(nc, "NCryptSignHash", S, H, ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.c_void_p,
                       W.DWORD, P(W.DWORD), W.DWORD),
        "cert_create": f(c32, "CertCreateCertificateContext", ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD),
        "cert_free": f(c32, "CertFreeCertificateContext", W.BOOL, ctypes.c_void_p),
        "store_open": f(c32, "CertOpenStore", ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD,
                        ctypes.c_void_p),
        "store_close": f(c32, "CertCloseStore", W.BOOL, ctypes.c_void_p, W.DWORD),
        "store_add": f(c32, "CertAddCertificateContextToStore", W.BOOL, ctypes.c_void_p, ctypes.c_void_p, W.DWORD,
                       P(ctypes.c_void_p)),
        "set_cert_prop": f(c32, "CertSetCertificateContextProperty", W.BOOL, ctypes.c_void_p, W.DWORD, W.DWORD,
                           ctypes.c_void_p),
        "find": f(c32, "CertFindCertificateInStore", ctypes.c_void_p, ctypes.c_void_p, W.DWORD, W.DWORD, W.DWORD,
                  ctypes.c_void_p, ctypes.c_void_p),
        "delete_cert": f(c32, "CertDeleteCertificateFromStore", W.BOOL, ctypes.c_void_p),
    }
    _api = api
    return api


def _check(status: int, what: str) -> None:
    if status != 0:
        raise WinCertError(f"{what}: 0x{status & 0xFFFFFFFF:08X}", status)


def _open_provider(name: str) -> int:
    a = _lib()
    h = a["H"]()
    _check(a["open_provider"](ctypes.byref(h), name, 0), f"open {name}")
    return h.value


def _set_dword(handle: int, prop: str, value: int, flags: int = 0) -> int:
    from ctypes import wintypes as W
    v = W.DWORD(value)
    return _lib()["set_property"](handle, prop, ctypes.byref(v), ctypes.sizeof(v), flags)


def _get_dword(handle: int, prop: str) -> int | None:
    from ctypes import wintypes as W
    v, n = W.DWORD(0), W.DWORD(0)
    st = _lib()["get_property"](handle, prop, ctypes.byref(v), ctypes.sizeof(v), ctypes.byref(n), NCRYPT_SILENT_FLAG)
    return v.value if st == 0 else None


def _set_window(handle: int, hwnd: int | None) -> None:
    if hwnd:
        h = ctypes.c_void_p(hwnd)
        _lib()["set_property"](handle, "HWND Handle", ctypes.byref(h), ctypes.sizeof(h), 0)


# --- blobs da chave ------------------------------------------------------------------------

def _pkcs8(key) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    return key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())


def _rsa_private_blob(key) -> bytes | None:
    """BCRYPT_RSAKEY_BLOB com os primos (BCRYPT_RSAPRIVATE_MAGIC), para provedores que não aceitam PKCS#8."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not isinstance(key, rsa.RSAPrivateKey):
        return None
    import struct
    n = key.private_numbers()
    pub = n.public_numbers

    def be(x: int) -> bytes:
        return x.to_bytes((x.bit_length() + 7) // 8, "big")
    e, mod, p, q = be(pub.e), be(pub.n), be(n.p), be(n.q)
    head = struct.pack("<6I", 0x32415352, key.key_size, len(e), len(mod), len(p), len(q))
    return head + e + mod + p + q


# --- importar -------------------------------------------------------------------------------

def _try_import(provider: str, key_name: str, key, protect: bool, hwnd: int | None,
                title: str, description: str) -> tuple[bool, bool]:
    """Importa a chave num provedor. Devolve (está em hardware, protegida). Falha → WinCertError, sem sobras."""
    a = _lib()
    prov = _open_provider(provider)
    hkey = 0
    try:
        _set_window(prov, hwnd)
        name = ctypes.create_unicode_buffer(key_name)
        buf = a["NCryptBuffer"](ctypes.sizeof(name), NCRYPTBUFFER_PKCS_KEY_NAME, ctypes.cast(name, ctypes.c_void_p))
        desc = a["NCryptBufferDesc"](0, 1, ctypes.pointer(buf))
        last = None
        blobs = [("PKCS8_PRIVATEKEY", _pkcs8(key))]
        rsa_blob = _rsa_private_blob(key)
        if rsa_blob is not None:
            blobs.append(("RSAPRIVATEBLOB", rsa_blob))
        for blob_type, blob in blobs:
            h = a["H"]()
            data = ctypes.create_string_buffer(blob, len(blob))
            st = a["import_key"](prov, 0, blob_type, ctypes.byref(desc), ctypes.byref(h), data, len(blob),
                                 NCRYPT_OVERWRITE_KEY_FLAG | NCRYPT_DO_NOT_FINALIZE_FLAG)
            ctypes.memset(data, 0, len(blob))           # a cópia da chave na memória do Prumo some logo
            if st == 0:
                hkey = h.value
                break
            last = st
        if not hkey:
            _check(last or -1, f"import into {provider}")
        _set_window(hkey, hwnd)
        _check(_set_dword(hkey, "Export Policy", 0, NCRYPT_PERSIST_FLAG), "set Export Policy")
        _set_dword(hkey, "Key Usage", NCRYPT_ALLOW_SIGNING_FLAG, NCRYPT_PERSIST_FLAG)   # só assinatura (se aceitar)
        if protect:
            pol = a["UiPolicy"](1, NCRYPT_UI_PROTECT_KEY_FLAG | NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG,
                                title, key_name, description)
            _check(a["set_property"](hkey, "UI Policy", ctypes.byref(pol), ctypes.sizeof(pol), NCRYPT_PERSIST_FLAG),
                   "set UI Policy")
        _check(a["finalize"](hkey, 0), "finalize key")
        impl = _get_dword(hkey, "Impl Type") or 0
        exp = _get_dword(hkey, "Export Policy")
        if exp is None or exp & (NCRYPT_ALLOW_EXPORT_FLAG | NCRYPT_ALLOW_PLAINTEXT_EXPORT_FLAG):
            raise WinCertError("key is exportable")
        return bool(impl & NCRYPT_IMPL_HARDWARE_FLAG), protect
    except BaseException:
        if hkey:
            # Importou pela metade: não deixa a chave para trás. Sem finalizar, ela nem chegou a ser gravada.
            if a["delete_key"](hkey, 0) != 0:
                a["free"](hkey)
            hkey = 0
        raise
    finally:
        if hkey:
            a["free"](hkey)
        a["free"](prov)


def _delete_key_by_name(prov: int, key_name: str) -> bool:
    a = _lib()
    h = a["H"]()
    if a["open_key"](prov, ctypes.byref(h), key_name, 0, NCRYPT_SILENT_FLAG) != 0:
        return False
    return a["delete_key"](h.value, 0) == 0        # libera o handle


def import_pfx(data: bytes, password: str, protect: bool = True, hwnd: int | None = None,
               use_tpm: bool = True, title: str = "Prumo PDF", description: str = "") -> Imported:
    """
    Guarda o certificado A1 no Windows. Ordem: TPM com senha da chave; TPM sem ela; Windows com senha da chave;
    Windows sem ela (este último só se `protect` for False ou se as outras falharem). Erro só se nada der certo.
    """
    if not available():
        raise WinCertError("Windows only")
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
    key, cert, _others = pkcs12.load_key_and_certificates(data, password.encode("utf-8") if password else None)
    if key is None or cert is None:
        raise WinCertError("no private key in the file")
    der = cert.public_bytes(Encoding.DER)
    thumb = hashlib.sha1(der).hexdigest().upper()
    key_name = KEY_PREFIX + thumb
    plan = []
    if use_tpm:
        plan += [(PLATFORM, True), (PLATFORM, False)] if protect else [(PLATFORM, False)]
    plan += [(SOFTWARE, True), (SOFTWARE, False)] if protect else [(SOFTWARE, False)]
    attempts: list[str] = []
    for provider, prot in plan:
        try:
            hardware, protected = _try_import(provider, key_name, key, prot, hwnd, title, description)
        except WinCertError as exc:
            attempts.append(f"{provider}{' + UI policy' if prot else ''}: {exc}")
            continue
        try:
            _add_to_store(der, provider, key_name, "Prumo PDF")
        except WinCertError:
            delete_key(provider, key_name)
            raise
        return Imported(thumb, key_name, provider, hardware, protected, attempts)
    raise WinCertError("; ".join(attempts) or "no key storage provider accepted the key")


def _add_to_store(der: bytes, provider: str, key_name: str, friendly: str) -> None:
    a = _lib()
    enc = X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
    raw = ctypes.create_string_buffer(der, len(der))
    ctx = a["cert_create"](enc, raw, len(der))
    if not ctx:
        raise WinCertError("invalid certificate", ctypes.get_last_error())
    store = a["store_open"](ctypes.c_void_p(CERT_STORE_PROV_SYSTEM_W), 0, None, CERT_SYSTEM_STORE_CURRENT_USER, "MY")
    if not store:
        a["cert_free"](ctx)
        raise WinCertError("open CurrentUser\\My", ctypes.get_last_error())
    added = ctypes.c_void_p()
    try:
        if not a["store_add"](store, ctx, CERT_STORE_ADD_REPLACE_EXISTING, ctypes.byref(added)):
            raise WinCertError("add certificate to CurrentUser\\My", ctypes.get_last_error())
        container = ctypes.create_unicode_buffer(key_name)
        prov = ctypes.create_unicode_buffer(provider)
        info = a["KeyProvInfo"](ctypes.cast(container, ctypes.c_wchar_p), ctypes.cast(prov, ctypes.c_wchar_p),
                                0, 0, 0, None, 0)
        if not a["set_cert_prop"](added, CERT_KEY_PROV_INFO_PROP_ID, 0, ctypes.byref(info)):
            err = ctypes.get_last_error()
            a["delete_cert"](added)
            added = ctypes.c_void_p()
            raise WinCertError("set CERT_KEY_PROV_INFO", err)
        name = ctypes.create_unicode_buffer(friendly)
        blob = a["DataBlob"](ctypes.sizeof(name), ctypes.cast(name, ctypes.c_void_p))
        a["set_cert_prop"](added, CERT_FRIENDLY_NAME_PROP_ID, 0, ctypes.byref(blob))
    finally:
        if added:
            a["cert_free"](added)
        a["cert_free"](ctx)
        a["store_close"](store, 0)


# --- usar e remover -----------------------------------------------------------------------

def delete_key(provider: str, key_name: str) -> bool:
    if not available():
        return False
    a = _lib()
    try:
        prov = _open_provider(provider)
    except WinCertError:
        return False
    try:
        return _delete_key_by_name(prov, key_name)
    finally:
        a["free"](prov)


def remove(thumbprint: str, provider: str, key_name: str) -> None:
    """Apaga a chave e tira o certificado de "Pessoal"."""
    delete_key(provider, key_name)
    if not available():
        return
    a = _lib()
    store = a["store_open"](ctypes.c_void_p(CERT_STORE_PROV_SYSTEM_W), 0, None, CERT_SYSTEM_STORE_CURRENT_USER, "MY")
    if not store:
        return
    try:
        h = bytes.fromhex(thumbprint)
        raw = ctypes.create_string_buffer(h, len(h))
        blob = a["DataBlob"](len(h), ctypes.cast(raw, ctypes.c_void_p))
        ctx = a["find"](store, X509_ASN_ENCODING | PKCS_7_ASN_ENCODING, 0, CERT_FIND_SHA1_HASH, ctypes.byref(blob), None)
        if ctx:
            a["delete_cert"](ctx)            # também libera o contexto
    finally:
        a["store_close"](store, 0)


def key_state(provider: str, key_name: str) -> dict | None:
    """{"exportable", "hardware", "protected"} da chave, ou None se ela não existe mais."""
    if not available():
        return None
    a = _lib()
    try:
        prov = _open_provider(provider)
    except WinCertError:
        return None
    try:
        h = a["H"]()
        if a["open_key"](prov, ctypes.byref(h), key_name, 0, NCRYPT_SILENT_FLAG) != 0:
            return None
        try:
            exp = _get_dword(h.value, "Export Policy")
            impl = _get_dword(h.value, "Impl Type") or 0
            from ctypes import wintypes as W
            buf = ctypes.create_string_buffer(2048)     # a estrutura vem seguida dos textos da janela
            n = W.DWORD(0)
            st = a["get_property"](h.value, "UI Policy", buf, 2048, ctypes.byref(n), NCRYPT_SILENT_FLAG)
            ui_flags = int.from_bytes(buf.raw[4:8], "little") if st == 0 and n.value >= 8 else 0
            return {"exportable": exp is None or bool(exp & (NCRYPT_ALLOW_EXPORT_FLAG | NCRYPT_ALLOW_PLAINTEXT_EXPORT_FLAG)),
                    "hardware": bool(impl & NCRYPT_IMPL_HARDWARE_FLAG),
                    "protected": bool(ui_flags & NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG)}
        finally:
            a["free"](h.value)
    finally:
        a["free"](prov)


def sign_digest(provider: str, key_name: str, digest: bytes, rsa: bool, hwnd: int | None = None) -> bytes:
    """
    Assina o resumo SHA-256. RSA: PKCS#1 v1.5. ECDSA: devolve r||s (o chamador converte para DER).
    Com proteção forte, o Windows abre a janela pedindo a senha da chave (sobre a janela `hwnd`).
    """
    from ctypes import wintypes as W
    a = _lib()
    prov = _open_provider(provider)
    try:
        _set_window(prov, hwnd)
        h = a["H"]()
        st = a["open_key"](prov, ctypes.byref(h), key_name, 0, 0)
        if st == NTE_BAD_KEYSET:
            raise WinCertError("key not found", st)
        _check(st, "open key")
        try:
            _set_window(h.value, hwnd)
            pad = a["Pkcs1Padding"]("SHA256") if rsa else None
            pp = ctypes.byref(pad) if rsa else None
            flags = BCRYPT_PAD_PKCS1 if rsa else 0
            src = ctypes.create_string_buffer(digest, len(digest))
            n = W.DWORD(0)
            _check(a["sign_hash"](h.value, pp, src, len(digest), None, 0, ctypes.byref(n), flags), "sign")
            out = ctypes.create_string_buffer(n.value)
            _check(a["sign_hash"](h.value, pp, src, len(digest), out, n.value, ctypes.byref(n), flags), "sign")
            return out.raw[:n.value]
        finally:
            a["free"](h.value)
    finally:
        a["free"](prov)


# Códigos do Windows que querem dizer "o usuário cancelou a janela" (SCARD_W_CANCELLED_BY_USER, ERROR_CANCELLED)
# e NTE_USER_CANCELLED
CANCELLED = {-2146434962, -2147023673, -2146893770}
