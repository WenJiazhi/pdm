"""
分享链接解析标签页：解析百度网盘分享链接，支持提取码、文件夹展开、转存后下载
"""
import os
import re
import time
import uuid
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from .utils import (
    FILE_TYPE_ICONS,
    format_size,
    get_file_type,
    make_unique_save_path,
)
from ..core.logger import get_logger

logger = get_logger()


class ShareParseWorker(QThread):
    """解析分享链接的工作线程"""
    result = pyqtSignal(dict)

    def __init__(self, api, surl, pwd):
        super().__init__()
        self.api = api
        self.surl = surl
        self.pwd = pwd

    def run(self):
        try:
            data = self.api.list_share_files(self.surl, self.pwd)
            self.result.emit(data)
        except Exception as e:
            self.result.emit({"errno": -1, "errmsg": str(e)})


class ShareDirWorker(QThread):
    """展开分享目录的工作线程"""
    result = pyqtSignal(str, dict)  # dir_path, data

    def __init__(self, api, shareid, uk, dir_path):
        super().__init__()
        self.api = api
        self.shareid = shareid
        self.uk = uk
        self.dir_path = dir_path

    def run(self):
        try:
            data = self.api.list_share_dir(self.shareid, self.uk, self.dir_path)
            self.result.emit(self.dir_path, data)
        except Exception as e:
            self.result.emit(self.dir_path, {"errno": -1, "errmsg": str(e)})


class TransferWorker(QThread):
    """转存文件的工作线程"""
    result = pyqtSignal(dict)

    def __init__(self, api, surl, fs_ids, to_path, randsk):
        super().__init__()
        self.api = api
        self.surl = surl
        self.fs_ids = fs_ids
        self.to_path = to_path
        self.randsk = randsk

    def run(self):
        try:
            data = self.api.transfer_share_files(
                self.surl, self.fs_ids, self.to_path, self.randsk
            )
            self.result.emit(data)
        except Exception as e:
            self.result.emit({"errno": -1, "errmsg": str(e)})


class TransferDownloadWorker(QThread):
    """一键转存+获取下载链接的工作线程"""
    # progress_msg, is_error
    progress = pyqtSignal(str, bool)
    # list of (filename, dlink, size, transferred_path)
    result = pyqtSignal(list)

    def __init__(self, api, surl, files_info, to_path, randsk):
        """
        files_info: list of (fs_id, filename, size)
        """
        super().__init__()
        self.api = api
        self.surl = surl
        self.files_info = files_info
        self.to_path = to_path
        self.randsk = randsk

    def run(self):
        try:
            fs_ids = [f[0] for f in self.files_info]

            # Step 0: 创建临时转存目录
            self.progress.emit("正在创建临时目录...", False)
            current = ""
            for part in [p for p in self.to_path.split("/") if p]:
                current += f"/{part}"
                self.api.create_dir(current)

            # Step 1: 转存
            self.progress.emit(f"正在转存 {len(fs_ids)} 个文件...", False)
            transfer_result = self.api.transfer_share_files(
                self.surl, fs_ids, self.to_path, self.randsk
            )
            if transfer_result.get("errno") != 0:
                errmsg = transfer_result.get("errmsg", str(transfer_result.get("errno", "")))
                self.progress.emit(f"转存失败: {errmsg}", True)
                self.result.emit([])
                return

            self.progress.emit("转存成功，正在获取下载链接...", False)

            # Step 2: 获取转存后文件的下载链接
            import time
            time.sleep(1)  # 等待百度索引

            results = []
            for fs_id, filename, size in self.files_info:
                # 在网盘中搜索刚转存的文件
                transferred_path = self.to_path.rstrip("/") + "/" + filename
                # 通过 list_files 查找转存后的文件获取新 fs_id
                parent = self.to_path
                file_list = self.api.list_files(parent)
                new_fs_id = None
                if file_list.get("errno") == 0:
                    for f in file_list.get("list", []):
                        if f.get("path") == transferred_path:
                            new_fs_id = f["fs_id"]
                            break

                if new_fs_id:
                    self.progress.emit(f"获取下载链接: {filename}", False)
                    dlink = self.api.get_download_link(new_fs_id)
                    results.append((filename, dlink, size, transferred_path))
                else:
                    results.append((filename, None, size, transferred_path))

            self.result.emit(results)
        except Exception as e:
            self.progress.emit(f"错误: {e}", True)
            self.result.emit([])


