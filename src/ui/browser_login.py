"""
内置浏览器登录窗口：在内嵌百度网盘登录页中提取 BDUSS Cookie。
"""
from __future__ import annotations

import os
import time

from PyQt5.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt5.QtNetwork import QNetworkCookie
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from src.core.api import BaiduPanAPI
from src.core.config import APP_DIR
from src.core.logger import get_logger


logger = get_logger()

QWebEnginePage = None
QWebEngineProfile = None
QWebEngineSettings = None
QWebEngineView = None
_WEBENGINE_IMPORT_ERROR = None


def _ensure_webengine() -> bool:
    """Lazy-load QtWebEngine so the main window and login dialog can appear first."""
    global QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView
    global _WEBENGINE_IMPORT_ERROR

    if QWebEngineView is not None:
        return True

    started = time.perf_counter()
    try:
        from PyQt5.QtWebEngineWidgets import (
            QWebEnginePage as _QWebEnginePage,
            QWebEngineProfile as _QWebEngineProfile,
            QWebEngineSettings as _QWebEngineSettings,
            QWebEngineView as _QWebEngineView,
        )
    except Exception as exc:
        _WEBENGINE_IMPORT_ERROR = exc
        logger.exception(f"failed to import QtWebEngine: {exc}")
        return False

    QWebEnginePage = _QWebEnginePage
    QWebEngineProfile = _QWebEngineProfile
    QWebEngineSettings = _QWebEngineSettings
    QWebEngineView = _QWebEngineView
    _WEBENGINE_IMPORT_ERROR = None
    logger.info(f"QtWebEngine imported in {time.perf_counter() - started:.2f}s")
    return True


def preload_webengine() -> bool:
    """Warm up the heavy QtWebEngine import after the app is already responsive."""
    return _ensure_webengine()


