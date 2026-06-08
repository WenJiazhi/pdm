"""
基于 aria2c RPC 的下载管理器
支持多线程下载、断点续传、速度限制、队列管理
"""
import json
import os
import socket
import subprocess
import sys
import time
import threading
import queue
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable

import requests

from .api import BaiduPanAPI
from .config import APP_DIR
from .logger import get_logger

logger = get_logger()
DOWNLOADS_PATH = os.path.join(APP_DIR, "downloads.json")


class DownloadStatus(Enum):
    WAITING = "waiting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class DownloadTask:
    task_id: str
    filename: str
    fs_id: int
    dlink: str
    save_path: str
    total_size: int = 0
    downloaded_size: int = 0
    status: DownloadStatus = DownloadStatus.WAITING
    speed: float = 0.0
    error_msg: str = ""
    custom_headers: dict = field(default_factory=dict)
    aria2_gid: str = ""  # aria2 download GID
    connections: int = 0  # 当前连接数
    pan_path: str = ""
    expected_size: int = 0
    retry_count: int = 0
    updated_at: float = field(default_factory=time.time)
    _finish_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self):
        # Backward-compatible attribute names used by older retry paths.
        self._pan_path = self.pan_path
        self._expected_size = self.expected_size or self.total_size
        self._retry_count = self.retry_count

    @property
    def is_terminal(self) -> bool:
        return self.status in (DownloadStatus.COMPLETED, DownloadStatus.ERROR)


def _find_aria2c() -> str:
    """查找 aria2c 可执行文件"""
    # 1. PyInstaller --onefile 模式 (_MEIPASS)
    if hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, 'aria2c.exe')
        if os.path.isfile(bundled):
            return bundled

    # 2. PyInstaller --onedir 模式 (exe 旁边的 _internal 目录)
    exe_dir = os.path.dirname(sys.executable)
    internal = os.path.join(exe_dir, '_internal', 'aria2c.exe')
    if os.path.isfile(internal):
        return internal
    # 也可能直接和 exe 同目录
    beside_exe = os.path.join(exe_dir, 'aria2c.exe')
    if os.path.isfile(beside_exe):
        return beside_exe

    # 3. 项目 tools 目录 (开发模式)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tools_path = os.path.join(project_root, 'tools', 'aria2c.exe')
    if os.path.isfile(tools_path):
        return tools_path

    # 4. PATH
    import shutil
    found = shutil.which('aria2c')
    if found:
        return found

    return ""


