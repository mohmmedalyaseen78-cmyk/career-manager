"""Resource governor: keep the game a polite neighbour on a weak shared machine.

- background work runs at LOW OS priority, in small batches, with yields between batches
- worker count is capped (never more than half the logical CPUs, max 2)
- when the window is inactive / system under memory pressure, background work is delayed
- no timers or polling live here: everything is called by explicit game actions
"""
import os
import sys
import time

MODES = {
    "normal": dict(batch_sleep_ms=0, max_workers=2, cache_clubs=48),
    "low": dict(batch_sleep_ms=15, max_workers=1, cache_clubs=16),
}


def logical_cpus():
    return os.cpu_count() or 1


def worker_count(mode="normal"):
    return max(1, min(MODES[mode]["max_workers"], logical_cpus() // 2))


def lower_priority():
    """Put the CURRENT process/thread-pool at below-normal priority (use in background worker)."""
    try:
        if sys.platform == "win32":
            import ctypes
            BELOW_NORMAL = 0x00004000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
        else:
            os.nice(5)
        return True
    except Exception:
        return False


def available_ram_mb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong),
                            ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ap // (1024 * 1024)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


def process_rss_mb():
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("pf", wintypes.DWORD), ("peak", ctypes.c_size_t),
                            ("ws", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                            ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", ctypes.c_size_t),
                            ("pb", ctypes.c_size_t), ("peakpb", ctypes.c_size_t)]
            p = PMC()
            p.cb = ctypes.sizeof(PMC)
            ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p),
                                                     p.cb)
            return p.ws // (1024 * 1024)
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


class Governor:
    """Call `yield_point()` between small batches of background work."""

    def __init__(self, mode="normal", min_free_mb=700):
        self.mode, self.min_free_mb, self.active = mode, min_free_mb, True
        self.pressure_checks = 0

    def set_active(self, active):
        """UI reports window focus/visibility. Inactive => background work slows down a lot."""
        self.active = active

    def under_pressure(self):
        free = available_ram_mb()
        return free is not None and free < self.min_free_mb

    def yield_point(self):
        ms = MODES[self.mode]["batch_sleep_ms"]
        if not self.active:
            ms = max(ms, 50)
        self.pressure_checks += 1
        if self.pressure_checks % 8 == 0 and self.under_pressure():
            ms = max(ms, 120)
        time.sleep(ms / 1000.0 if ms else 0)
