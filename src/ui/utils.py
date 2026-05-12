"""
工具方法
"""
import os
import re


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}" if i > 0 else f"{int(size)} {units[i]}"


def format_speed(speed_kbs: float) -> str:
    """格式化速度（输入 KB/s）"""
    if speed_kbs <= 0:
        return "0 KB/s"
    if speed_kbs < 1024:
        return f"{speed_kbs:.1f} KB/s"
    return f"{speed_kbs / 1024:.2f} MB/s"


def format_eta(remaining_bytes: int, speed_kbs: float) -> str:
    """计算剩余时间"""
    if speed_kbs <= 0 or remaining_bytes <= 0:
        return "--:--"
    seconds = remaining_bytes / (speed_kbs * 1024)
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m"


# 文件类型标记。避免 emoji 在 Windows 不同字体/缩放下导致行高和裁切不一致。
FILE_TYPE_ICONS = {
    "folder": "[DIR]",
    "video": "[VID]",
    "audio": "[AUD]",
    "image": "[IMG]",
    "document": "[DOC]",
    "archive": "[ZIP]",
    "code": "[CODE]",
    "other": "[FILE]",
}


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(filename: str) -> str:
    """转换为 Windows 可安全保存的文件名。"""
    name = str(filename or "download").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.rstrip(" .")
    if not name:
        name = "download"

    root, ext = os.path.splitext(name)
    if root.upper() in _WINDOWS_RESERVED_NAMES:
        root = f"_{root}"

    max_len = 180
    if len(root + ext) > max_len:
        root = root[:max(1, max_len - len(ext))]
    return root + ext


def make_unique_save_path(
    directory: str, filename: str, reserved_paths: set[str] = None
) -> str:
    """返回不会覆盖现有文件的保存路径。"""
    reserved_paths = reserved_paths if reserved_paths is not None else set()
    safe_name = sanitize_filename(filename)
    base, ext = os.path.splitext(safe_name)
    candidate = os.path.join(directory, safe_name)
    index = 1
    while (
        os.path.exists(candidate)
        or os.path.normcase(os.path.abspath(candidate)) in reserved_paths
    ):
        candidate = os.path.join(directory, f"{base} ({index}){ext}")
        index += 1
    reserved_paths.add(os.path.normcase(os.path.abspath(candidate)))
    return candidate


def get_file_type(filename: str) -> str:
    """根据文件名判断文件类型"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    video_exts = {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "rmvb", "rm"}
    audio_exts = {"mp3", "flac", "wav", "aac", "ogg", "m4a", "wma", "ape"}
    image_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico", "tiff"}
    doc_exts = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "md"}
    archive_exts = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"}
    code_exts = {"py", "js", "ts", "java", "c", "cpp", "h", "html", "css", "json", "xml"}

    if ext in video_exts:
        return "video"
    elif ext in audio_exts:
        return "audio"
    elif ext in image_exts:
        return "image"
    elif ext in doc_exts:
        return "document"
    elif ext in archive_exts:
        return "archive"
    elif ext in code_exts:
        return "code"
    return "other"
