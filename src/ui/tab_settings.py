"""
设置标签页：下载设置、应用信息
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QSpinBox, QLineEdit, QFileDialog,
    QSlider,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from ..core.config import save_config


class SettingsTab(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, config, download_manager):
        super().__init__()
        self.config = config
        self.dm = download_manager
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        # ── 下载设置 ──
        dl_group = QGroupBox("下载设置")
        dl_layout = QFormLayout(dl_group)
        dl_layout.setHorizontalSpacing(14)
        dl_layout.setVerticalSpacing(14)
        dl_layout.setContentsMargins(18, 26, 18, 18)
        dl_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # 下载目录
        dir_layout = QHBoxLayout()
        self.edit_dl_dir = QLineEdit()
        self.edit_dl_dir.setMinimumHeight(32)
        self.edit_dl_dir.setReadOnly(True)
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.setMinimumHeight(36)
        self.btn_browse.setMinimumWidth(84)
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.edit_dl_dir)
        dir_layout.addWidget(self.btn_browse)
        dl_layout.addRow("下载目录:", dir_layout)

        # 同时下载任务数
        self.spin_tasks = QSpinBox()
        self.spin_tasks.setRange(1, 8)
        self.spin_tasks.setMinimumHeight(32)
        dl_layout.addRow("同时下载任务数:", self.spin_tasks)

        # 单任务连接数
        self.spin_connections = QSpinBox()
        self.spin_connections.setRange(1, 16)
        self.spin_connections.setMinimumHeight(32)
        dl_layout.addRow("单任务连接数:", self.spin_connections)

        # 速度限制
        speed_layout = QHBoxLayout()
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(0, 102400)  # 0-100MB/s in KB/s
        self.slider_speed.setSingleStep(512)
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        self.lbl_speed = QLabel("不限速")
        self.lbl_speed.setMinimumWidth(100)
        speed_layout.addWidget(self.slider_speed)
        speed_layout.addWidget(self.lbl_speed)
        dl_layout.addRow("速度限制:", speed_layout)

        layout.addWidget(dl_group)

        # ── 应用信息 ──
        info_group = QGroupBox("关于")
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(12)
        info_layout.setContentsMargins(18, 26, 18, 18)

        # aria2 状态
        self.lbl_aria2 = QLabel("")
        self.lbl_aria2.setWordWrap(True)
        self._update_aria2_status()
        info_layout.addWidget(self.lbl_aria2)

        learn_label = QLabel("仅供学习使用")
        learn_label.setObjectName("mutedText")
        info_layout.addWidget(learn_label)

        github_label = QLabel(
            'GitHub: <a href="https://github.com/WenJiazhi/pdm">'
            'https://github.com/WenJiazhi/pdm</a>'
        )
        github_label.setOpenExternalLinks(True)
        github_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        github_label.setObjectName("linkLabel")
        github_label.setWordWrap(True)
        info_layout.addWidget(github_label)

        # 定时刷新 aria2 状态（等后台线程启动完毕）
        self._aria2_timer = QTimer(self)
        self._aria2_timer.timeout.connect(self._update_aria2_status)
        self._aria2_timer.start(3000)  # 每3秒检查一次

        layout.addWidget(info_group)

        # 保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("保存设置")
        self.btn_save.setObjectName("btnSuccess")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.setMinimumWidth(140)
        self.btn_save.clicked.connect(self._save_settings)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _load_values(self):
        self.edit_dl_dir.setText(self.config.get("download_dir", ""))
        self.spin_tasks.setValue(self.config.get("max_concurrent_tasks", 2))
        self.spin_connections.setValue(self.config.get("task_connections", 16))

        speed = self.config.get("speed_limit", 0)
        self.slider_speed.setValue(speed)
        self._update_speed_label(speed)

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择下载目录", self.edit_dl_dir.text()
        )
        if path:
            self.edit_dl_dir.setText(path)

    def _on_speed_changed(self, value: int):
        self._update_speed_label(value)

    def _update_speed_label(self, value: int):
        if value == 0:
            self.lbl_speed.setText("不限速")
        elif value < 1024:
            self.lbl_speed.setText(f"{value} KB/s")
        else:
            self.lbl_speed.setText(f"{value / 1024:.1f} MB/s")

    def _save_settings(self):
        self.config["download_dir"] = self.edit_dl_dir.text()
        self.config["max_concurrent_tasks"] = self.spin_tasks.value()
        self.config["task_connections"] = self.spin_connections.value()
        self.config.pop("max_concurrent", None)
        self.config.pop("connections_per_file", None)
        self.config["speed_limit"] = self.slider_speed.value()

        # 更新下载管理器
        self.dm.update_settings(
            max_concurrent_tasks=self.config["max_concurrent_tasks"],
            task_connections=self.config["task_connections"],
            speed_limit=self.config["speed_limit"],
        )
        self._update_aria2_status()

        save_config(self.config)
        self.config_changed.emit()

        self.btn_save.setText("已保存")
        QTimer.singleShot(2000, lambda: self.btn_save.setText("保存设置"))

    def _update_aria2_status(self):
        if hasattr(self.dm, 'is_aria2_available') and self.dm.is_aria2_available():
            tasks = getattr(self.dm, "max_concurrent_downloads", self.config.get("max_concurrent_tasks", 2))
            connections = getattr(self.dm, "task_connections", self.config.get("task_connections", 16))
            self.lbl_aria2.setText(
                f"Aria 已就位：同时任务 {tasks}，单任务连接 {connections}"
            )
            self.lbl_aria2.setStyleSheet("color: #16A34A; font-weight: 500;")
            if hasattr(self, '_aria2_timer') and self._aria2_timer.isActive():
                self._aria2_timer.stop()
        else:
            self.lbl_aria2.setText("Aria 未就位：使用内置单线程下载")
            self.lbl_aria2.setStyleSheet("color: #F59E0B;")