class BaiduLoginDialog(QDialog):
    """内嵌百度网盘登录对话框。"""

    login_done = pyqtSignal(str, str, str)  # bduss, bduss_bfess, full_cookie_str

    LOGIN_URL = (
        "https://pan.baidu.com/login?"
        "redirecturl=https%3A%2F%2Fpan.baidu.com%2Fdisk%2Fmain%23%2Findex"
    )
    SUCCESS_INDICATORS = [
        "pan.baidu.com/disk/home",
        "pan.baidu.com/disk/main",
        "/disk/home",
        "/disk/main",
        "/mbox/homepage",
    ]
    LOGIN_INDICATORS = ["/login", "passport.baidu.com", "wappass.baidu.com"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("百度网盘登录")
        self.resize(960, 700)
        self.setMinimumSize(800, 600)

        self._profile = None
        self.browser = None
        self._browser_layout = None
        self._placeholder = None
        self._browser_ready = False
        self._bduss = ""
        self._bfess = ""
        self._all_cookies = {}  # name -> value
        self._finished = False
        self._loading = False
        self._init_started_at = 0.0

        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.timeout.connect(self._on_load_timeout)

        self._progress_complete_timer = QTimer(self)
        self._progress_complete_timer.setSingleShot(True)
        self._progress_complete_timer.timeout.connect(self._mark_page_interactive)

        self._soft_ready_timer = QTimer(self)
        self._soft_ready_timer.setSingleShot(True)
        self._soft_ready_timer.timeout.connect(self._mark_page_interactive)

        self._init_ui_shell()
        QTimer.singleShot(80, self._init_browser)

    def _init_ui_shell(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(12, 8, 12, 8)
        hint = QLabel("请在下方登录百度网盘，登录成功后程序会自动获取 Cookie")
        hint.setStyleSheet("color: #71717A; font-size: 13px;")
        top_bar.addWidget(hint)
        top_bar.addStretch()

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedWidth(72)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_refresh.setEnabled(False)
        top_bar.addWidget(self.btn_refresh)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedWidth(72)
        self.btn_cancel.clicked.connect(self.reject)
        top_bar.addWidget(self.btn_cancel)

        layout.addLayout(top_bar)

        self.lbl_status = QLabel("正在启动内置浏览器...")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 12px; padding: 6px;")
        layout.addWidget(self.lbl_status)

        self._browser_layout = QVBoxLayout()
        self._browser_layout.setContentsMargins(12, 0, 12, 12)
        self._browser_layout.setSpacing(0)

        self._placeholder = QFrame()
        self._placeholder.setObjectName("browserPlaceholder")
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.setSpacing(8)

        loading_title = QLabel("正在准备百度网盘登录页面")
        loading_title.setAlignment(Qt.AlignCenter)
        loading_title.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #09090B;"
        )
        loading_subtitle = QLabel("首次启动内置浏览器会加载 QtWebEngine，之后会更快。")
        loading_subtitle.setAlignment(Qt.AlignCenter)
        loading_subtitle.setStyleSheet("font-size: 12px; color: #71717A;")
        placeholder_layout.addStretch()
        placeholder_layout.addWidget(loading_title)
        placeholder_layout.addWidget(loading_subtitle)
        placeholder_layout.addStretch()

        self._browser_layout.addWidget(self._placeholder)
        layout.addLayout(self._browser_layout, 1)

    def _init_browser(self) -> None:
        if self._browser_ready or self._finished:
            return

        self._init_started_at = time.perf_counter()
        self.lbl_status.setText("正在初始化内置浏览器...")

        if not _ensure_webengine():
            self.lbl_status.setText(
                f"内置浏览器初始化失败：{_WEBENGINE_IMPORT_ERROR}"
            )
            self.btn_refresh.setEnabled(True)
            return

        try:
            self._profile = self._create_profile()
            cookie_store = self._profile.cookieStore()
            cookie_store.deleteAllCookies()
            cookie_store.cookieAdded.connect(self._on_cookie_added)

            page = QWebEnginePage(self._profile, self)
            self._configure_page(page)

            self.browser = QWebEngineView()
            self.browser.setPage(page)
            self.browser.setMinimumHeight(520)
            self.browser.loadStarted.connect(self._on_load_started)
            self.browser.loadProgress.connect(self._on_load_progress)
            self.browser.loadFinished.connect(self._on_load_finished)
            self.browser.urlChanged.connect(self._on_url_changed)
            if hasattr(page, "renderProcessTerminated"):
                page.renderProcessTerminated.connect(self._on_render_process_terminated)

            self._browser_layout.replaceWidget(self._placeholder, self.browser)
            self._placeholder.hide()
            self._placeholder.deleteLater()
            self._placeholder = None

            self._browser_ready = True
            logger.info(
                f"browser dialog webengine ready in "
                f"{time.perf_counter() - self._init_started_at:.2f}s"
            )
            self._load_login_page("正在加载百度网盘登录页面...")
        except Exception as exc:
            logger.exception(f"failed to initialize browser login dialog: {exc}")
            self.lbl_status.setText(f"内置浏览器启动失败：{exc}")
            self.btn_refresh.setEnabled(True)

    def _create_profile(self):
        cache_dir = os.path.join(APP_DIR, "webengine_cache")
        storage_dir = os.path.join(APP_DIR, "webengine_storage")
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(storage_dir, exist_ok=True)

        try:
            profile = QWebEngineProfile("pdm-login", self)
        except TypeError:
            profile = QWebEngineProfile(self)

        if hasattr(QWebEngineProfile, "DiskHttpCache"):
            profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        if hasattr(profile, "setCachePath"):
            profile.setCachePath(cache_dir)
        if hasattr(profile, "setPersistentStoragePath"):
            profile.setPersistentStoragePath(storage_dir)
        if hasattr(profile, "setPersistentCookiesPolicy"):
            profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        if hasattr(profile, "setHttpAcceptLanguage"):
            profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9,en;q=0.8")
        profile.setHttpUserAgent(BaiduPanAPI.UA)
        return profile

    def _configure_page(self, page) -> None:
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        for attr_name in ("WebGLEnabled", "Accelerated2dCanvasEnabled"):
            if hasattr(QWebEngineSettings, attr_name):
                settings.setAttribute(getattr(QWebEngineSettings, attr_name), False)

    def _refresh(self) -> None:
        if not self._browser_ready or self.browser is None:
            self._init_browser()
            return
        if self._loading:
            self.browser.stop()
        self._load_login_page("正在重新加载百度网盘登录页面...")

    def _load_login_page(self, status: str) -> None:
        if self.browser is None:
            self.lbl_status.setText("内置浏览器尚未就绪，正在重试...")
            QTimer.singleShot(200, self._init_browser)
            return

        self.lbl_status.setText(status)
        self.btn_refresh.setEnabled(False)
        self._loading = True
        self._load_timeout.start(25000)
        self._soft_ready_timer.start(6000)
        logger.info(f"browser login loading pan entry: {self.LOGIN_URL}")
        self.browser.setUrl(QUrl(self.LOGIN_URL))

    def _on_load_started(self) -> None:
        self._loading = True
        self.btn_refresh.setEnabled(False)

    def _on_load_progress(self, progress: int) -> None:
        if progress >= 0:
            self.lbl_status.setText(f"正在加载百度网盘登录页面... {progress}%")
        if progress >= 100:
            self._progress_complete_timer.start(1200)

    def _on_load_finished(self, ok: bool) -> None:
        self._progress_complete_timer.stop()
        url = self.browser.url().toString() if self.browser else ""
        logger.info(f"browser login load finished: ok={ok}, url={url}")
        if ok:
            self._mark_page_interactive()
        else:
            self._loading = False
            self.btn_refresh.setEnabled(True)
            self._load_timeout.stop()
            if self._is_login_url(url):
                self._mark_page_interactive()
            else:
                self.lbl_status.setText("登录页面加载失败，请检查网络后点击刷新")

    def _mark_page_interactive(self) -> None:
        if self._finished:
            return
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self._load_timeout.stop()
        self._soft_ready_timer.stop()
        self.lbl_status.setText("请在下方完成百度网盘登录")

    def _on_load_timeout(self) -> None:
        if self._finished:
            return
        self._progress_complete_timer.stop()
        self._soft_ready_timer.stop()
        self._loading = False
        self.btn_refresh.setEnabled(True)
        if self.browser is not None:
            self.browser.stop()
            current_url = self.browser.url().toString()
        else:
            current_url = ""
        logger.warning(f"browser login load timeout: {current_url}")
        self.lbl_status.setText("登录页面加载超时，请点击刷新重试")

    def _on_render_process_terminated(self, status, exit_code) -> None:
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self._load_timeout.stop()
        self._progress_complete_timer.stop()
        self._soft_ready_timer.stop()
        logger.warning(
            f"browser render process terminated: status={status}, exit={exit_code}"
        )
        self.lbl_status.setText("内置浏览器进程异常退出，请点击刷新重试")

    def _on_cookie_added(self, cookie: QNetworkCookie) -> None:
        """实时监听 Cookie，捕获 BDUSS 后自动结束登录。"""
        if self._finished:
            return

        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        value = bytes(cookie.value()).decode("utf-8", errors="replace")
        self._all_cookies[name] = value

        if name == "BDUSS":
            self._bduss = value
            self.lbl_status.setText(
                f"已捕获 BDUSS (长度={len(value)})，等待登录完成..."
            )
        elif name == "BDUSS_BFESS":
            self._bfess = value

        if self._bduss and self._bfess and not self._finished:
            QTimer.singleShot(2000, self._try_finish)

    def _on_url_changed(self, url: QUrl) -> None:
        if self._finished:
            return

        url_str = url.toString()
        if not self._loading:
            self.lbl_status.setText(f"当前页面: {url_str[:80]}")

        if self._is_login_url(url_str):
            self.lbl_status.setText("请在下方完成百度网盘登录")
            return

        if self._is_netdisk_home_url(url_str):
            if self._bduss:
                self.lbl_status.setText("登录成功，Cookie 已获取")
                QTimer.singleShot(1000, self._try_finish)
            else:
                self.lbl_status.setText("已进入网盘页面，等待 Cookie...")

    def _is_login_url(self, url: str) -> bool:
        return any(indicator in url for indicator in self.LOGIN_INDICATORS)

    def _is_netdisk_home_url(self, url: str) -> bool:
        if self._is_login_url(url):
            return False
        return any(indicator in url for indicator in self.SUCCESS_INDICATORS)

    def _try_finish(self) -> None:
        """尝试完成登录。"""
        if self._finished:
            return

        if self._bduss:
            self._finished = True
            full_cookie = "; ".join(
                f"{key}={value}" for key, value in self._all_cookies.items()
            )
            self.lbl_status.setText(
                f"Cookie 获取成功，BDUSS 长度={len(self._bduss)}，"
                f"共 {len(self._all_cookies)} 个 Cookie"
            )
            self.login_done.emit(self._bduss, self._bfess, full_cookie)
            self._shutdown_browser()
            self.accept()
            return

        cookie_names = list(self._all_cookies.keys())
        self.lbl_status.setText(
            f"请继续完成百度网盘登录。已收集 {len(self._all_cookies)} 个 Cookie，"
            f"等待 BDUSS 写入。已有: {', '.join(cookie_names[:10])}"
        )

    def _disconnect_cookie_listener(self) -> None:
        if self._profile is None:
            return
        try:
            cookie_store = self._profile.cookieStore()
            cookie_store.cookieAdded.disconnect(self._on_cookie_added)
        except Exception:
            pass

    def _shutdown_browser(self) -> None:
        self._load_timeout.stop()
        self._progress_complete_timer.stop()
        self._soft_ready_timer.stop()
        self._disconnect_cookie_listener()
        if self.browser is None:
            return
        try:
            self.browser.stop()
            page = self.browser.page()
            self.browser.setPage(None)
            if page is not None:
                page.deleteLater()
            self.browser.deleteLater()
        except Exception:
            pass
        self.browser = None
        self._browser_ready = False

    def closeEvent(self, event) -> None:
        self._shutdown_browser()
        super().closeEvent(event)

    def reject(self) -> None:
        self._shutdown_browser()
        super().reject()
