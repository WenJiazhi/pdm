"""
主窗口：左侧导航 + 内容工作区。
"""
from PyQt5.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSizePolicy, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)
from PyQt5.QtCore import QTimer

from ..core.api import BaiduPanAPI
from ..core.aria2_downloader import DownloadManager
from ..core.config import load_config, save_config
from .styles import STYLE_SHEET
from .tab_downloads import DownloadsTab
from .tab_files import FileBrowserTab
from .tab_login import LoginTab
from .tab_settings import SettingsTab
from .tab_share import ShareParseTab
from .utils import format_size


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDM")
        self.setMinimumSize(1080, 720)
        self.resize(1180, 780)

        self.config = load_config()
        self.api = BaiduPanAPI(
            bduss=self.config.get("bduss", ""),
            bduss_bfess=self.config.get("bduss_bfess", ""),
        )
        self.download_manager = DownloadManager(
            api=self.api,
            max_concurrent_tasks=self.config.get("max_concurrent_tasks", 2),
            task_connections=self.config.get("task_connections", 16),
            speed_limit=self.config.get("speed_limit", 0),
        )

        self.setStyleSheet(STYLE_SHEET)
        self._init_ui()
        self._connect_signals()

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(2000)

        self._center_and_show()
        QTimer.singleShot(500, self._check_initial_login)
        QTimer.singleShot(1200, self._preload_browser_login)

    def _center_and_show(self):
        """强制窗口居中到屏幕并置顶显示。"""
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _init_ui(self):
        central = QWidget()
        central.setObjectName("appShell")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(12)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(12, 16, 12, 12)
        side_layout.setSpacing(4)

        brand = QLabel("PDM")
        brand.setObjectName("brandTitle")
        side_layout.addWidget(brand)

        brand_subtitle = QLabel("Pan Download Manager")
        brand_subtitle.setObjectName("brandSubtitle")
        side_layout.addWidget(brand_subtitle)
        side_layout.addSpacing(16)

        self.login_tab = LoginTab(self.api, self.config)
        self.files_tab = FileBrowserTab(self.api, self.download_manager, self.config)
        self.share_tab = ShareParseTab(self.api, self.download_manager, self.config)
        self.downloads_tab = DownloadsTab(self.download_manager)
        self.settings_tab = SettingsTab(self.config, self.download_manager)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentStack")
        self.pages = [
            ("登录", self.login_tab),
            ("我的文件", self.files_tab),
            ("分享转存", self.share_tab),
            ("下载", self.downloads_tab),
            ("设置", self.settings_tab),
        ]

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for index, (title, page) in enumerate(self.pages):
            self.stack.addWidget(page)
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda checked=False, idx=index: self._select_page(idx)
            )
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            side_layout.addWidget(button)

        side_layout.addStretch()
        side_note = QLabel("Cookie 仅保存在本机配置目录")
        side_note.setObjectName("sideNote")
        side_note.setWordWrap(True)
        side_layout.addWidget(side_note)

        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.stack)

        root.addWidget(self.sidebar)
        root.addWidget(content_frame, 1)
        self._select_page(0)

        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("appStatusBar")
        self.setStatusBar(self.status_bar)
        self.lbl_login_status = QLabel("未登录")
        self.lbl_login_status.setObjectName("lblStatus")
        self.lbl_quota = QLabel("")
        self.status_bar.addWidget(self.lbl_login_status)
        self.status_bar.addPermanentWidget(self.lbl_quota)

    def _connect_signals(self):
        self.login_tab.login_success.connect(self._on_login_success)
        self.login_tab.logout_success.connect(self._on_logout)
        self.settings_tab.config_changed.connect(self._on_config_changed)
        self.stack.currentChanged.connect(self._on_page_changed)

    def _select_page(self, index: int):
        self.stack.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)

    def _on_page_changed(self, index: int):
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if index == 1 and self.api.bduss:
            if self.files_tab.tree.topLevelItemCount() == 0:
                self.files_tab.refresh_files()

    def _check_initial_login(self):
        full_cookie = self.config.get("full_cookie", "")
        if full_cookie:
            self.api.update_credentials_from_cookie_string(full_cookie)
            self.login_tab.check_login_status()
        elif self.config.get("bduss") or self.config.get("bduss_bfess"):
            cookie_parts = []
            if self.config.get("bduss"):
                cookie_parts.append(f"BDUSS={self.config['bduss']}")
            if self.config.get("bduss_bfess"):
                cookie_parts.append(f"BDUSS_BFESS={self.config['bduss_bfess']}")
            if cookie_parts:
                self.config["full_cookie"] = "; ".join(cookie_parts)
                self.api.update_credentials_from_cookie_string(self.config["full_cookie"])
            self.login_tab.check_login_status()

    def _preload_browser_login(self):
        try:
            from src.ui.browser_login import preload_webengine

            preload_webengine()
        except Exception as exc:
            from src.core.logger import get_logger

            get_logger().warning(f"browser login preload failed: {exc}")

    def _on_login_success(self, username: str):
        self.lbl_login_status.setText(f"已登录: {username}")
        self.lbl_login_status.setStyleSheet("color: #16A34A;")
        self.status_bar.showMessage("登录成功", 3000)

        self.config["bduss"] = self.api.bduss
        self.config["bduss_bfess"] = self.api.bduss_bfess
        cookie_parts = [f"{c.name}={c.value}" for c in self.api.session.cookies]
        if cookie_parts:
            self.config["full_cookie"] = "; ".join(cookie_parts)
        save_config(self.config)
        self._update_quota()

    def _on_logout(self):
        self.lbl_login_status.setText("未登录")
        self.lbl_login_status.setStyleSheet("color: #EF4444;")
        self.lbl_quota.setText("")
        self.config["bduss"] = ""
        self.config["bduss_bfess"] = ""
        self.config["full_cookie"] = ""
        save_config(self.config)
        self._select_page(0)

    def _on_config_changed(self):
        save_config(self.config)

    def _update_quota(self):
        try:
            quota = self.api.get_quota()
            if quota.get("errno", -1) == 0 or "total" in quota:
                total = quota.get("total", 0)
                used = quota.get("used", 0)
                self.lbl_quota.setText(f"容量: {format_size(used)} / {format_size(total)}")
        except Exception:
            pass

    def _update_status_bar(self):
        tasks = self.download_manager.get_tasks()
        downloading = sum(1 for task in tasks if task.status.value == "downloading")
        if downloading > 0:
            self.status_bar.showMessage(f"正在下载 {downloading} 个文件")
        else:
            self.status_bar.clearMessage()

    def closeEvent(self, event):
        self.download_manager.stop()
        save_config(self.config)
        event.accept()