class CleanupTransferWorker(QThread):
    """后台清理一键下载产生的临时转存目录。"""
    result = pyqtSignal(bool, str, str)  # success, user_message, detail

    def __init__(self, api, root: str, success_message: str,
                 fallback_paths: list = None):
        super().__init__()
        self.api = api
        self.root = root
        self.success_message = success_message
        self.fallback_paths = fallback_paths or []

    def run(self):
        targets = [self.root] if self.root else self.fallback_paths
        if not targets:
            self.result.emit(True, self.success_message, "no targets")
            return

        try:
            result = self.api.delete_files(
                targets, onnest="ignore" if self.root else "fail"
            )
            if result.get("errno") == 0:
                self.result.emit(True, self.success_message, str(result))
                return

            if self.root and self.fallback_paths:
                fallback_result = self.api.delete_files(self.fallback_paths)
                if fallback_result.get("errno") == 0:
                    self.api.delete_files([self.root], onnest="ignore")
                    self.result.emit(True, self.success_message, str(fallback_result))
                    return
                self.result.emit(
                    False, "转存临时文件清理失败，可稍后在网盘中手动删除",
                    str(fallback_result),
                )
                return

            self.result.emit(
                False, "转存临时目录清理失败，可稍后在网盘中手动删除",
                str(result),
            )
        except Exception as e:
            self.result.emit(False, f"转存临时目录清理异常: {e}", str(e))


