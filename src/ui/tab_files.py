"""
文件浏览标签页：浏览自己网盘中的文件，支持下载
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QFileDialog,
    QAbstractItemView, QLineEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from .utils import (
    FILE_TYPE_ICONS,
    format_size,
    get_file_type,
    make_unique_save_path,
)
from ..core.config import save_config


class FileListWorker(QThread):
    """后台获取文件列表"""
    result = pyqtSignal(dict)

    def __init__(self, api, path):
        super().__init__()
        self.api = api
        self.path = path

    def run(self):
        try:
            data = self.api.list_files(dir_path=self.path)
            self.result.emit(data)
        except Exception as e:
            self.result.emit({"errno": -1, "errmsg": str(e)})


class DlinkWorker(QThread):
    """后台获取下载链接"""
    result = pyqtSignal(int, str, str)  # fs_id, filename, dlink

    def __init__(self, api, fs_id, filename):
        super().__init__()
        self.api = api
        self.fs_id = fs_id
        self.filename = filename

    def run(self):
        try:
            dlink = self.api.get_download_link(self.fs_id)
            self.result.emit(self.fs_id, self.filename, dlink or "")
        except Exception as e:
            self.result.emit(self.fs_id, self.filename, "")


class FileBrowserTab(QWidget):
    def __init__(self, api, download_manager, config):
        super().__init__()
        self.api = api
        self.dm = download_manager
        self.config = config
        self.current_path = "/"
        self.path_history = ["/"]
        self._workers = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 顶部导航栏
        nav_layout = QHBoxLayout()

        self.btn_back = QPushButton("返回")
        self.btn_back.setMinimumHeight(36)
        self.btn_back.setMaximumWidth(80)
        self.btn_back.clicked.connect(self._go_back)

        self.btn_home = QPushButton("根目录")
        self.btn_home.setMinimumHeight(36)
        self.btn_home.setMaximumWidth(100)
        self.btn_home.clicked.connect(self._go_home)

        self.lbl_path = QLabel("/")
        self.lbl_path.setStyleSheet("color: #2563EB; font-size: 13px; font-weight: 500; padding: 4px 8px;")

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setMinimumHeight(36)
        self.btn_refresh.setMaximumWidth(80)
        self.btn_refresh.clicked.connect(self.refresh_files)

        nav_layout.addWidget(self.btn_back)
        nav_layout.addWidget(self.btn_home)
        nav_layout.addWidget(self.lbl_path, 1)
        nav_layout.addWidget(self.btn_refresh)

        layout.addLayout(nav_layout)

        # 搜索栏
        search_layout = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索文件...")
        self.edit_search.setMinimumHeight(32)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setMinimumHeight(36)
        self.btn_search.setMaximumWidth(80)
        self.btn_search.clicked.connect(self._do_search)
        self.edit_search.returnPressed.connect(self._do_search)
        search_layout.addWidget(self.edit_search)
        search_layout.addWidget(self.btn_search)
        layout.addLayout(search_layout)

        # 文件树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件名", "大小", "修改时间", "类型"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setRootIsDecorated(False)
        self.tree.setAllColumnsShowFocus(True)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree)

        # 底部操作栏
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)
        self.lbl_info = QLabel("")
        bottom_layout.addWidget(self.lbl_info, 1)

        self.btn_download_selected = QPushButton("下载选中")
        self.btn_download_selected.setMinimumHeight(36)
        self.btn_download_selected.setMinimumWidth(120)
        self.btn_download_selected.setObjectName("btnSuccess")
        self.btn_download_selected.clicked.connect(self._download_selected)
        bottom_layout.addWidget(self.btn_download_selected)

        self.btn_delete_selected = QPushButton("删除选中")
        self.btn_delete_selected.setMinimumHeight(36)
        self.btn_delete_selected.setMinimumWidth(120)
        self.btn_delete_selected.setObjectName("btnDanger")
        self.btn_delete_selected.clicked.connect(self._delete_selected)
        bottom_layout.addWidget(self.btn_delete_selected)

        layout.addLayout(bottom_layout)

    def _start_worker(self, worker: QThread):
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._forget_worker(w))
        worker.start()

    def _forget_worker(self, worker: QThread):
        if worker in self._workers:
            self._workers.remove(worker)

    def refresh_files(self):
        self.tree.clear()
        self.lbl_info.setText("加载中...")
        self.lbl_path.setText(self.current_path)

        worker = FileListWorker(self.api, self.current_path)
        worker.result.connect(self._on_file_list)
        self._start_worker(worker)

    @pyqtSlot(dict)
    def _on_file_list(self, data: dict):
        self.tree.clear()
        if data.get("errno") != 0:
            self.lbl_info.setText(f"获取失败: {data.get('errmsg', data.get('errno'))}")
            return

        file_list = data.get("list", [])
        self.lbl_info.setText(f"共 {len(file_list)} 个项目")

        for item in file_list:
            is_dir = item.get("isdir", 0) == 1
            filename = item.get("server_filename", item.get("path", "").rsplit("/", 1)[-1])
            size = item.get("size", 0)
            mtime = item.get("server_mtime", 0)

            tree_item = QTreeWidgetItem()
            ftype = "folder" if is_dir else get_file_type(filename)
            icon = FILE_TYPE_ICONS.get(ftype, FILE_TYPE_ICONS["other"])

            tree_item.setText(0, f"{icon} {filename}")
            tree_item.setText(1, "" if is_dir else format_size(size))

            import datetime
            if mtime:
                dt = datetime.datetime.fromtimestamp(mtime)
                tree_item.setText(2, dt.strftime("%Y-%m-%d %H:%M"))
            else:
                tree_item.setText(2, "")

            tree_item.setText(3, "文件夹" if is_dir else ftype)

            # 存储元数据
            tree_item.setData(0, Qt.UserRole, {
                "path": item.get("path", ""),
                "fs_id": item.get("fs_id", 0),
                "isdir": is_dir,
                "size": size,
                "filename": filename,
            })

            self.tree.addTopLevelItem(tree_item)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        meta = item.data(0, Qt.UserRole)
        if meta and meta.get("isdir"):
            self.current_path = meta["path"]
            self.path_history.append(self.current_path)
            self.refresh_files()

    def _go_back(self):
        if len(self.path_history) > 1:
            self.path_history.pop()
            self.current_path = self.path_history[-1]
            self.refresh_files()

    def _go_home(self):
        self.current_path = "/"
        self.path_history = ["/"]
        self.refresh_files()

    def _do_search(self):
        keyword = self.edit_search.text().strip()
        if not keyword:
            return
        self.tree.clear()
        self.lbl_info.setText("搜索中...")

        class SearchWorker(QThread):
            result = pyqtSignal(dict)
            def __init__(self, api, kw):
                super().__init__()
                self.api = api
                self.kw = kw
            def run(self):
                try:
                    self.result.emit(self.api.search_files(self.kw))
                except Exception as e:
                    self.result.emit({"errno": -1, "errmsg": str(e)})

        worker = SearchWorker(self.api, keyword)
        worker.result.connect(self._on_file_list)
        self._start_worker(worker)

    def _get_selected_items(self):
        """获取当前高亮选中的项目。"""
        return self.tree.selectedItems()

    def _download_selected(self):
        selected = self._get_selected_items()
        if not selected:
            self.lbl_info.setText("请先选择要下载的文件")
            return

        save_dir = self.config.get("download_dir", "")
        if not save_dir:
            save_dir = QFileDialog.getExistingDirectory(self, "选择下载目录")
            if not save_dir:
                return
            self.config["download_dir"] = save_dir
            save_config(self.config)
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            self.lbl_info.setText(f"下载目录不可用: {e}")
            return

        planned_paths = set()
        for item in selected:
            meta = item.data(0, Qt.UserRole)
            if not meta or meta.get("isdir"):
                continue
            fs_id = meta["fs_id"]
            filename = meta["filename"]
            size = meta["size"]
            pan_path = meta.get("path", "")
            save_path = make_unique_save_path(save_dir, filename, planned_paths)

            self.lbl_info.setText(f"获取下载链接: {filename}...")

            worker = DlinkWorker(self.api, fs_id, filename)
            worker.result.connect(
                lambda fid, fn, dl, sz=size, sp=save_path, pp=pan_path:
                    self._on_dlink_ready(fid, fn, dl, sz, sp, pp)
            )
            self._start_worker(worker)

    @pyqtSlot(int, str, str)
    def _on_dlink_ready(self, fs_id: int, filename: str, dlink: str,
                        size: int = 0, save_path: str = "", pan_path: str = ""):
        if not dlink:
            self.lbl_info.setText(f"获取下载链接失败: {filename}")
            return

        self.dm.add_task(
            filename=filename,
            fs_id=fs_id,
            dlink=dlink,
            save_path=save_path,
            total_size=size,
            file_path=pan_path,
        )
        self.lbl_info.setText(f"已添加下载: {filename}")

    def _delete_selected(self):
        items = self._get_selected_items()
        if not items:
            self.lbl_info.setText("请先选择要删除的文件")
            return

        paths = []
        names = []
        for item in items:
            meta = item.data(0, Qt.UserRole)
            if meta:
                paths.append(meta["path"])
                names.append(meta["filename"])

        if not paths:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除以下 {len(paths)} 个文件/文件夹？\n\n" +
            "\n".join(names[:10]) +
            ("\n..." if len(names) > 10 else ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self.api.delete_files(paths)
            if result.get("errno") == 0:
                self.lbl_info.setText(f"已删除 {len(paths)} 个文件")
                self.refresh_files()
            else:
                self.lbl_info.setText(f"删除失败: {result.get('errmsg', result.get('errno'))}")
        except Exception as e:
            self.lbl_info.setText(f"删除出错: {e}")
