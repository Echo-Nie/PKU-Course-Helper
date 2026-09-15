"""Windows DPAPI file encryption; no registry or Credential Manager access."""
import ctypes
import os
from ctypes import wintypes

from .config_store import atomic_write


def _dpapi(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = None
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = 'PKU AutoElective portable password'
    function.restype = wintypes.BOOL
    # UI_FORBIDDEN: never let a worker display operating-system credential prompts.
    if not function(ctypes.byref(incoming), description, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError('无法解密已保存的密码，请重新输入' if decrypt else '无法安全保存密码')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel32.LocalFree(outgoing.data)
        ctypes.memset(buffer, 0, len(buffer))


class CredentialStore:
    def __init__(self, paths):
        self.paths = paths
        self._password = ''

    def __repr__(self):
        return 'CredentialStore()'

    def load(self):
        if self._password:
            return self._password
        if not self.paths.credentials.exists():
            return ''
        if os.name != 'nt':
            raise RuntimeError('已保存密码仅能在原 Windows 用户下读取，请重新输入')
        try:
            self._password = _dpapi(self.paths.credentials.read_bytes(), decrypt=True).decode('utf-8')
        except (OSError, UnicodeError):
            raise OSError('无法读取已保存的密码，请重新输入') from None
        return self._password

    def save(self, password, remember=False):
        if remember and os.name != 'nt':
            raise RuntimeError('记住密码仅支持 Windows DPAPI；当前平台密码只保存在内存中')
        if remember and password:
            atomic_write(self.paths.credentials, _dpapi(password.encode('utf-8')))
        else:
            self.paths.credentials.unlink(missing_ok=True)
        self._password = password

    def clear(self):
        self.paths.credentials.unlink(missing_ok=True)
        self._password = ''
