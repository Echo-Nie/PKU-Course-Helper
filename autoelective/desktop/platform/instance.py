"""Native lifetime leases shared with the current-user installer."""
import ctypes

APP_MUTEX = 'Local\\PKUAutoElectiveDesktop'
MAINTENANCE_MUTEX = 'Local\\PKUAutoElectiveMaintenance'


def acquire_instance():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, APP_MUTEX)
    existed = ctypes.get_last_error() == 183
    if not handle:
        raise RuntimeError('无法创建本机工作空间，请重新打开程序')
    # Advertise the application lease before testing maintenance. The installer
    # advertises maintenance before testing the app lease, closing the startup race.
    maintenance = kernel.OpenMutexW(0x100000, False, MAINTENANCE_MUTEX)
    maintenance_error = ctypes.get_last_error()
    if maintenance:
        kernel.CloseHandle(maintenance)
        kernel.CloseHandle(handle)
        raise RuntimeError('安装或卸载正在进行，请完成后再打开PKUCourseHelper。')
    if maintenance_error != 2:  # Only ERROR_FILE_NOT_FOUND means no maintenance.
        kernel.CloseHandle(handle)
        raise RuntimeError('无法确认安装维护状态，请关闭安装或卸载窗口后重试。')
    if existed:
        kernel.CloseHandle(handle)
        user = ctypes.WinDLL('user32')
        user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user.FindWindowW.restype = ctypes.c_void_p
        user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        window = user.FindWindowW(None, 'PKUCourseHelper')
        if window:
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
        return None, kernel
    return handle, kernel
