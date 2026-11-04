"""
Perfil do computador onde o Prumo está rodando: processadores, memória e energia.

O Prumo não foi feito para um computador específico. Ele mede a máquina na hora (leva menos de
1 ms, sem gravar nem enviar nada) e decide quanto pode usar sem deixar o computador lento:

  - quantas páginas o OCR lê ao mesmo tempo (núcleos, memória livre e bateria);
  - quanta memória as páginas do leitor e as miniaturas podem ocupar;
  - quantos núcleos a correção de páginas curvas usa;
  - quanto espaço em disco o cache de miniaturas pode ocupar.

Os núcleos não mudam com o computador ligado e são lidos uma vez; memória livre e bateria são lidas
de novo a cada decisão (por exemplo, ao começar um OCR).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache

MB = 1024 * 1024
GB = 1024 * MB

# Memória usada por página que o OCR lê ao mesmo tempo. Medido com o Tesseract 5 numa página A4 a
# 300 dpi: pico de 76 MB com o modelo padrão e 97 MB com o de precisão máxima; com a imagem ampliada
# (precisão máxima), 182 MB. Somam-se a imagem da página e os arquivos intermediários do OCRmyPDF.
OCR_MB_PER_PAGE = 250
OCR_MB_PER_PAGE_MAX = 400


@dataclass(frozen=True)
class Machine:
    logical: int            # processadores lógicos que o Prumo pode usar
    physical: int           # núcleos físicos
    total_ram: int          # bytes (0 = não foi possível medir)
    avail_ram: int          # bytes livres agora (0 = não foi possível medir)
    on_battery: bool        # notebook fora da tomada
    battery_saver: bool     # "Economia de bateria" do Windows ligada

    def describe(self) -> str:
        ram = f"{self.total_ram / GB:.0f} GB de memória ({self.avail_ram / GB:.1f} GB livres)" if self.total_ram else "memória desconhecida"
        power = "na bateria" + (" (economia ligada)" if self.battery_saver else "") if self.on_battery else "na tomada"
        return f"{self.physical} núcleos, {self.logical} processadores lógicos, {ram}, {power}"


# --- Medidas -------------------------------------------------------------------------------------

def _logical() -> int:
    fn = getattr(os, "process_cpu_count", None)       # Python 3.13+: respeita a afinidade do processo
    if fn is not None:
        n = fn()
    elif hasattr(os, "sched_getaffinity"):
        n = len(os.sched_getaffinity(0))
    else:
        n = os.cpu_count()
    return max(1, int(n or 1))


def _physical_windows() -> int | None:
    import ctypes
    import struct
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k.GetLogicalProcessorInformationEx
    fn.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    size = wintypes.DWORD(0)
    fn(0, None, ctypes.byref(size))                    # 0 = RelationProcessorCore; pergunta o tamanho
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not fn(0, buf, ctypes.byref(size)):
        return None
    raw, off, cores = buf.raw[:size.value], 0, 0
    while off + 8 <= len(raw):
        rel, rec = struct.unpack_from("<II", raw, off)
        if rec == 0:
            break
        if rel == 0:
            cores += 1
        off += rec
    return cores or None


def _physical_linux() -> int | None:
    try:
        cores, phys, core = set(), None, None
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                key, _, val = line.partition(":")
                key = key.strip()
                if key == "physical id":
                    phys = val.strip()
                elif key == "core id":
                    core = val.strip()
                elif not line.strip():
                    if core is not None:
                        cores.add((phys, core))
                    phys = core = None
        if core is not None:
            cores.add((phys, core))
        return len(cores) or None
    except OSError:
        return None


@lru_cache(maxsize=1)
def _cpus() -> tuple[int, int]:
    logical = _logical()
    physical = None
    try:
        physical = _physical_windows() if sys.platform == "win32" else _physical_linux()
    except Exception:  # noqa: BLE001  (sem a informação: usa os lógicos)
        physical = None
    physical = max(1, min(logical, physical or logical))
    return logical, physical


def _memory() -> tuple[int, int]:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys), int(st.ullAvailPhys)
        except Exception:  # noqa: BLE001
            pass
        return 0, 0
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0]) * 1024
        return info.get("MemTotal", 0), info.get("MemAvailable", info.get("MemFree", 0))
    except (OSError, ValueError, IndexError):
        return 0, 0


def _power() -> tuple[bool, bool]:
    """(na bateria, economia de bateria ligada). Computador de mesa: (False, False)."""
    if sys.platform != "win32":
        return False, False
    try:
        import ctypes
        from ctypes import wintypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

        st = SYSTEM_POWER_STATUS()
        if not ctypes.WinDLL("kernel32").GetSystemPowerStatus(ctypes.byref(st)):
            return False, False
        has_battery = st.BatteryFlag not in (128, 255)        # 128 = sem bateria; 255 = desconhecido
        on_battery = has_battery and st.ACLineStatus == 0     # 0 = fora da tomada
        return on_battery, st.SystemStatusFlag == 1           # 1 = economia de bateria ligada
    except Exception:  # noqa: BLE001
        return False, False


def current() -> Machine:
    """Medida de agora (núcleos lidos uma vez; memória e energia, na hora)."""
    logical, physical = _cpus()
    total, avail = _memory()
    on_battery, saver = _power()
    return Machine(logical, physical, total, avail, on_battery, saver)


# --- Decisões ------------------------------------------------------------------------------------

def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, v)))


def ocr_jobs(max_precision: bool = False, m: Machine | None = None) -> int:
    """
    Quantas páginas o OCR lê ao mesmo tempo.

    - Um processador fica para a janela do Prumo e para os outros programas.
    - Na bateria, no máximo metade dos núcleos físicos (menos calor e menos gasto); com a economia de
      bateria ligada, uma página por vez.
    - Cada página em paralelo precisa de memória livre (ver OCR_MB_PER_PAGE); sobra uma reserva para
      o Windows e os outros programas não começarem a usar o disco como memória.
    O processo do OCR roda com prioridade abaixo do normal (ver lower_priority): se o usuário estiver
    usando outro programa, o Windows dá preferência a ele.
    """
    m = m or current()
    cpu = max(1, m.logical - 1)
    if m.battery_saver:
        cpu = 1
    elif m.on_battery:
        cpu = max(1, min(cpu, m.physical // 2))
    if m.avail_ram:
        per = (OCR_MB_PER_PAGE_MAX if max_precision else OCR_MB_PER_PAGE) * MB
        reserve = max(768 * MB, m.total_ram // 10)
        cpu = min(cpu, max(1, (m.avail_ram - reserve) // per))
    return max(1, int(cpu))


def page_cache_bytes(m: Machine | None = None) -> int:
    """Memória para as páginas já desenhadas no leitor (1/24 da memória do computador, entre 96 e 640 MB)."""
    m = m or current()
    if not m.total_ram:
        return 256 * MB
    budget = _clamp(m.total_ram / 24, 96 * MB, 640 * MB)
    if m.avail_ram and m.avail_ram < 1 * GB:              # computador já apertado: guarda menos
        budget = max(96 * MB, min(budget, m.avail_ram // 8))
    return budget


def thumb_cache_bytes(m: Machine | None = None) -> int:
    """Memória para as miniaturas (1/64 da memória do computador, entre 32 e 256 MB)."""
    m = m or current()
    if not m.total_ram:
        return 96 * MB
    return _clamp(m.total_ram / 64, 32 * MB, 256 * MB)


def thumb_disk_bytes(folder) -> int:
    """Espaço em disco para o cache de miniaturas: 1% do espaço livre, entre 32 e 256 MB."""
    import shutil
    try:
        free = shutil.disk_usage(str(folder)).free
    except OSError:
        return 128 * MB
    return _clamp(free / 100, 32 * MB, 256 * MB)


def onnx_threads(m: Machine | None = None) -> int:
    """Núcleos para a correção de páginas curvas: os físicos, menos um quando há mais de dois."""
    m = m or current()
    return m.physical - 1 if m.physical > 2 else m.physical


def thumb_threads(m: Machine | None = None) -> int:
    """Desenho de miniaturas em paralelo (o PDFium desenha uma de cada vez; o resto é ler e gravar PNG)."""
    m = m or current()
    return 2 if m.logical >= 4 else 1


# --- Prioridade ----------------------------------------------------------------------------------

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def lower_priority() -> bool:
    """
    Põe ESTE processo (o do OCR) com prioridade abaixo do normal. No Windows, os processos que ele abrir
    (o tesseract.exe) herdam essa prioridade. O OCR continua usando o processador inteiro quando ninguém
    mais precisa; quando o usuário está em outro programa, o Windows atende o outro programa primeiro.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetCurrentProcess.restype = wintypes.HANDLE
            k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k.SetPriorityClass.restype = wintypes.BOOL
            return bool(k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
        os.nice(5)
        return True
    except Exception:  # noqa: BLE001
        return False
