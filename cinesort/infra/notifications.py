"""Win32 balloon notification wrapper via Shell_NotifyIconW.

Zero external dependencies — uses ctypes + stdlib only.
Falls back silently on non-Windows platforms.
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys
import threading

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# --- Win32 constants --------------------------------------------------------

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003
NIIF_NOSOUND = 0x00000010

# Shell_NotifyIconW expects NOTIFYICONDATAW (V2 minimum for balloon).
# We use the V2 layout: up to szInfo[256], szInfoTitle[64], dwInfoFlags.
_NOTIFYICONDATA_FMT = "".join(
    [
        "I",  # cbSize (DWORD)
        "P",  # hWnd (HWND)
        "I",  # uID (UINT)
        "I",  # uFlags (UINT)
        "I",  # uCallbackMessage (UINT)
        "P",  # hIcon (HICON)
        "128s",  # szTip[64] in WCHAR = 128 bytes
        "I",  # dwState (DWORD)
        "I",  # dwStateMask (DWORD)
        "512s",  # szInfo[256] in WCHAR = 512 bytes
        "I",  # uTimeoutOrVersion (UINT) — union, use version=3 for modern
        "128s",  # szInfoTitle[64] in WCHAR = 128 bytes
        "I",  # dwInfoFlags (DWORD)
    ]
)

_STRUCT_SIZE = struct.calcsize(_NOTIFYICONDATA_FMT)
_NOTIFY_UID = 99  # arbitrary unique ID for our icon

_lock = threading.Lock()
_icon_added = False


def _encode_wstr(text: str, max_chars: int) -> bytes:
    """Encode text as null-terminated UTF-16LE, truncated to max_chars."""
    truncated = text[: max_chars - 1]
    encoded = truncated.encode("utf-16-le")
    return encoded.ljust(max_chars * 2, b"\x00")


def _get_console_hwnd() -> int:
    """Get a usable HWND. We use the desktop window as a fallback."""
    try:
        return ctypes.windll.user32.GetDesktopWindow()
    except (AttributeError, OSError):
        return 0


def _get_default_icon() -> int:
    """Load the default application icon."""
    try:
        return ctypes.windll.user32.LoadIconW(0, 32512)  # IDI_APPLICATION
    except (AttributeError, OSError):
        return 0


def _build_nid(title: str, message: str, icon_flag: int = NIIF_INFO) -> bytes:
    """Build a NOTIFYICONDATAW struct for a balloon notification."""
    hwnd = _get_console_hwnd()
    hicon = _get_default_icon()
    flags = NIF_ICON | NIF_TIP | NIF_INFO

    return struct.pack(
        _NOTIFYICONDATA_FMT,
        _STRUCT_SIZE,  # cbSize
        hwnd,  # hWnd
        _NOTIFY_UID,  # uID
        flags,  # uFlags
        0,  # uCallbackMessage
        hicon,  # hIcon
        _encode_wstr("CineSort", 64),  # szTip
        0,  # dwState
        0,  # dwStateMask
        _encode_wstr(message, 256),  # szInfo
        3,  # uTimeoutOrVersion (NOTIFYICON_VERSION)
        _encode_wstr(title, 64),  # szInfoTitle
        icon_flag,  # dwInfoFlags
    )


def show_balloon(title: str, message: str, level: str = "info") -> bool:
    """Show a Windows balloon notification. Non-blocking, thread-safe.

    Args:
        title: Notification title (max 63 chars).
        message: Notification body (max 255 chars).
        level: 'info', 'warning', or 'error'.

    Returns True if shown, False on failure or non-Windows.
    """
    if not _IS_WINDOWS:
        return False

    icon_flag = {
        "info": NIIF_INFO,
        "warning": NIIF_WARNING,
        "error": NIIF_ERROR,
    }.get(level, NIIF_INFO)

    try:
        shell32 = ctypes.windll.shell32
        nid = _build_nid(title, message, icon_flag)

        with _lock:
            global _icon_added
            if not _icon_added:
                shell32.Shell_NotifyIconW(NIM_ADD, nid)
                _icon_added = True
            shell32.Shell_NotifyIconW(NIM_MODIFY, nid)
        return True
    except (AttributeError, OSError, ValueError) as exc:
        logger.debug("Balloon notification failed: %s", exc)
        return False


def cleanup() -> None:
    """Remove the notification icon from the tray. Call at app shutdown."""
    if not _IS_WINDOWS:
        return
    global _icon_added
    with _lock:
        if not _icon_added:
            return
        try:
            hwnd = _get_console_hwnd()
            hicon = _get_default_icon()
            nid = struct.pack(
                _NOTIFYICONDATA_FMT,
                _STRUCT_SIZE,
                hwnd,
                _NOTIFY_UID,
                NIF_ICON,
                0,
                hicon,
                _encode_wstr("", 64),
                0,
                0,
                _encode_wstr("", 256),
                0,
                _encode_wstr("", 64),
                0,
            )
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, nid)
        except (AttributeError, OSError):
            pass
        _icon_added = False
