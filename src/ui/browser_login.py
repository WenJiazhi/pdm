"""
浏览器登录：优先使用内嵌 WebEngine 直接捕获 Cookie，缺少依赖时回退系统浏览器。
"""
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

from PyQt5.QtCore import QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QTextEdit,
)

from src.core.logger import get_logger
from src.core.api import BaiduPanAPI

logger = get_logger()

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineProfile, QWebEngineView
    _WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineProfile = None
    QWebEngineView = None
    _WEBENGINE_AVAILABLE = False

_CALLBACK_PORT = 19980
_LOGIN_URL = (
    "https://pan.baidu.com/login?"
    "redirecturl=https%3A%2F%2Fpan.baidu.com%2Fdisk%2Fmain%23%2Findex"
)


def preload_webengine() -> bool:
    """预热 WebEngine 导入，缺少依赖时返回 False。"""
    return _WEBENGINE_AVAILABLE


class _CookieHandler(BaseHTTPRequestHandler):
    """处理来自浏览器的 Cookie 回调"""

    server: "HTTPServer"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
            b"<h2 style='color:#16A34A'>&#10003; Cookie received</h2>"
            b"<p>You can close this tab now.</p></body></html>"
        )
        if hasattr(self.server, "_cookie_result"):
            self.server._cookie_result = body

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


