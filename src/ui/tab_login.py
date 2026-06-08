"""
登录标签页：浏览器登录 + 多账号管理（保存历史登录的完整Cookie）
"""
import json
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QPlainTextEdit,
)
from PyQt5.QtCore import pyqtSignal, Qt, QThread, pyqtSlot
from PyQt5.QtGui import QBrush, QColor


ACCOUNTS_PATH = os.path.join(
    os.path.expanduser("~"), ".pdm", "accounts.json"
)
LEGACY_ACCOUNTS_PATH = os.path.join(
    os.path.expanduser("~"), ".bduss_downloader", "accounts.json"
)


def _load_accounts() -> list:
    accounts_path = ACCOUNTS_PATH
    if not os.path.exists(accounts_path) and os.path.exists(LEGACY_ACCOUNTS_PATH):
        accounts_path = LEGACY_ACCOUNTS_PATH
    if not os.path.exists(accounts_path):
        return []
    try:
        with open(accounts_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_accounts(accounts: list):
    os.makedirs(os.path.dirname(ACCOUNTS_PATH), exist_ok=True)
    with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


class LoginWorker(QThread):
    result = pyqtSignal(bool, str, str)  # success, username/error, vip_type

    def __init__(self, api, cookie_string: str = ""):
        super().__init__()
        self.api = api
        self.cookie_string = cookie_string

    def run(self):
        try:
            if self.cookie_string:
                self.api.update_credentials_from_cookie_string(self.cookie_string)
            info = self.api.get_user_info()
            if info.get("errno") == 0:
                uname = info.get("username", "用户")
                vip = self._detect_vip()
                self.result.emit(True, str(uname), vip)
            else:
                errmsg = info.get("errmsg", f"errno={info.get('errno')}")
                self.result.emit(False, str(errmsg), "")
        except Exception as e:
            self.result.emit(False, str(e), "")

    def _detect_vip(self) -> str:
        try:
            resp = self.api.session.get(
                "https://pan.baidu.com/api/gettemplatevariable",
                params={"clienttype": 0, "web": 1,
                        "fields": json.dumps(["is_vip", "is_svip"])},
                timeout=10,
            )
            data = resp.json()
            if data.get("errno") == 0:
                result = data.get("result", {})
                if result.get("is_svip") == 1:
                    return "SVIP"
                elif result.get("is_vip") == 1:
                    return "VIP"
            return "普通用户"
        except Exception:
            return "未知"


class LoginTab(QWidget):
    login_success = pyqtSignal(str)
    logout_success = pyqtSignal()

    def __init__(self, api, config):
        super().__init__()
        self.api = api
        self.config = config
        self._worker = None
        self._pending_cookie = None
        self._accounts = _load_accounts()
        self._active_username = self._infer_active_username()
        if self._active_username:
            self._promote_account_to_top(self._active_username, persist=True)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 24, 34, 20)
        layout.setSpacing(12)

        title = QLabel("PDM")
        title.setObjectName("lblTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("登录后即可下载文件")
        subtitle.setObjectName("lblSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # ── 浏览器登录 ──
        login_group = QGroupBox("新账号登录")
        login_layout = QVBoxLayout(login_group)
        login_layout.setContentsMargins(18, 24, 18, 18)
        login_layout.setSpacing(10)

        self.btn_browser_login = QPushButton("网页登录（推荐）")
        self.btn_browser_login.setMinimumHeight(44)
        self.btn_browser_login.clicked.connect(self._do_browser_login)
        login_layout.addWidget(self.btn_browser_login)

        lbl_hint = QLabel("优先使用内嵌登录窗口，登录成功后自动保存账号")
        lbl_hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        lbl_hint.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(lbl_hint)

        layout.addWidget(login_group)

        # ── 手动 Cookie 导入 ──
        cookie_group = QGroupBox("手动 Cookie 导入")
        cookie_layout = QVBoxLayout(cookie_group)
        cookie_layout.setContentsMargins(18, 24, 18, 18)
        cookie_layout.setSpacing(10)

        self.edit_cookie = QPlainTextEdit()
        self.edit_cookie.setPlaceholderText("粘贴新的 Cookie 后点击导入，不会显示已保存 Cookie")
        self.edit_cookie.setFixedHeight(76)
        cookie_layout.addWidget(self.edit_cookie)

        cookie_btn_layout = QHBoxLayout()
        cookie_btn_layout.addStretch()
        self.btn_import_cookie = QPushButton("导入 Cookie")
        self.btn_import_cookie.setMinimumHeight(34)
        self.btn_import_cookie.setObjectName("btnFlat")
        self.btn_import_cookie.clicked.connect(self._import_cookie)
        cookie_btn_layout.addWidget(self.btn_import_cookie)
        cookie_layout.addLayout(cookie_btn_layout)

        layout.addWidget(cookie_group)

        # ── 已保存账号列表 ──
        account_group = QGroupBox("已保存的账号")
        account_layout = QVBoxLayout(account_group)
        account_layout.setContentsMargins(18, 24, 18, 18)
        account_layout.setSpacing(12)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["用户名", "类型", "状态"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setMinimumHeight(120)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        account_layout.addWidget(self.tree)

        acc_btn_layout = QHBoxLayout()

        self.btn_login_selected = QPushButton("使用选中账号登录")
        self.btn_login_selected.setMinimumHeight(36)
        self.btn_login_selected.setObjectName("btnSuccess")
        self.btn_login_selected.clicked.connect(self._login_selected)

        self.btn_delete_selected = QPushButton("删除选中")
        self.btn_delete_selected.setMinimumHeight(36)
        self.btn_delete_selected.setObjectName("btnDanger")
        self.btn_delete_selected.clicked.connect(self._delete_selected)

        self.btn_logout = QPushButton("退出登录")
        self.btn_logout.setMinimumHeight(36)
        self.btn_logout.setObjectName("btnDanger")
        self.btn_logout.clicked.connect(self._do_logout)
        self.btn_logout.setEnabled(False)

        acc_btn_layout.addWidget(self.btn_login_selected)
        acc_btn_layout.addWidget(self.btn_delete_selected)
        acc_btn_layout.addStretch()
        acc_btn_layout.addWidget(self.btn_logout)
        account_layout.addLayout(acc_btn_layout)
        self.tree.itemSelectionChanged.connect(self._sync_account_buttons)

        layout.addWidget(account_group, 1)

        # 状态
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        self._refresh_account_list()

    def _refresh_account_list(self):
        self.tree.clear()
        active_item = None
        for acc in self._accounts:
            is_active = acc.get("username") == self._active_username
            item = QTreeWidgetItem([
                acc.get("username", "未知"),
                acc.get("vip_type", "未知"),
                "当前使用" if is_active else "已保存",
            ])
            item.setData(0, Qt.UserRole, acc)
            if is_active:
                active_item = item
                active_bg = QBrush(QColor("#EFF6FF"))
                active_fg = QBrush(QColor("#1D4ED8"))
                for column in range(3):
                    item.setBackground(column, active_bg)
                item.setForeground(0, active_fg)
                item.setForeground(2, active_fg)
            self.tree.addTopLevelItem(item)
        if active_item:
            self.tree.setCurrentItem(active_item)
            active_item.setSelected(True)
            self.tree.scrollToItem(active_item)
        self._sync_account_buttons()

    def _sync_account_buttons(self):
        has_selection = self._get_selected_account() is not None
        busy = bool(self._worker and self._worker.isRunning())
        self.btn_browser_login.setEnabled(not busy)
        self.btn_import_cookie.setEnabled(not busy)
        self.btn_login_selected.setEnabled(has_selection and not busy)
        self.btn_delete_selected.setEnabled(has_selection and not busy)

    def _start_login_worker(self, worker: LoginWorker):
        self._worker = worker
        worker.result.connect(self._on_login_result)
        worker.finished.connect(self._on_login_worker_finished)
        self._sync_account_buttons()
        worker.start()

    def _on_login_worker_finished(self):
        self._worker = None
        self._sync_account_buttons()

    def _get_selected_account(self) -> dict | None:
        selected_items = self.tree.selectedItems()
        if selected_items:
            return selected_items[0].data(0, Qt.UserRole)
        return None

    def _login_selected(self):
        acc = self._get_selected_account()
        if not acc:
            self.lbl_status.setText("请先选择一个账号")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        cookie = acc.get("cookie", "")
        if not cookie:
            self.lbl_status.setText("该账号没有保存Cookie，请重新浏览器登录")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        self.lbl_status.setText("正在登录...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        self._pending_cookie = cookie
        self._start_login_worker(LoginWorker(self.api, cookie_string=cookie))

    def _import_cookie(self):
        cookie = self.edit_cookie.toPlainText().strip()
        if not cookie:
            self.lbl_status.setText("请先粘贴 Cookie")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        self.edit_cookie.clear()
        self.lbl_status.setText("正在验证 Cookie...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        self._pending_cookie = cookie
        self._start_login_worker(LoginWorker(self.api, cookie_string=cookie))

    def _delete_selected(self):
        acc = self._get_selected_account()
        if not acc:
            self.lbl_status.setText("请先选择要删除的账号")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        username = acc.get("username", "")
        was_active = username == self._active_username
        self._accounts = [a for a in self._accounts if a.get("username") != username]
        _save_accounts(self._accounts)
        self._refresh_account_list()
        if was_active:
            self._do_logout()
        else:
            self.lbl_status.setText(f"已删除账号: {username}")
            self.lbl_status.setStyleSheet("color: #A1A1AA;")

    def _do_browser_login(self):
        from src.ui.browser_login import BaiduLoginDialog
        dlg = BaiduLoginDialog(self)
        dlg.login_done.connect(self._on_browser_login)
        dlg.exec_()

    def _on_browser_login(self, bduss: str, bfess: str, full_cookie: str):
        self.api.update_credentials_from_cookie_string(full_cookie)
        self._pending_cookie = full_cookie

        self.lbl_status.setText("浏览器登录成功，正在验证...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        self._start_login_worker(LoginWorker(self.api))

    @pyqtSlot(bool, str, str)
    def _on_login_result(self, success: bool, msg: str, vip_type: str):
        if success:
            self.lbl_status.setText(f"登录成功！欢迎 {msg}  ({vip_type})")
            self.lbl_status.setStyleSheet("color: #16A34A;")
            self.btn_logout.setEnabled(True)
            self._active_username = msg

            cookie = self._pending_cookie
            if not cookie:
                parts = []
                for c in self.api.session.cookies:
                    parts.append(f"{c.name}={c.value}")
                cookie = "; ".join(parts)

            self._save_account(msg, vip_type, cookie)
            self._promote_account_to_top(msg, persist=True)
            self._pending_cookie = None

            self.config["full_cookie"] = cookie
            self.config["bduss"] = self.api.bduss
            self.config["bduss_bfess"] = self.api.bduss_bfess

            self.login_success.emit(msg)
            self._refresh_account_list()

            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                acc = item.data(0, Qt.UserRole)
                if acc and acc.get("username") == msg:
                    item.setText(2, "当前使用")
                    self.tree.setCurrentItem(item)
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
        else:
            self.lbl_status.setText(f"登录失败: {msg}")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            self._pending_cookie = None

    def _save_account(self, username: str, vip_type: str, cookie: str):
        existing = next(
            (acc for acc in self._accounts if acc.get("username") == username),
            {},
        )
        record = {
            **existing,
            "username": username,
            "vip_type": vip_type,
            "cookie": cookie,
        }
        self._accounts = [
            acc for acc in self._accounts if acc.get("username") != username
        ]
        self._accounts.insert(0, record)
        _save_accounts(self._accounts)

    def _promote_account_to_top(self, username: str, persist: bool):
        if not username:
            return
        for index, acc in enumerate(self._accounts):
            if acc.get("username") == username:
                if index > 0:
                    self._accounts.insert(0, self._accounts.pop(index))
                    if persist:
                        _save_accounts(self._accounts)
                return

    def _infer_active_username(self) -> str:
        cookie = self.config.get("full_cookie", "")
        bduss = self.config.get("bduss", "") or self._cookie_value(cookie, "BDUSS")
        for acc in self._accounts:
            acc_cookie = acc.get("cookie", "")
            if cookie and acc_cookie == cookie:
                return acc.get("username", "")
            if bduss and self._cookie_value(acc_cookie, "BDUSS") == bduss:
                return acc.get("username", "")
        return ""

    @staticmethod
    def _cookie_value(cookie: str, name: str) -> str:
        prefix = f"{name}="
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):]
        return ""

    def _do_logout(self):
        self.api.update_credentials("", "")
        self._active_username = ""
        self.btn_logout.setEnabled(False)
        self.lbl_status.setText("已退出登录")
        self.lbl_status.setStyleSheet("color: #A1A1AA;")
        self._refresh_account_list()
        self.tree.clearSelection()
        self.logout_success.emit()

    def check_login_status(self):
        cookie = self.config.get("full_cookie", "")
        if cookie:
            self._pending_cookie = cookie
            self._start_login_worker(LoginWorker(self.api, cookie_string=cookie))
