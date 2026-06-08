"""
下载管理标签页：显示所有下载任务的进度、状态
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QAbstractItemView, QMenu
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from .utils import format_size, format_speed, format_eta
from ..core.aria2_downloader import DownloadStatus


class DownloadsTab(QWidget):
    def __init__(self, download_manager):
        super().__init__()
        self.dm = download_manager
        self._progress_bars = {}
        self._init_ui()
        self._setup_timer()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部按钮
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        self.lbl_summary = QLabel("暂无下载任务")
        self.lbl_summary.setStyleSheet("font-size: 13px; color: #64748B;")
        top_layout.addWidget(self.lbl_summary, 1)

        self.btn_pause_all = QPushButton("全部暂停")
        self.btn_pause_all.setMinimumHeight(30)
        self.btn_pause_all.setObjectName("btnWarning")
        self.btn_pause_all.clicked.connect(self._pause_all)

        self.btn_resume_all = QPushButton("全部恢复")
        self.btn_resume_all.setMinimumHeight(30)
        self.btn_resume_all.setObjectName("btnSuccess")
        self.btn_resume_all.clicked.connect(self._resume_all)

        self.btn_remove_selected = QPushButton("移除所选")
        self.btn_remove_selected.setMinimumHeight(30)
        self.btn_remove_selected.setObjectName("btnFlat")
        self.btn_remove_selected.clicked.connect(self._remove_selected)
        self.btn_remove_selected.setEnabled(False)

        self.btn_clear_completed = QPushButton("清除已完成")
        self.btn_clear_completed.setMinimumHeight(30)
        self.btn_clear_completed.setObjectName("btnFlat")
        self.btn_clear_completed.clicked.connect(self._clear_completed)

        top_layout.addWidget(self.btn_pause_all)
        top_layout.addWidget(self.btn_resume_all)
        top_layout.addWidget(self.btn_remove_selected)
        top_layout.addWidget(self.btn_clear_completed)

        layout.addLayout(top_layout)

        # 下载列表表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["文件名", "大小", "进度", "速度", "剩余时间", "状态"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._sync_actions)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(2, 160)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)

        layout.addWidget(self.table, 1)

    def _setup_timer(self):
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start(800)

    def _refresh_table(self):
        tasks = self.dm.get_tasks()

        # 更新摘要
        total = len(tasks)
        downloading = sum(1 for t in tasks if t.status == DownloadStatus.DOWNLOADING)
        completed = sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED)
        self.lbl_summary.setText(
            f"共 {total} 个任务  |  下载中 {downloading}  |  已完成 {completed}"
        )

        # 调整行数
        self.table.setRowCount(len(tasks))
        active_task_ids = {task.task_id for task in tasks}
        for task_id in list(self._progress_bars):
            if task_id not in active_task_ids:
                del self._progress_bars[task_id]

        for row, task in enumerate(tasks):
            # 文件名
            name_item = QTableWidgetItem(task.filename)
            name_item.setData(Qt.UserRole, task.task_id)
            self.table.setItem(row, 0, name_item)

            # 大小
            size_text = format_size(task.total_size) if task.total_size > 0 else "未知"
            self.table.setItem(row, 1, QTableWidgetItem(size_text))

            # 进度条
            if task.task_id not in self._progress_bars:
                pbar = QProgressBar()
                pbar.setMinimum(0)
                pbar.setMaximum(100)
                self._progress_bars[task.task_id] = pbar
            pbar = self._progress_bars[task.task_id]

            if task.total_size > 0:
                pct = int(task.downloaded_size * 100 / task.total_size)
                pbar.setValue(pct)
                pbar.setFormat(f"{pct}%  ({format_size(task.downloaded_size)})")
            else:
                pbar.setValue(0)
                pbar.setFormat(format_size(task.downloaded_size))

            self.table.setCellWidget(row, 2, pbar)

            # 速度
            if task.status == DownloadStatus.DOWNLOADING:
                speed_text = format_speed(task.speed)
                if hasattr(task, 'connections') and task.connections > 0:
                    speed_text += f"  ({task.connections}连接)"
            else:
                speed_text = ""
            self.table.setItem(row, 3, QTableWidgetItem(speed_text))

            # 剩余时间
            remaining = task.total_size - task.downloaded_size
            eta_text = format_eta(remaining, task.speed) if task.status == DownloadStatus.DOWNLOADING else ""
            self.table.setItem(row, 4, QTableWidgetItem(eta_text))

            # 状态
            status_map = {
                DownloadStatus.WAITING: ("等待中", "#64748B"),
                DownloadStatus.DOWNLOADING: ("下载中", "#2563EB"),
                DownloadStatus.PAUSED: ("已暂停", "#94A3B8"),
                DownloadStatus.COMPLETED: ("已完成", "#16A34A"),
                DownloadStatus.ERROR: ("错误", "#DC2626"),
            }
            status_text, status_color = status_map.get(
                task.status, ("未知", "#9B9590")
            )
            if task.status == DownloadStatus.ERROR and task.error_msg:
                status_text += f": {task.error_msg[:30]}"
            status_item = QTableWidgetItem(status_text)
            from PyQt5.QtGui import QColor
            status_item.setForeground(QColor(status_color))
            self.table.setItem(row, 5, status_item)
        self._sync_actions()

    def _selected_task_ids(self) -> list[str]:
        task_ids = []
        seen = set()
        for item in self.table.selectedItems():
            row = item.row()
            name_item = self.table.item(row, 0)
            if not name_item:
                continue
            task_id = name_item.data(Qt.UserRole)
            if task_id and task_id not in seen:
                seen.add(task_id)
                task_ids.append(task_id)
        return task_ids

    def _sync_actions(self):
        self.btn_remove_selected.setEnabled(bool(self._selected_task_ids()))

    def _show_context_menu(self, pos):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        task_id = item.data(Qt.UserRole)

        menu = QMenu(self)
        task = self.dm.get_task(task_id)
        if not task:
            return

        if task.status == DownloadStatus.DOWNLOADING:
            act_pause = menu.addAction("暂停")
            act_pause.triggered.connect(lambda: self.dm.pause_task(task_id))
        elif task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            act_resume = menu.addAction("恢复")
            act_resume.triggered.connect(lambda: self.dm.resume_task(task_id))

        if task.status == DownloadStatus.COMPLETED:
            act_open = menu.addAction("打开文件夹")
            act_open.triggered.connect(
                lambda: os.startfile(os.path.dirname(task.save_path))
            )

        menu.addSeparator()
        act_remove = menu.addAction("移除任务")
        act_remove.triggered.connect(lambda: self._remove_task(task_id))

        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _remove_task(self, task_id: str):
        self.dm.remove_task(task_id)
        if task_id in self._progress_bars:
            del self._progress_bars[task_id]
        self._refresh_table()

    def _remove_selected(self):
        for task_id in self._selected_task_ids():
            self.dm.remove_task(task_id)
            if task_id in self._progress_bars:
                del self._progress_bars[task_id]
        self._refresh_table()

    def _pause_all(self):
        for task in self.dm.get_tasks():
            if task.status == DownloadStatus.DOWNLOADING:
                self.dm.pause_task(task.task_id)

    def _resume_all(self):
        for task in self.dm.get_tasks():
            if task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
                self.dm.resume_task(task.task_id)

    def _clear_completed(self):
        for task in self.dm.get_tasks():
            if task.status == DownloadStatus.COMPLETED:
                self.dm.remove_task(task.task_id)
                if task.task_id in self._progress_bars:
                    del self._progress_bars[task.task_id]
        self._refresh_table()
