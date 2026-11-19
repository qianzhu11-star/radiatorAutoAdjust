"""An app-owned Windows event lets a second launch reopen the existing window."""
import ctypes
from ctypes import wintypes

SHOW_EVENT = "Local\\BS2ProGameGearShowWindow"


def kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


class ShowRequest:
    def __init__(self, name=SHOW_EVENT):
        self.kernel = kernel_api()
        self.handle = self.kernel.CreateEventW(None, False, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def requested(self):
        return self.handle is not None and self.kernel.WaitForSingleObject(self.handle, 0) == 0

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def request_show(name=SHOW_EVENT):
    kernel = kernel_api()
    handle = kernel.OpenEventW(2, False, name)  # EVENT_MODIFY_STATE
    if not handle:
        return False
    try:
        return bool(kernel.SetEvent(handle))
    finally:
        kernel.CloseHandle(handle)