class ShareParseTab(QWidget):
    _cleanup_requested = pyqtSignal(str, str, list)

    def __init__(self, api, download_manager, config):
        super().__init__()
        self.api = api
        self.dm = download_manager
        self.config = config
        self._workers = []
        self._current_surl = ""
        self._current_randsk = ""
        self._shareid = ""
        self._uk = ""
        self._dir_stack = []  # 路径导航栈
        self._cleanup_jobs = {}  # job_id -> {root, paths, task_ids}
        self._current_transfer_job_id = ""
        self._current_transfer_root = ""
        self._auto_delete_hooked = False
        self._cleanup_requested.connect(self._delete_transfer_root)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 输入区域 ──
        input_group = QGroupBox("解析分享链接")
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(18, 26, 18, 18)
        input_layout.setSpacing(10)

        # 链接输入
        link_layout = QHBoxLayout()
        self.edit_link = QLineEdit()
        self.edit_link.setPlaceholderText(
            "粘贴百度网盘分享链接，如: https://pan.baidu.com/s/1xxxxx"
        )
        self.edit_link.setMinimumHeight(36)
        link_layout.addWidget(QLabel("链接:"))
        link_layout.addWidget(self.edit_link)
        input_layout.addLayout(link_layout)

        # 提取码 + 解析按钮
        pwd_layout = QHBoxLayout()
        self.edit_pwd = QLineEdit()
        self.edit_pwd.setPlaceholderText("提取码（无则留空）")
        self.edit_pwd.setMaximumWidth(200)
        self.edit_pwd.setMinimumHeight(36)

        self.btn_parse = QPushButton("解析链接")
        self.btn_parse.setMinimumHeight(36)
        self.btn_parse.setMinimumWidth(120)
        self.btn_parse.clicked.connect(self._do_parse)
        self.edit_link.returnPressed.connect(self._do_parse)

        pwd_layout.addWidget(QLabel("提取码:"))
        pwd_layout.addWidget(self.edit_pwd)
        pwd_layout.addStretch()
        pwd_layout.addWidget(self.btn_parse)
        input_layout.addLayout(pwd_layout)

        layout.addWidget(input_group)

        # ── 路径导航 ──
        nav_layout = QHBoxLayout()
        self.btn_back = QPushButton("← 返回上级")
        self.btn_back.setMaximumWidth(120)
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.setEnabled(False)
        self.btn_back.setVisible(False)
        nav_layout.addWidget(self.btn_back)

        self.lbl_path = QLabel("")
        self.lbl_path.setStyleSheet("color: #2563EB; font-size: 12px; font-weight: 500;")
        nav_layout.addWidget(self.lbl_path)
        nav_layout.addStretch()
        layout.addLayout(nav_layout)

        # ── 状态 ──
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # ── 结果显示 ──
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件名", "大小", "类型"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setRootIsDecorated(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.doubleClicked.connect(self._on_item_double_clicked)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        layout.addWidget(self.tree, 1)

        # ── 底部操作 ──
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)

        self.btn_transfer = QPushButton("仅转存到网盘")
        self.btn_transfer.setMinimumHeight(38)
        self.btn_transfer.setMinimumWidth(120)
        self.btn_transfer.setObjectName("btnWarning")
        self.btn_transfer.clicked.connect(self._do_transfer)
        self.btn_transfer.setEnabled(False)

        self.btn_save_to = QPushButton("转存并下载")
        self.btn_save_to.setMinimumHeight(38)
        self.btn_save_to.setMinimumWidth(120)
        self.btn_save_to.setObjectName("btnSuccess")
        self.btn_save_to.clicked.connect(self._do_transfer_and_download)
        self.btn_save_to.setEnabled(False)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_transfer)
        bottom_layout.addWidget(self.btn_save_to)

        layout.addLayout(bottom_layout)

    def _start_worker(self, worker: QThread):
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._forget_worker(w))
        worker.start()

    def _forget_worker(self, worker: QThread):
        if worker in self._workers:
            self._workers.remove(worker)

    def _extract_link_and_pwd(self, text: str) -> tuple:
        """从文本中提取链接和提取码"""
        text = text.strip()
        pwd = ""

        m = re.search(r'[?&]pwd=([A-Za-z0-9]{4})', text)
        if m:
            pwd = m.group(1)

        m2 = re.search(r'提取码\s*[:：]\s*([A-Za-z0-9]{4})', text)
        if m2:
            pwd = m2.group(1)

        m3 = re.search(r'(https?://\S+)\s+([A-Za-z0-9]{4})$', text)
        if m3:
            pwd = m3.group(2)

        parsed = self.api.parse_share_url(text)
        return parsed, pwd

    def _do_parse(self):
        link = self.edit_link.text().strip()
        pwd = self.edit_pwd.text().strip()

        if not link:
            self.lbl_status.setText("请输入分享链接")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        parsed, auto_pwd = self._extract_link_and_pwd(link)
        if not parsed:
            self.lbl_status.setText("无法解析该链接格式")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        if not pwd and auto_pwd:
            pwd = auto_pwd
            self.edit_pwd.setText(pwd)

        surl = parsed["surl"]
        self._current_surl = surl
        self._current_randsk = ""
        self._dir_stack = []
        self._update_nav()

        self.btn_parse.setEnabled(False)
        self.btn_parse.setText("解析中...")
        self.lbl_status.setText("正在解析...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        worker = ShareParseWorker(self.api, surl, pwd)
        worker.result.connect(self._on_parse_result)
        self._start_worker(worker)

    @pyqtSlot(dict)
    def _on_parse_result(self, data: dict):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("解析链接")
        self.tree.clear()

        if data.get("errno") != 0:
            errmsg = data.get("errmsg", "")
            errno = data.get("errno", "")
            if errno == -12:
                errmsg = "提取码错误"
            elif errno == -9:
                errmsg = "链接已过期或不存在"
            self.lbl_status.setText(f"解析失败: {errmsg} (errno={errno})")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            self.btn_transfer.setEnabled(False)
            self.btn_save_to.setEnabled(False)
            return

        # 保存shareid和uk
        self._shareid = str(data.get("shareid", ""))
        self._uk = str(data.get("uk", ""))
        self._current_randsk = str(data.get("randsk", self._current_randsk))

        file_list = data.get("list", [])
        self._show_file_list(file_list)

    def _show_file_list(self, file_list):
        """显示文件列表"""
        self.tree.clear()
        self.lbl_status.setText(f"共 {len(file_list)} 个项目")
        self.lbl_status.setStyleSheet("color: #5BA85B;")

        for item in file_list:
            is_dir = item.get("isdir", 0) == 1
            filename = item.get("server_filename", "")
            size = item.get("size", 0)

            tree_item = QTreeWidgetItem()
            ftype = "folder" if is_dir else get_file_type(filename)
            icon = FILE_TYPE_ICONS.get(ftype, FILE_TYPE_ICONS["other"])

            tree_item.setText(0, f"{icon} {filename}")
            tree_item.setText(1, "" if is_dir else format_size(size))
            tree_item.setText(2, "文件夹（双击进入）" if is_dir else ftype)

            tree_item.setData(0, Qt.UserRole, {
                "fs_id": item.get("fs_id", 0),
                "filename": filename,
                "isdir": is_dir,
                "size": size,
                "path": item.get("path", ""),
            })

            self.tree.addTopLevelItem(tree_item)

        has_items = len(file_list) > 0
        self.btn_transfer.setEnabled(has_items)
        self.btn_save_to.setEnabled(has_items)

    def _on_item_double_clicked(self, index):
        """双击文件夹 → 展开进入"""
        item = self.tree.currentItem()
        if not item:
            return
        meta = item.data(0, Qt.UserRole)
        if not meta or not meta.get("isdir"):
            return

        dir_path = meta.get("path", "")
        if not dir_path:
            return

        if not self._shareid or not self._uk:
            self.lbl_status.setText("无法进入子目录（缺少 shareid/uk）")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        # 记录当前路径
        self._dir_stack.append(dir_path)
        self._update_nav()

        self.lbl_status.setText(f"正在加载: {dir_path}")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        worker = ShareDirWorker(self.api, self._shareid, self._uk, dir_path)
        worker.result.connect(self._on_dir_result)
        self._start_worker(worker)

    @pyqtSlot(str, dict)
    def _on_dir_result(self, dir_path: str, data: dict):
        if data.get("errno") != 0:
            errmsg = data.get("errmsg", str(data.get("errno", "")))
            self.lbl_status.setText(f"加载目录失败: {errmsg}")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            # 弹出路径栈
            if self._dir_stack and self._dir_stack[-1] == dir_path:
                self._dir_stack.pop()
                self._update_nav()
            return

        file_list = data.get("list", [])
        self._show_file_list(file_list)

    def _go_back(self):
        """返回上级目录"""
        if not self._dir_stack:
            return

        self._dir_stack.pop()
        self._update_nav()

        if not self._dir_stack:
            # 回到根目录 → 重新解析
            self._do_parse()
        else:
            parent_path = self._dir_stack[-1]
            # 加载父目录
            # 先弹出再加载（因为加载成功不会再push）
            self._dir_stack.pop()
            self._dir_stack.append(parent_path)

            worker = ShareDirWorker(self.api, self._shareid, self._uk, parent_path)
            worker.result.connect(self._on_dir_result)
            self._start_worker(worker)

    def _update_nav(self):
        """更新路径导航"""
        if self._dir_stack:
            self.btn_back.setVisible(True)
            self.btn_back.setEnabled(True)
            self.lbl_path.setText(f"当前路径: {self._dir_stack[-1]}")
        else:
            self.btn_back.setVisible(False)
            self.btn_back.setEnabled(False)
            self.lbl_path.setText("")

    def _get_selected_items(self) -> list:
        """获取当前高亮选中的项目。"""
        return self.tree.selectedItems()

    def _get_selected_fs_ids(self) -> list:
        items = self._get_selected_items()
        fs_ids = []
        for item in items:
            meta = item.data(0, Qt.UserRole)
            if meta:
                fs_ids.append(meta["fs_id"])
        return fs_ids

    def _get_selected_files(self) -> list:
        """获取选中的非文件夹文件: [(fs_id, filename, size), ...]"""
        items = self._get_selected_items()
        files = []
        for item in items:
            meta = item.data(0, Qt.UserRole)
            if meta and not meta.get("isdir"):
                files.append((meta["fs_id"], meta["filename"], meta["size"]))
        return files

    def _do_transfer(self):
        fs_ids = self._get_selected_fs_ids()
        if not fs_ids:
            self.lbl_status.setText("请先选择要转存的文件")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return
        self.lbl_status.setText("正在转存...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")
        self.btn_transfer.setEnabled(False)

        worker = TransferWorker(self.api, self._current_surl, fs_ids, "/", self._current_randsk)
        worker.result.connect(self._on_transfer_result)
        self._start_worker(worker)

    @pyqtSlot(dict)
    def _on_transfer_result(self, data: dict):
        self.btn_transfer.setEnabled(True)
        if data.get("errno") == 0:
            self.lbl_status.setText("转存成功！文件已保存到网盘根目录")
            self.lbl_status.setStyleSheet("color: #16A34A;")
        else:
            errmsg = data.get("errmsg", str(data.get("errno", "")))
            self.lbl_status.setText(f"转存失败: {errmsg}")
            self.lbl_status.setStyleSheet("color: #EF4444;")

    def _do_transfer_and_download(self):
        """一键转存+下载+下载完成后自动删除转存"""
        if not self._get_selected_items():
            self.lbl_status.setText("请先选择要下载的文件")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return
        files = self._get_selected_files()
        if not files:
            self.lbl_status.setText("选中的项目不包含可下载文件，文件夹需要先进入")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            return

        # 转存到唯一临时目录，避免误删用户自己的同名目录
        job_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        transfer_path = f"/__pdm_tmp__/{job_id}"

        self.btn_save_to.setEnabled(False)
        self.btn_transfer.setEnabled(False)
        self.lbl_status.setText(f"正在转存 {len(files)} 个文件...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")

        self._current_transfer_job_id = job_id
        self._current_transfer_root = transfer_path

        worker = TransferDownloadWorker(
            self.api, self._current_surl, files,
            transfer_path, self._current_randsk
        )
        worker.progress.connect(self._on_transfer_dl_progress)
        worker.result.connect(self._on_transfer_dl_result)
        self._start_worker(worker)

    @pyqtSlot(str, bool)
    def _on_transfer_dl_progress(self, msg: str, is_error: bool):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #EF4444;" if is_error else "color: #F59E0B;")

    @pyqtSlot(list)
    def _on_transfer_dl_result(self, results: list):
        self.btn_save_to.setEnabled(True)
        self.btn_transfer.setEnabled(True)

        if not results:
            self._delete_transfer_root(self._current_transfer_root, "转存失败，已尝试清理临时目录")
            self._current_transfer_job_id = ""
            self._current_transfer_root = ""
            return

        save_dir = self.config.get("download_dir", os.path.expanduser("~/Downloads"))
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            self.lbl_status.setText(f"下载目录不可用: {e}")
            self.lbl_status.setStyleSheet("color: #EF4444;")
            self._delete_transfer_root(
                self._current_transfer_root,
                "下载目录不可用，已清理转存临时目录",
            )
            self._current_transfer_job_id = ""
            self._current_transfer_root = ""
            return
        success = 0
        failed = 0
        delete_paths = []
        task_ids = []
        planned_paths = set()

        for filename, dlink, size, transferred_path in results:
            if transferred_path:
                delete_paths.append(transferred_path)
            if dlink:
                save_path = make_unique_save_path(save_dir, filename, planned_paths)
                task_id = self.dm.add_task(
                    filename=filename,
                    dlink=dlink,
                    save_path=save_path,
                    total_size=size,
                    file_path=transferred_path or "",
                )
                task_ids.append(task_id)
                success += 1
            else:
                failed += 1

        msg = f"已添加 {success} 个下载任务"
        if failed:
            msg += f"，{failed} 个文件获取链接失败"
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #16A34A;" if not failed else "color: #F59E0B;")

        job_id = self._current_transfer_job_id
        root = self._current_transfer_root
        self._current_transfer_job_id = ""
        self._current_transfer_root = ""

        if not task_ids:
            self._delete_transfer_root(root, "未创建下载任务，已清理转存临时目录")
            return

        if delete_paths:
            self._cleanup_jobs[job_id] = {
                "root": root,
                "paths": delete_paths,
                "task_ids": set(task_ids),
            }
            if not self._auto_delete_hooked:
                self.dm.on("status_changed", self._check_auto_delete)
                self._auto_delete_hooked = True

    def _check_auto_delete(self, task_id, status):
        """当某个转存批次的下载任务全部结束后，自动删除该批次临时目录。"""
        from src.core.aria2_downloader import DownloadStatus
        if status not in (DownloadStatus.COMPLETED, DownloadStatus.ERROR):
            return

        tasks = {task.task_id: task for task in self.dm.get_tasks()}
        finished_jobs = []
        for job_id, job in self._cleanup_jobs.items():
            task_ids = job["task_ids"]
            terminal = all(
                tid not in tasks or tasks[tid].status in (
                    DownloadStatus.COMPLETED,
                    DownloadStatus.ERROR,
                )
                for tid in task_ids
            )
            if terminal:
                finished_jobs.append(job_id)

        for job_id in finished_jobs:
            job = self._cleanup_jobs.pop(job_id, None)
            if not job:
                continue
            root = job.get("root", "")
            paths = job.get("paths", [])
            self._cleanup_requested.emit(
                root,
                "下载结束，已自动清理转存临时目录",
                paths,
            )

    def _delete_transfer_root(self, root: str, success_message: str,
                              fallback_paths: list = None):
        """优先删除唯一临时目录，失败时回退删除已知文件路径。"""
        targets = [root] if root else (fallback_paths or [])
        if not targets:
            return
        self.lbl_status.setText("正在清理转存临时目录...")
        self.lbl_status.setStyleSheet("color: #F59E0B;")
        worker = CleanupTransferWorker(
            self.api, root, success_message, fallback_paths or []
        )
        worker.result.connect(self._on_cleanup_result)
        self._start_worker(worker)

    @pyqtSlot(bool, str, str)
    def _on_cleanup_result(self, success: bool, message: str, detail: str):
        logger.info(f" 转存清理结果: success={success}, detail={detail}")
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(
            "color: #16A34A;" if success else "color: #F59E0B;"
        )