class BaiduLoginDialog(QDialog):
    """百度网盘登录对话框"""

    login_done = pyqtSignal(str, str, str)  # bduss, bduss_bfess, full_cookie_str

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("百度网盘登录")
        if _WEBENGINE_AVAILABLE:
            self.resize(920, 640)
            self.setMinimumSize(720, 480)
        else:
            self.resize(520, 400)
            self.setMinimumSize(460, 340)

        self._server = None
        self._server_thread = None
        self._finished = False
        self._cookies = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_cookie)

        if _WEBENGINE_AVAILABLE:
            self._init_webengine_ui()
        else:
            self._init_manual_ui()
            self._start_server()
            self._open_browser()

    def _init_webengine_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("百度网盘登录")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        layout.addWidget(title)

        self.lbl_status = QLabel("请在下方页面完成登录，Cookie 会自动保存到本机。")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #64748B;")
        layout.addWidget(self.lbl_status)

        self.webview = QWebEngineView(self)
        profile = QWebEngineProfile.defaultProfile()
        try:
            profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
            profile.setHttpUserAgent(BaiduPanAPI.UA)
        except Exception:
            pass
        profile.cookieStore().cookieAdded.connect(self._on_web_cookie_added)
        layout.addWidget(self.webview, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_reopen = QPushButton("重新加载")
        self.btn_reopen.clicked.connect(lambda: self.webview.load(QUrl(_LOGIN_URL)))
        btn_layout.addWidget(self.btn_reopen)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btnFlat")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)
        self.webview.load(QUrl(_LOGIN_URL))

    def _init_manual_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("使用系统浏览器登录")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        layout.addWidget(title)

        step1 = QLabel("1. 系统浏览器已打开百度网盘登录页面，请完成登录")
        step1.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(step1)

        step2 = QLabel("2. 登录成功后，在浏览器地址栏中按 F12 打开开发者工具")
        step2.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(step2)

        step3 = QLabel("3. 切换到 Console 标签，粘贴以下代码并回车：")
        step3.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(step3)

        snippet = (
            f"fetch('http://127.0.0.1:{_CALLBACK_PORT}/cookie',"
            "{method:'POST',headers:{'Content-Type':'text/plain'},"
            "body:document.cookie})"
            ".then(()=>document.title='Done')"
        )
        self._snippet = snippet

        code_box = QTextEdit()
        code_box.setPlainText(snippet)
        code_box.setReadOnly(True)
        code_box.setMaximumHeight(60)
        code_box.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px;"
            "background: #F1F5F9; border: 1px solid #E2E8F0; border-radius: 6px;"
            "padding: 8px; color: #334155;"
        )
        layout.addWidget(code_box)

        self.lbl_status = QLabel("等待 Cookie 回调...")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #64748B;")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_reopen = QPushButton("重新打开浏览器")
        self.btn_reopen.clicked.connect(self._open_browser)
        btn_layout.addWidget(self.btn_reopen)

        self.btn_copy = QPushButton("复制代码")
        self.btn_copy.clicked.connect(self._copy_snippet)
        btn_layout.addWidget(self.btn_copy)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btnFlat")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _on_web_cookie_added(self, cookie):
        if self._finished:
            return
        try:
            domain = cookie.domain()
            if "baidu.com" not in domain:
                return
            name = bytes(cookie.name()).decode("utf-8", errors="replace")
            value = bytes(cookie.value()).decode("utf-8", errors="replace")
            if not name or not value:
                return
            self._cookies[name] = value
            if name == "BDUSS" or "BDUSS" in self._cookies:
                self.lbl_status.setText("已捕获登录 Cookie，正在验证...")
                self.lbl_status.setStyleSheet("font-size: 12px; color: #16A34A;")
                QTimer.singleShot(500, lambda: self._finish(self._web_cookie_string()))
        except Exception as e:
            logger.debug(f"web cookie capture failed: {e}")

    def _web_cookie_string(self) -> str:
        priority = ["BDUSS", "BDUSS_BFESS", "STOKEN", "BDCLND"]
        ordered = []
        for name in priority:
            if name in self._cookies:
                ordered.append((name, self._cookies[name]))
        for name, value in self._cookies.items():
            if name not in priority:
                ordered.append((name, value))
        return "; ".join(f"{name}={value}" for name, value in ordered)

    def _start_server(self):
        try:
            self._server = HTTPServer(("127.0.0.1", _CALLBACK_PORT), _CookieHandler)
            self._server._cookie_result = None
            self._server.timeout = 0.5
            self._server_thread = threading.Thread(
                target=self._serve_loop, daemon=True
            )
            self._server_thread.start()
            self._poll_timer.start(500)
            logger.info(f"Cookie callback server started on port {_CALLBACK_PORT}")
        except OSError as e:
            self.lbl_status.setText(f"无法启动回调服务: {e}")
            self.lbl_status.setStyleSheet("font-size: 12px; color: #DC2626;")

    def _serve_loop(self):
        while not self._finished:
            self._server.handle_request()

    def _open_browser(self):
        webbrowser.open(_LOGIN_URL)
        self.lbl_status.setText("浏览器已打开，请登录后执行上方代码")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #2563EB;")

    def _copy_snippet(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(self._snippet)
        self.btn_copy.setText("已复制")
        QTimer.singleShot(2000, lambda: self.btn_copy.setText("复制代码"))

    def _check_cookie(self):
        if self._finished:
            return
        if self._server and self._server._cookie_result:
            cookie_str = self._server._cookie_result
            self._server._cookie_result = None
            self._finish(cookie_str)

    def _finish(self, cookie_str: str):
        if self._finished:
            return
        self._finished = True
        self._poll_timer.stop()

        bduss = ""
        bfess = ""
        import re
        for item in re.split(r';\s*', cookie_str.strip()):
            if '=' in item:
                key, val = item.split('=', 1)
                key = key.strip()
                val = val.strip()
                if key == "BDUSS":
                    bduss = val
                elif key == "BDUSS_BFESS":
                    bfess = val

        if bduss:
            self.lbl_status.setText("Cookie 获取成功！")
            self.lbl_status.setStyleSheet("font-size: 12px; color: #16A34A;")
            self.login_done.emit(bduss, bfess, cookie_str)
            QTimer.singleShot(800, self.accept)
        else:
            self.lbl_status.setText("未找到 BDUSS，请确认已登录百度网盘")
            self.lbl_status.setStyleSheet("font-size: 12px; color: #DC2626;")

    def _shutdown_server(self):
        self._finished = True
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass

    def closeEvent(self, event):
        self._shutdown_server()
        super().closeEvent(event)

    def reject(self):
        self._shutdown_server()
        super().reject()