class DownloadManager:
    """基于 aria2c RPC 的下载管理器"""

    RPC_PORT = 16850  # 避免和其他aria2冲突
    RPC_HOST = "127.0.0.1"
    RPC_URL = f"http://{RPC_HOST}:{RPC_PORT}/jsonrpc"
    RPC_SECRET = "bduss_dl_token"

    def __init__(self, api: BaiduPanAPI, max_concurrent_tasks: int = 2,
                 task_connections: int = 16, speed_limit: int = 0):
        self.api = api
        self.max_concurrent_downloads = max(1, min(16, int(max_concurrent_tasks)))
        self.task_connections = max(1, min(16, int(task_connections)))
        self.speed_limit = max(0, int(speed_limit or 0))  # KB/s, 0=无限

        self._tasks: dict[str, DownloadTask] = {}
        self._task_order: list[str] = []
        self._gid_to_task: dict[str, str] = {}  # aria2 gid -> task_id
        self._lock = threading.Lock()
        self._running = True
        self._aria2_process: Optional[subprocess.Popen] = None
        self._aria2_ready = False
        self._aria2c_path = _find_aria2c()
        self._rpc_session = requests.Session()
        self._rpc_session.trust_env = False

        self._callbacks: dict[str, list[Callable]] = {
            "progress": [],
            "status_changed": [],
            "speed_update": [],
        }
        self._last_persist_time = 0.0

        # 任务提交队列（提交给 aria2 后由 aria2 控制并发数）
        self._submit_queue: queue.Queue[DownloadTask] = queue.Queue()

        self._load_persisted_tasks()

        # 启动 aria2c RPC 服务（后台线程，不阻塞GUI）
        self._aria2_init_thread = threading.Thread(target=self._start_aria2c, daemon=True)
        self._aria2_init_thread.start()

        # 状态轮询线程
        self._poll_thread = threading.Thread(target=self._poll_status, daemon=True)
        self._poll_thread.start()

        # 任务提交工作线程（不阻塞 GUI）
        self._submit_thread = threading.Thread(target=self._submit_worker, daemon=True)
        self._submit_thread.start()

    # ─── aria2c 进程管理 ─────────────────────────────────────

    def _start_aria2c(self):
        """启动 aria2c RPC 后台服务"""
        logger.info(f"aria2c path: {self._aria2c_path or 'not found'}")
        if not self._aria2c_path:
            logger.warning(" aria2c not found, downloads will use fallback mode")
            return

        # 只在端口已打开时探测已有 RPC，避免空端口连接在部分环境下长时间 SYN_SENT。
        if self._is_rpc_port_open():
            try:
                self._rpc_call("aria2.getVersion", timeout=(0.5, 2))
                self._aria2_ready = True
                self._apply_aria2_options()
                logger.info(f" aria2c RPC already running on port {self.RPC_PORT}")
                return
            except Exception as e:
                logger.warning(f" aria2 RPC port is open but not usable: {e}")

        args = [
            self._aria2c_path,
            '--enable-rpc',
            f'--rpc-listen-port={self.RPC_PORT}',
            f'--rpc-secret={self.RPC_SECRET}',
            '--rpc-allow-origin-all=true',
            '--rpc-listen-all=false',
            f'--max-concurrent-downloads={self.max_concurrent_downloads}',
            f'--max-connection-per-server={self.task_connections}',
            f'--split={self.task_connections}',
            '--min-split-size=1M',
            '--continue=true',
            '--auto-file-renaming=false',
            '--allow-overwrite=true',
            '--file-allocation=none',
            '--console-log-level=warn',
            '--summary-interval=0',
            '--user-agent=' + self.api.UA,
            '--check-certificate=false',
        ]

        if self.speed_limit > 0:
            args.append(f'--max-overall-download-limit={self.speed_limit}K')

        try:
            creation_flags = subprocess.CREATE_NO_WINDOW
            log_dir = os.path.join(os.path.expanduser("~"), ".pdm", "logs")
            os.makedirs(log_dir, exist_ok=True)
            aria2_log = os.path.join(log_dir, "aria2c.log")
            with open(aria2_log, "a", encoding="utf-8") as stderr_handle:
                self._aria2_process = subprocess.Popen(
                    args,
                    creationflags=creation_flags,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_handle,
                    cwd=os.path.dirname(self._aria2c_path),
                )
            logger.info(f" aria2c process started, pid={self._aria2_process.pid}")

            # 等待 RPC 就绪
            for _ in range(30):
                time.sleep(0.2)
                try:
                    if self._aria2_process.poll() is not None:
                        logger.warning(
                            f" aria2c exited early with code {self._aria2_process.returncode}"
                        )
                        break
                    self._rpc_call("aria2.getVersion", timeout=(0.5, 2))
                    self._aria2_ready = True
                    logger.info(f" aria2c RPC ready on port {self.RPC_PORT}")
                    return
                except Exception:
                    continue

            logger.warning(" aria2c RPC failed to start")

        except Exception as e:
            logger.warning(f" Failed to start aria2c: {e}")

    def _is_rpc_port_open(self) -> bool:
        """快速检查 RPC 端口是否已有监听，不能用 HTTP 探测空端口。"""
        try:
            with socket.create_connection((self.RPC_HOST, self.RPC_PORT), timeout=0.25):
                return True
        except OSError:
            return False

    def _rpc_call(self, method: str, params: list = None, timeout=(1, 5)) -> dict:
        """发送 JSON-RPC 请求到 aria2c"""
        payload = {
            "jsonrpc": "2.0",
            "id": str(int(time.time() * 1000)),
            "method": method,
        }
        token_param = f"token:{self.RPC_SECRET}"
        if params:
            payload["params"] = [token_param] + params
        else:
            payload["params"] = [token_param]

        resp = self._rpc_session.post(self.RPC_URL, json=payload, timeout=timeout)
        result = resp.json()
        if "error" in result:
            raise RuntimeError(result["error"].get("message", str(result["error"])))
        return result.get("result", {})

    def _apply_aria2_options(self):
        """同步当前下载设置到已运行的 aria2 RPC 实例。"""
        opts = {
            "max-concurrent-downloads": str(self.max_concurrent_downloads),
            "max-connection-per-server": str(self.task_connections),
            "split": str(self.task_connections),
            "max-overall-download-limit": (
                f"{self.speed_limit}K" if self.speed_limit > 0 else "0"
            ),
        }
        self._rpc_call("aria2.changeGlobalOption", [opts])

    # ─── 回调注册 ──────────────────────────────────────────────

    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args):
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception:
                pass
        if event == "status_changed":
            self._persist_tasks(force=True)
        elif event in ("progress", "speed_update"):
            self._persist_tasks(force=False)

    def _task_to_record(self, task: DownloadTask) -> dict:
        return {
            "task_id": task.task_id,
            "filename": task.filename,
            "fs_id": task.fs_id,
            "dlink": task.dlink,
            "save_path": task.save_path,
            "total_size": int(task.total_size or 0),
            "downloaded_size": int(task.downloaded_size or 0),
            "status": task.status.value,
            "error_msg": task.error_msg,
            "custom_headers": task.custom_headers,
            "pan_path": getattr(task, "_pan_path", task.pan_path),
            "expected_size": int(getattr(task, "_expected_size", task.expected_size or task.total_size or 0)),
            "retry_count": int(getattr(task, "_retry_count", task.retry_count or 0)),
            "connections": int(task.connections or 0),
            "updated_at": time.time(),
        }

    def _record_to_task(self, record: dict) -> Optional[DownloadTask]:
        try:
            status = DownloadStatus(record.get("status", DownloadStatus.PAUSED.value))
        except ValueError:
            status = DownloadStatus.ERROR
        if status in (DownloadStatus.DOWNLOADING, DownloadStatus.WAITING):
            status = DownloadStatus.PAUSED

        save_path = record.get("save_path", "")
        downloaded_size = int(record.get("downloaded_size") or 0)
        if status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            downloaded_size = max(downloaded_size, self._file_size(save_path))
        elif status == DownloadStatus.COMPLETED and os.path.exists(save_path):
            downloaded_size = max(downloaded_size, self._file_size(save_path))

        task = DownloadTask(
            task_id=record.get("task_id") or f"restored_{uuid.uuid4().hex}",
            filename=record.get("filename") or os.path.basename(save_path) or "download",
            fs_id=int(record.get("fs_id") or 0),
            dlink=record.get("dlink") or "",
            save_path=save_path,
            total_size=int(record.get("total_size") or record.get("expected_size") or 0),
            downloaded_size=downloaded_size,
            status=status,
            speed=0.0,
            error_msg=record.get("error_msg", ""),
            custom_headers=record.get("custom_headers") or {},
            connections=int(record.get("connections") or 0),
            pan_path=record.get("pan_path", ""),
            expected_size=int(record.get("expected_size") or record.get("total_size") or 0),
            retry_count=int(record.get("retry_count") or 0),
            updated_at=float(record.get("updated_at") or time.time()),
        )
        task.aria2_gid = ""
        return task

    def _load_persisted_tasks(self):
        if not os.path.exists(DOWNLOADS_PATH):
            return
        try:
            with open(DOWNLOADS_PATH, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception as e:
            logger.warning(f" failed to load download records: {e}")
            return
        if not isinstance(records, list):
            return
        with self._lock:
            for record in records:
                task = self._record_to_task(record)
                if not task or task.task_id in self._tasks:
                    continue
                self._tasks[task.task_id] = task
                self._task_order.append(task.task_id)
        logger.info(f" restored {len(self._task_order)} download tasks")

    def _persist_tasks(self, force: bool = False):
        now = time.time()
        if not force and now - self._last_persist_time < 1.0:
            return
        self._last_persist_time = now
        try:
            os.makedirs(os.path.dirname(DOWNLOADS_PATH), exist_ok=True)
            with self._lock:
                records = [
                    self._task_to_record(self._tasks[tid])
                    for tid in self._task_order
                    if tid in self._tasks
                ]
            tmp_path = DOWNLOADS_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, DOWNLOADS_PATH)
        except Exception as e:
            logger.warning(f" failed to save download records: {e}")

    def _file_size(self, path: str) -> int:
        try:
            return os.path.getsize(path) if path and os.path.exists(path) else 0
        except OSError:
            return 0

    def save_now(self):
        self._persist_tasks(force=True)

    # ─── 任务管理 ──────────────────────────────────────────────

    def add_task(self, filename: str = "", fs_id: int = 0, dlink: str = "",
                 save_path: str = "", total_size: int = 0,
                 url: str = "", headers: dict = None,
                 file_path: str = "") -> str:
        actual_url = url or dlink
        task_id = (
            f"{fs_id or id(actual_url)}_{int(time.time()*1000)}_"
            f"{uuid.uuid4().hex[:8]}"
        )
        task = DownloadTask(
            task_id=task_id,
            filename=filename,
            fs_id=fs_id,
            dlink=actual_url,
            save_path=save_path,
            total_size=total_size,
            custom_headers=headers or {},
            pan_path=file_path or "",
            expected_size=total_size,
        )
        # 存储文件在网盘中的路径，PCS API需要
        task._pan_path = file_path
        # 保存原始期望的文件大小，用于完成后校验
        task._expected_size = total_size

        with self._lock:
            self._tasks[task_id] = task
            self._task_order.append(task_id)

        # 放入队列，由后台工作线程逐个提交（不阻塞 GUI）
        self._submit_queue.put(task)

        self._emit("status_changed", task_id, DownloadStatus.WAITING)
        logger.debug(f" Task queued: {filename}")
        return task_id

    def _submit_worker(self):
        """后台工作线程：提交任务，实际同时下载数量由 aria2 全局配置控制。"""
        while self._running:
            try:
                task = self._submit_queue.get(timeout=1)
            except queue.Empty:
                continue

            # 如果任务已被删除，跳过
            if task.task_id not in self._tasks:
                self._submit_queue.task_done()
                continue

            # 等待 aria2c 就绪
            for _ in range(30):
                if self._aria2_ready:
                    break
                time.sleep(0.5)

            if self._aria2_ready:
                try:
                    self._submit_to_aria2(task)
                except Exception as e:
                    logger.debug(f" Submit error: {e}")
                    task.status = DownloadStatus.ERROR
                    task.error_msg = str(e)
                    self._emit("status_changed", task.task_id, DownloadStatus.ERROR)
                    task._finish_event.set()
            else:
                logger.debug(f" aria2 not ready, using fallback for: {task.filename}")
                self._fallback_download(task)

            self._submit_queue.task_done()

    MAX_RETRIES = 5  # 最大重试次数

    def _wait_task_finish(self, task: DownloadTask):
        """阻塞等待任务下载完成、出错或被删除（使用 Event 避免竞态条件）"""
        while self._running:
            if task.task_id not in self._tasks:
                break
            if task._finish_event.wait(timeout=0.5):
                break

    def _get_task_connection_options(self) -> dict:
        connections = str(self.task_connections)
        return {
            "max-connection-per-server": connections,
            "split": connections,
            "min-split-size": "1M",
            "continue": "true",
        }

    def _resolve_cdn_url(self, dlink: str, pan_path: str = "",
                         fs_id: int = 0) -> tuple[str, bool, bool]:
        """
        通过 dlink 获取 CDN 下载地址。
        返回 (url, is_cdn, is_locate):
          - is_cdn: 是否成功获取到CDN的真实下载地址
          - is_locate: 是否通过 locatedownload 获取（需要特殊 UA）
        优先用 locatedownload 高速方法，再用 session 重定向，最后 PCS API。
        """
        from urllib.parse import quote

        # 方案 0: locatedownload（高速下载，需客户端签名）
        if pan_path:
            for app_id in ("250528", "778750"):
                locate_url = self.api.get_locate_download_url(pan_path, app_id)
                if locate_url:
                    return locate_url, True, True

        # 方案 1: session 跟随重定向
        try:
            resp = self.api.session.get(
                dlink,
                headers={"Referer": "https://pan.baidu.com/disk/home"},
                allow_redirects=True,
                stream=True,
                timeout=15,
            )
            status = resp.status_code
            final_url = resp.url
            resp.close()

            if status == 200 and final_url != dlink:
                logger.debug(f" CDN resolved via session redirect: {final_url[:120]}...")
                return final_url, True, False
            elif status == 200:
                # URL直接可下载，不需要跳转
                logger.debug(f" URL is direct download (no redirect)")
                return dlink, False, False
            elif status == 403:
                logger.debug(f" dlink returned 403, trying PCS API...")
            else:
                logger.debug(f" dlink status={status}, trying PCS API...")
        except Exception as e:
            logger.debug(f" Session redirect failed: {e}, trying PCS API...")

        # 方案 2: PCS file download API（使用文件路径）
        if pan_path:
            for app_id in ("250528", "778750"):
                try:
                    encoded_path = quote(pan_path)
                    pcs_url = (f"https://d.pcs.baidu.com/rest/2.0/pcs/file"
                               f"?method=download&path={encoded_path}"
                               f"&app_id={app_id}")
                    resp = self.api.session.get(
                        pcs_url,
                        headers={"Referer": "https://pan.baidu.com/disk/home"},
                        allow_redirects=False,
                        stream=True,
                        timeout=15,
                    )
                    status = resp.status_code
                    if status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location", "")
                        resp.close()
                        if location:
                            logger.debug(f" CDN resolved via PCS (app_id={app_id}): "
                                  f"{location[:120]}...")
                            return location, True, False
                    elif status == 200:
                        final_url = resp.url
                        resp.close()
                        if "baidupcs.com" in final_url:
                            logger.debug(f" CDN resolved via PCS (app_id={app_id}): "
                                  f"{final_url[:120]}...")
                            return final_url, True, False
                    else:
                        resp.close()
                        logger.debug(f" PCS (app_id={app_id}) status={status}")
                except Exception as e:
                    logger.debug(f" PCS (app_id={app_id}) failed: {e}")

        # 方案 3: 直接用 dlink + allow_redirects=False 获取302 Location
        try:
            resp = self.api.session.get(
                dlink,
                headers={"Referer": "https://pan.baidu.com/disk/home"},
                allow_redirects=False,
                stream=True,
                timeout=15,
            )
            status = resp.status_code
            if status in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                resp.close()
                if location:
                    logger.debug(f" CDN resolved via 302: {location[:120]}...")
                    return location, True, False
            resp.close()
        except Exception:
            pass

        logger.debug(f" All redirect methods failed for dlink")
        return dlink, False, False

    def _submit_to_aria2(self, task: DownloadTask):
        """发送下载任务到 aria2c"""
        try:
            real_url, is_cdn, is_locate = self._resolve_cdn_url(
                task.dlink, getattr(task, '_pan_path', ''),
                fs_id=task.fs_id,
            )

            # locatedownload 需要特殊 UA
            if is_locate:
                bduss = self.api._get_bduss()
                header_list = [
                    f"User-Agent: {self.api.PCS_UA}",
                    f"Cookie: BDUSS={bduss};",
                ]
            elif is_cdn:
                # CDN URL 不需要 Cookie（认证信息已在URL参数中），只需 User-Agent
                header_list = [
                    f"User-Agent: {self.api.UA}",
                    "Referer: https://pan.baidu.com/disk/home",
                ]
            else:
                cookie_str = self._build_cookie_header()
                header_list = [
                    f"User-Agent: {self.api.UA}",
                    f"Cookie: {cookie_str}",
                    "Referer: https://pan.baidu.com/disk/home",
                ]

            save_dir = os.path.dirname(task.save_path)
            out_name = os.path.basename(task.save_path)
            os.makedirs(save_dir, exist_ok=True)

            # 检查磁盘空间
            import shutil
            disk_usage = shutil.disk_usage(save_dir)
            free_gb = disk_usage.free / (1024 ** 3)
            need_gb = task.total_size / (1024 ** 3) if task.total_size > 0 else 0
            if disk_usage.free < max(task.total_size * 1.1, 100 * 1024 * 1024):  # 至少100MB
                raise Exception(
                    f"磁盘空间不足！可用: {free_gb:.1f}GB, "
                    f"需要: {need_gb:.1f}GB, 路径: {save_dir}"
                )

            options = {
                "dir": save_dir,
                "out": out_name,
                "header": header_list,
            }
            options.update(self._get_task_connection_options())

            result = self._rpc_call("aria2.addUri", [[real_url], options])
            task.aria2_gid = result
            task.status = DownloadStatus.DOWNLOADING
            logger.debug(f" aria2 task submitted, gid={result}, file={task.filename}")
            logger.debug(f" url={real_url[:120]}")
            logger.debug(f" is_cdn={is_cdn}")

            with self._lock:
                self._gid_to_task[task.aria2_gid] = task.task_id
            self._emit("status_changed", task.task_id, DownloadStatus.DOWNLOADING)

        except Exception as e:
            task.status = DownloadStatus.ERROR
            task.error_msg = f"aria2 提交失败: {e}"
            self._emit("status_changed", task.task_id, DownloadStatus.ERROR)
            task._finish_event.set()

    def _build_cookie_header(self) -> str:
        parts = []
        for c in self.api.session.cookies:
            parts.append(f"{c.name}={c.value}")
        return '; '.join(parts)

    def remove_task(self, task_id: str):
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if task_id in self._task_order:
                self._task_order.remove(task_id)
            if task and task.aria2_gid:
                self._gid_to_task.pop(task.aria2_gid, None)

        if task and task.aria2_gid and self._aria2_ready:
            try:
                self._rpc_call("aria2.remove", [task.aria2_gid])
            except Exception:
                try:
                    self._rpc_call("aria2.removeDownloadResult", [task.aria2_gid])
                except Exception:
                    pass

        # 用户主动移除未完成任务时清理本地半成品；已完成任务只移除记录。
        if task:
            task._finish_event.set()
            aria2_ctrl = task.save_path + ".aria2"
            if task.status != DownloadStatus.COMPLETED and os.path.exists(task.save_path):
                try:
                    os.remove(task.save_path)
                except Exception:
                    pass
            if task.status != DownloadStatus.COMPLETED and os.path.exists(aria2_ctrl):
                try:
                    os.remove(aria2_ctrl)
                except Exception:
                    pass
            self._emit("status_changed", task_id, DownloadStatus.ERROR)

    def pause_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)

        if not task:
            return

        if task.aria2_gid and self._aria2_ready:
            try:
                self._rpc_call("aria2.pause", [task.aria2_gid])
            except Exception:
                pass

        task.status = DownloadStatus.PAUSED
        self._emit("status_changed", task_id, DownloadStatus.PAUSED)

    def resume_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)

        if not task:
            return

        if task.status == DownloadStatus.PAUSED and task.aria2_gid and self._aria2_ready:
            try:
                self._rpc_call("aria2.unpause", [task.aria2_gid])
                task.status = DownloadStatus.DOWNLOADING
                self._emit("status_changed", task_id, DownloadStatus.DOWNLOADING)
                return
            except Exception:
                pass

        if task.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            task.error_msg = ""
            task.speed = 0
            task.downloaded_size = self._file_size(task.save_path)
            task.connections = 0
            if task.aria2_gid:
                with self._lock:
                    self._gid_to_task.pop(task.aria2_gid, None)
            task.aria2_gid = ""
            task._finish_event.clear()
            task.status = DownloadStatus.WAITING
            self._submit_queue.put(task)
            self._emit("status_changed", task_id, DownloadStatus.WAITING)

    def get_tasks(self) -> list[DownloadTask]:
        with self._lock:
            return [self._tasks[tid] for tid in self._task_order if tid in self._tasks]

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self._tasks.get(task_id)

    # ─── 状态轮询 ──────────────────────────────────────────────

    def _poll_status(self):
        """定时轮询 aria2c 获取下载状态"""
        while self._running:
            time.sleep(0.8)
            if not self._aria2_ready:
                continue

            with self._lock:
                gids = dict(self._gid_to_task)

            for gid, task_id in gids.items():
                task = self._tasks.get(task_id)
                if not task or task.status in (DownloadStatus.COMPLETED, DownloadStatus.ERROR):
                    continue

                try:
                    status = self._rpc_call("aria2.tellStatus", [gid, [
                        "status", "totalLength", "completedLength",
                        "downloadSpeed", "errorCode", "errorMessage",
                        "connections",
                    ]])

                    total = int(status.get("totalLength", 0))
                    downloaded = int(status.get("completedLength", 0))
                    speed = int(status.get("downloadSpeed", 0)) / 1024  # KB/s
                    connections = int(status.get("connections", 0))
                    aria2_status = status.get("status", "")

                    task.total_size = total
                    task.downloaded_size = downloaded
                    task.speed = speed
                    task.connections = connections

                    if aria2_status == "complete":
                        # 验证下载文件大小是否正确（防止 CDN 返回错误页面被当作完成）
                        expected = getattr(task, '_expected_size', 0)
                        if expected > 0 and total > 0 and total < expected * 0.5:
                            retry_count = getattr(task, '_retry_count', 0)
                            pan_path = getattr(task, '_pan_path', '')
                            logger.debug(f" Size mismatch: got {total} vs expected {expected}, retrying...")
                            with self._lock:
                                self._gid_to_task.pop(gid, None)
                            if pan_path and retry_count < self.MAX_RETRIES:
                                task._retry_count = retry_count + 1
                                task.retry_count = task._retry_count
                                task.downloaded_size = 0
                                task.speed = 0
                                try:
                                    if os.path.exists(task.save_path):
                                        os.remove(task.save_path)
                                    aria2_ctrl = task.save_path + ".aria2"
                                    if os.path.exists(aria2_ctrl):
                                        os.remove(aria2_ctrl)
                                except Exception:
                                    pass
                                t = threading.Thread(
                                    target=self._retry_with_pcs, args=(task,), daemon=True
                                )
                                t.start()
                            else:
                                task.status = DownloadStatus.ERROR
                                task.error_msg = f"文件大小不匹配: {total} / {expected}"
                                task.speed = 0
                                self._emit("status_changed", task_id, DownloadStatus.ERROR)
                                task._finish_event.set()
                        else:
                            task.status = DownloadStatus.COMPLETED
                            task.speed = 0
                            self._emit("status_changed", task_id, DownloadStatus.COMPLETED)
                            self._emit("progress", task_id, downloaded, total)
                            task._finish_event.set()
                    elif aria2_status == "error":
                        error_msg = status.get("errorMessage", "下载错误")
                        error_code = status.get("errorCode", "")
                        logger.error(f" {task.filename}: [{error_code}] {error_msg}")
                        pan_path = getattr(task, '_pan_path', '')
                        retry_count = getattr(task, '_retry_count', 0)
                        # 所有错误都尝试重试（不只是403），直到用完重试次数
                        if pan_path and retry_count < self.MAX_RETRIES:
                            task._retry_count = retry_count + 1
                            task.retry_count = task._retry_count
                            logger.debug(f" aria2 error, retry {task._retry_count}/{self.MAX_RETRIES}...")
                            task.downloaded_size = self._file_size(task.save_path)
                            task.speed = 0
                            with self._lock:
                                self._gid_to_task.pop(gid, None)
                            t = threading.Thread(
                                target=self._retry_with_pcs, args=(task,), daemon=True
                            )
                            t.start()
                        elif pan_path and retry_count >= self.MAX_RETRIES:
                            # 重试次数用完，尝试 fallback
                            logger.debug(f" Retries exhausted, trying fallback session download...")
                            task.downloaded_size = self._file_size(task.save_path)
                            task.speed = 0
                            with self._lock:
                                self._gid_to_task.pop(gid, None)
                            task._retry_count = retry_count + 1  # 防止重复进入
                            task.retry_count = task._retry_count
                            t = threading.Thread(
                                target=self._fallback_download, args=(task,), daemon=True
                            )
                            t.start()
                        else:
                            task.status = DownloadStatus.ERROR
                            task.error_msg = f"[{error_code}] {error_msg}"
                            task.speed = 0
                            self._emit("status_changed", task_id, DownloadStatus.ERROR)
                            task._finish_event.set()
                    elif aria2_status == "paused":
                        if task.status != DownloadStatus.PAUSED:
                            task.status = DownloadStatus.PAUSED
                            task.speed = 0
                            self._emit("status_changed", task_id, DownloadStatus.PAUSED)
                    elif aria2_status == "active":
                        task.status = DownloadStatus.DOWNLOADING
                        self._emit("progress", task_id, downloaded, total)
                        self._emit("speed_update", task_id, speed)
                    elif aria2_status == "waiting":
                        task.status = DownloadStatus.WAITING

                except Exception:
                    pass

    # ─── PCS备用下载 (app_id=778750) ──────────────────────────

    def _retry_with_pcs(self, task: DownloadTask):
        """使用 locatedownload 或 PCS API (app_id=778750) 重新获取CDN URL"""
        from urllib.parse import quote
        try:
            # 延迟一下再重试，避免被CDN封禁
            retry_count = getattr(task, '_retry_count', 1)
            delay = min(retry_count * 2, 10)
            if delay > 0:
                logger.debug(f" Waiting {delay}s before retry {retry_count}...")
                time.sleep(delay)

            pan_path = getattr(task, '_pan_path', '')

            # 先尝试 locatedownload（高速）
            for app_id in ("250528", "778750"):
                locate_url = self.api.get_locate_download_url(pan_path, app_id)
                if locate_url:
                    logger.debug(f" locatedownload retry (app_id={app_id}) ok")
                    save_dir = os.path.dirname(task.save_path)
                    out_name = os.path.basename(task.save_path)
                    bduss = self.api._get_bduss()
                    header_list = [
                        f"User-Agent: {self.api.PCS_UA}",
                        f"Cookie: BDUSS={bduss};",
                    ]
                    options = {
                        "dir": save_dir,
                        "out": out_name,
                        "header": header_list,
                    }
                    options.update(self._get_task_connection_options())
                    result = self._rpc_call("aria2.addUri", [[locate_url], options])
                    task.aria2_gid = result
                    task.status = DownloadStatus.DOWNLOADING
                    logger.debug(f" locatedownload retry submitted, gid={result}")
                    with self._lock:
                        self._gid_to_task[task.aria2_gid] = task.task_id
                    self._emit("status_changed", task.task_id, DownloadStatus.DOWNLOADING)
                    return

            # 回退到 PCS download API
            encoded_path = quote(pan_path)
            pcs_url = (f"https://d.pcs.baidu.com/rest/2.0/pcs/file"
                       f"?method=download&path={encoded_path}&app_id=778750")

            resp = self.api.session.get(
                pcs_url,
                headers={"Referer": "https://pan.baidu.com/disk/home"},
                allow_redirects=False,
                stream=True,
                timeout=15,
            )
            cdn_url = ""
            if resp.status_code in (301, 302, 303, 307, 308):
                cdn_url = resp.headers.get("Location", "")
            resp.close()

            if not cdn_url:
                # 尝试 allow_redirects=True
                resp = self.api.session.get(
                    pcs_url,
                    headers={"Referer": "https://pan.baidu.com/disk/home"},
                    allow_redirects=True,
                    stream=True,
                    timeout=15,
                )
                if resp.status_code == 200 and "baidupcs.com" in resp.url:
                    cdn_url = resp.url
                resp.close()

            if not cdn_url:
                raise Exception("PCS API无法获取CDN链接")

            logger.debug(f" PCS 778750 CDN: {cdn_url[:120]}...")

            # 提交到aria2（CDN URL不需要cookie）
            save_dir = os.path.dirname(task.save_path)
            out_name = os.path.basename(task.save_path)
            header_list = [
                f"User-Agent: {self.api.UA}",
                "Referer: https://pan.baidu.com/disk/home",
            ]
            options = {
                "dir": save_dir,
                "out": out_name,
                "header": header_list,
            }
            options.update(self._get_task_connection_options())
            result = self._rpc_call("aria2.addUri", [[cdn_url], options])
            task.aria2_gid = result
            task.status = DownloadStatus.DOWNLOADING
            logger.debug(f" PCS retry submitted, gid={result}")
            with self._lock:
                self._gid_to_task[task.aria2_gid] = task.task_id
            self._emit("status_changed", task.task_id, DownloadStatus.DOWNLOADING)

        except Exception as e:
            logger.debug(f" PCS retry failed: {e}, trying fallback...")
            task.downloaded_size = self._file_size(task.save_path)
            t = threading.Thread(
                target=self._fallback_download, args=(task,), daemon=True
            )
            t.start()

    # ─── 回退下载（aria2不可用时） ────────────────────────────

    def _fallback_download(self, task: DownloadTask):
        """当 aria2c 不可用或失败时，使用 api.session 下载"""
        try:
            task.status = DownloadStatus.DOWNLOADING
            self._emit("status_changed", task.task_id, DownloadStatus.DOWNLOADING)

            os.makedirs(os.path.dirname(task.save_path), exist_ok=True)

            existing_size = self._file_size(task.save_path)
            headers = {"Referer": "https://pan.baidu.com/disk/home"}
            if existing_size > 0:
                headers["Range"] = f"bytes={existing_size}-"

            # 使用 api.session 下载（带完整cookie，自动跟随重定向）
            resp = self.api.session.get(
                task.dlink,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=60,
            )

            append_mode = False
            if resp.status_code == 206:
                append_mode = existing_size > 0
                task.downloaded_size = existing_size
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    total_part = content_range.rsplit("/", 1)[-1]
                    if total_part.isdigit():
                        task.total_size = int(total_part)
                if task.total_size == 0:
                    task.total_size = existing_size + int(resp.headers.get("Content-Length", 0))
            elif resp.status_code == 416 and existing_size > 0:
                expected = getattr(task, "_expected_size", task.total_size)
                if expected <= 0 or existing_size >= expected:
                    task.downloaded_size = existing_size
                    task.total_size = max(task.total_size, existing_size)
                    task.status = DownloadStatus.COMPLETED
                    task.speed = 0
                    self._emit("status_changed", task.task_id, DownloadStatus.COMPLETED)
                    task._finish_event.set()
                    resp.close()
                    return
            else:
                task.downloaded_size = 0
                if task.total_size == 0:
                    task.total_size = int(resp.headers.get("Content-Length", 0))

            logger.debug(f" Fallback download: status={resp.status_code}, "
                  f"CL={resp.headers.get('Content-Length','?')}, "
                  f"CT={resp.headers.get('Content-Type','?')}, "
                  f"url={resp.url[:100]}")

            if resp.status_code == 403:
                # 读取错误响应
                import gzip
                body = resp.content
                if body[:2] == b'\x1f\x8b':
                    try:
                        body = gzip.decompress(body)
                    except Exception:
                        pass
                err_text = body.decode('utf-8', errors='replace')[:300]
                logger.debug(f" 403 response body: {err_text}")
                # 检查是否是内容审核限制
                if "31326" in err_text or "hitcode" in err_text:
                    raise Exception(
                        "该文件被百度网盘内容审核限制，无法通过API下载。"
                        "请尝试使用百度网盘官方客户端下载。"
                    )
                raise Exception(f"下载被拒绝(403)")

            if resp.status_code not in (200, 206):
                raise Exception(f"下载失败, HTTP {resp.status_code}")

            chunk_size = 64 * 1024
            last_time = time.time()
            last_downloaded = task.downloaded_size

            mode = "ab" if append_mode else "wb"
            with open(task.save_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if task.status != DownloadStatus.DOWNLOADING:
                        return
                    if chunk:
                        f.write(chunk)
                        task.downloaded_size += len(chunk)

                        now = time.time()
                        dt = now - last_time
                        if dt >= 0.5:
                            task.speed = (task.downloaded_size - last_downloaded) / dt / 1024
                            last_time = now
                            last_downloaded = task.downloaded_size
                            self._emit("speed_update", task.task_id, task.speed)

                        self._emit("progress", task.task_id,
                                   task.downloaded_size, task.total_size)

            task.status = DownloadStatus.COMPLETED
            task.speed = 0
            self._emit("status_changed", task.task_id, DownloadStatus.COMPLETED)
            task._finish_event.set()

        except Exception as e:
            task.status = DownloadStatus.ERROR
            task.error_msg = str(e)
            task.speed = 0
            self._emit("status_changed", task.task_id, DownloadStatus.ERROR)
            task._finish_event.set()

    # ─── 设置 ──────────────────────────────────────────────────

    def update_settings(self, max_concurrent_tasks: int = None,
                        task_connections: int = None,
                        speed_limit: int = None):
        if max_concurrent_tasks is not None:
            self.max_concurrent_downloads = max(1, min(16, int(max_concurrent_tasks)))
        if task_connections is not None:
            self.task_connections = max(1, min(16, int(task_connections)))
        if speed_limit is not None:
            self.speed_limit = max(0, int(speed_limit or 0))

        if self._aria2_ready:
            try:
                opts = {}
                if max_concurrent_tasks is not None:
                    opts["max-concurrent-downloads"] = str(self.max_concurrent_downloads)
                if task_connections is not None:
                    opts["max-connection-per-server"] = str(self.task_connections)
                    opts["split"] = str(self.task_connections)
                if speed_limit is not None:
                    speed_val = f"{self.speed_limit}K" if self.speed_limit > 0 else "0"
                    opts["max-overall-download-limit"] = speed_val
                if opts:
                    self._rpc_call("aria2.changeGlobalOption", [opts])
            except Exception:
                pass

    def stop(self):
        """停止下载管理器和 aria2c 进程"""
        self.save_now()
        self._running = False
        if self._aria2_ready:
            try:
                self._rpc_call("aria2.shutdown")
            except Exception:
                pass
        if self._aria2_process:
            try:
                self._aria2_process.terminate()
                self._aria2_process.wait(timeout=5)
            except Exception:
                try:
                    self._aria2_process.kill()
                except Exception:
                    pass

    def is_aria2_available(self) -> bool:
        return self._aria2_ready
