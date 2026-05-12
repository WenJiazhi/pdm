# PDM - Pan Download Manager

<p align="center">
  <strong>基于 PyQt5 的百度网盘下载工具</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

> **声明**：本项目为第三方学习项目，非百度官方客户端。请遵守百度网盘服务条款和当地法律法规，不要用于未授权内容的下载或分发。

## 功能

- 内置浏览器登录，自动提取 Cookie
- 多账号管理（保存和切换登录账号）
- 浏览个人网盘目录、搜索文件、删除文件
- 解析百度网盘分享链接和提取码
- 「转存并下载」流程（下载完成后自动清理转存文件）
- 使用 aria2c 作为下载引擎，支持多任务并发和多连接
- 支持下载限速、暂停、恢复和任务管理
- 记住下载目录和登录配置

## 快速开始

### 环境要求

- Python 3.10+（Windows）
- PyQt5 + QtWebEngine

### 安装

```bash
git clone https://github.com/WenJiazhi/pdm.git
cd pdm
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

配置和 Cookie 保存在 `~/.pdm/` 目录。首次启动会自动兼容读取旧的 `~/.bduss_downloader/` 配置。

## 项目结构

```
.
├── main.py                  # 应用入口
├── build.spec               # PyInstaller 构建配置
├── requirements.txt         # Python 依赖
├── src/
│   ├── core/                # API、配置、日志、下载管理
│   │   ├── api.py           # 百度网盘 API 封装（Cookie 认证）
│   │   ├── aria2_downloader.py  # aria2c RPC 下载管理器
│   │   ├── config.py        # 配置持久化
│   │   └── logger.py        # 日志模块（自动轮转）
│   └── ui/                  # PyQt5 界面
│       ├── main_window.py   # 主窗口（左侧导航布局）
│       ├── browser_login.py # 内置浏览器登录对话框
│       ├── tab_login.py     # 登录与账号管理
│       ├── tab_files.py     # 文件浏览器
│       ├── tab_share.py     # 分享链接解析与转存
│       ├── tab_downloads.py # 下载队列与进度
│       ├── tab_settings.py  # 设置面板
│       ├── styles.py        # 全局 QSS 样式
│       └── utils.py         # 工具方法
├── tools/
│   └── aria2c.exe           # 随包分发的 aria2c
└── licenses/
    └── aria2/               # aria2 许可证文件（GPL + OpenSSL 例外）
```

## 打包

```bash
python -m PyInstaller --noconfirm --clean build.spec
```

产物输出到 `dist/PDM/`，`aria2c.exe` 会自动包含在内。

## 工作原理

1. **认证**：通过浏览器提取的 BDUSS/BDUSS_BFESS Cookie 认证百度网盘内部 Web API
2. **下载链接解析**：依次尝试 `locatedownload`（高速客户端 API）、Session 重定向、PCS API 备用方案
3. **aria2c 集成**：管理 aria2c RPC 子进程，支持多连接下载、自动重试和单线程回退
4. **分享转存**：分享文件先转存到临时目录，通过 dlink 下载后自动删除临时目录

## 第三方组件

本项目随包分发 `aria2c.exe`（aria2 1.37.0，Windows 64 位）。aria2 使用 GNU GPL 许可证（含 OpenSSL 例外）。完整许可证见 `licenses/aria2/`。

## 贡献

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/my-feature`)
3. 提交更改
4. 推送到分支 (`git push origin feature/my-feature`)
5. 创建 Pull Request

请遵循现有的 `src/core` 和 `src/ui` 目录划分。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可。

Apache-2.0 允许使用、修改、分发、私有使用和商业使用，但需要遵守许可证条款。

第三方组件按各自许可证分发（详见 `licenses/` 目录）。

## 社区

[LINUX DO](https://linux.do/) — 中文开发者社区

本项目认可并感谢 LINUX DO 社区在中文开发者开源交流、项目分享和技术讨论中的价值。除非社区另有明确说明，此处仅为社区致谢和链接，不代表官方背书。
