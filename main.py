"""
PDM - 主入口
"""
import sys
import os

# 确保 src 在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt

__version__ = "2.2.1"


def _append_env_flags(name: str, flags: list[str]) -> None:
    current = os.environ.get(name, "")
    parts = current.split()
    for flag in flags:
        if flag not in parts:
            parts.append(flag)
    os.environ[name] = " ".join(parts).strip()


def _configure_qt_webengine_runtime() -> None:
    """让打包后的 QtWebEngine 明确找到子进程和资源，避免空白或卡死。"""
    _append_env_flags("QTWEBENGINE_CHROMIUM_FLAGS", [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-features=UseSkiaRenderer",
    ])
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

    if not getattr(sys, "frozen", False):
        return

    qt_root = os.path.join(
        os.path.dirname(sys.executable), "_internal", "PyQt5", "Qt5"
    )
    paths = {
        "QTWEBENGINEPROCESS_PATH": os.path.join(
            qt_root, "bin", "QtWebEngineProcess.exe"
        ),
        "QTWEBENGINE_RESOURCES_PATH": os.path.join(qt_root, "resources"),
        "QTWEBENGINE_LOCALES_PATH": os.path.join(
            qt_root, "translations", "qtwebengine_locales"
        ),
    }
    for key, path in paths.items():
        if os.path.exists(path):
            os.environ.setdefault(key, path)


def _exception_hook(exc_type, exc_value, exc_tb):
    """全局异常捕获，防止无控制台时崩溃无提示"""
    from src.core.logger import get_logger
    import traceback
    logger = get_logger()
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical(f"未捕获的异常:\n{tb_text}")
    QMessageBox.critical(None, "程序异常", f"发生未处理的错误:\n\n{exc_value}")


def main():
    _configure_qt_webengine_runtime()

    # 单实例锁（防止多开）
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    _lock_socket = QLocalSocket()
    _lock_socket.connectToServer("PDM_SingleInstance")
    if _lock_socket.waitForConnected(500):
        _lock_socket.close()
        return  # 已有实例在运行

    _lock_server = QLocalServer()
    _lock_server.listen("PDM_SingleInstance")

    # 高DPI支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("PDM")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Pan Download Manager")

    from PyQt5.QtGui import QIcon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
    if getattr(sys, "frozen", False):
        icon_path = os.path.join(os.path.dirname(sys.executable), "_internal", "assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 安装全局异常钩子
    sys.excepthook = _exception_hook

    from src.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
