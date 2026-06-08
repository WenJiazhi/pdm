# PDM - Pan Download Manager

<p align="center">
  <strong>面向 macOS 与 Windows 的百度网盘下载管理器</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/macOS-SwiftUI-blue" alt="macOS SwiftUI">
  <img src="https://img.shields.io/badge/Windows-PyQt5-blue" alt="Windows PyQt5">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="License">
</p>

> **声明**：本项目为第三方学习项目，非百度官方客户端。请遵守百度网盘服务条款和当地法律法规，不要用于未授权内容的下载或分发。

## 项目定位

PDM 是一个双端开源下载工具：

- **macOS 端**：原生 SwiftUI 应用，提供更贴近 macOS 的窗口、导航、文件管理和下载体验。
- **Windows 端**：PyQt5 应用，保留完整桌面端能力，并与 macOS 端同步核心功能。
- **下载引擎**：随应用内置 aria2，不依赖 Motrix 或其他外部下载器。
- **配置目录**：统一使用 `~/.pdm/` 保存配置、账号、日志和下载任务状态。

## 功能

- Cookie 登录、账号保存与账号切换
- 浏览个人网盘目录、搜索文件、删除文件
- 解析百度网盘分享链接和提取码
- 选择目标目录后执行转存
- 转存并下载，下载结束后清理转存目录
- 内置 aria2 下载，支持多任务并发和多连接下载
- 下载任务保存，重启应用后保留任务记录
- 断点续传，未完成任务可继续下载
- 暂停、恢复、取消、移除和清理下载任务
- 下载缓存与临时目录清理，避免留下空目录或无效转存目录
- 下载目录、并发数、连接数等常用设置持久化

## 平台说明

### macOS

macOS 端位于 `macos/`，使用 SwiftUI 实现。它面向原生桌面体验，覆盖登录、文件列表、分享解析、转存、下载队列、任务保存、断点续传和临时目录清理等主流程。

常用本地运行方式：

```bash
./script/build_and_run.sh
```

常用打包方式：

```bash
./script/package_dmg.sh
```

macOS 发布产物建议放在本地 `release/macos/`，例如 DMG、校验信息和版本说明。

### Windows

Windows 端位于 `src/`，使用 PyQt5 实现。它与 macOS 端同步核心行为，包括内置 aria2 下载、任务保存、断点续传、转存临时目录清理和多账号管理。

运行环境：

- Python 3.10+
- PyQt5
- PyQtWebEngine

本地运行方式：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

打包方式：

```bash
python -m PyInstaller --noconfirm --clean build.spec
```

Windows 发布产物建议放在本地 `release/windows/`，例如压缩包、校验信息和版本说明。

仓库也提供 GitHub Actions workflow，可在 GitHub 的 Windows/macOS runner 上生成双端 release artifacts。

## 项目结构

```
.
├── main.py                  # Windows PyQt 应用入口
├── build.spec               # Windows PyInstaller 构建配置
├── requirements.txt         # Windows Python 依赖
├── macos/                   # macOS SwiftUI 原生应用
├── script/                  # macOS 构建、打包和辅助脚本
├── src/
│   ├── core/                # API、配置、日志、下载管理
│   └── ui/                  # Windows PyQt 界面
├── tools/                   # 随包工具，例如 Windows aria2c
└── licenses/                # 第三方组件许可证
```

## 工作原理

1. **认证**：通过 Cookie 认证百度网盘 Web API，并把账号信息保存在本地配置目录。
2. **文件管理**：通过 API 获取文件列表、执行搜索、删除和分享转存等操作。
3. **转存流程**：分享文件先转存到统一临时目录，获取下载链接后进入下载队列。
4. **下载流程**：aria2 负责实际下载，PDM 管理任务状态、进度、暂停恢复和失败重试。
5. **清理策略**：转存失败、下载完成、任务取消或任务删除时，清理对应临时目录和无效缓存。
6. **任务恢复**：下载任务保存到本地，应用重启后仍保留记录，未完成任务可继续下载。

## 第三方组件

PDM 随包分发 aria2。aria2 使用 GNU GPL 许可证（含 OpenSSL 例外），完整许可证见 `licenses/aria2/`。

各平台发布包应包含对应平台可执行的 aria2 二进制文件，并确保应用启动时不需要用户额外安装 Motrix、Homebrew aria2 或其他外部下载器。

## 发布目录建议

发布文件建议只作为本地构建产物保存，不直接提交到仓库：

```
release/
├── macos/
│   ├── PDM-macOS.dmg
│   ├── checksums.txt
│   └── RELEASE_NOTES.md
└── windows/
    ├── PDM-windows-x64.zip
    ├── checksums.txt
    └── RELEASE_NOTES.md
```

`release/` 当前作为构建产物目录被 `.gitignore` 忽略。若后续要通过 GitHub Release 分发安装包，建议把安装包上传到 Release 页面，而不是提交进源码仓库。

## 贡献

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/my-feature`
3. 提交更改
4. 推送到分支：`git push origin feature/my-feature`
5. 创建 Pull Request

请尽量保持两端行为一致：macOS 端的功能修复应同步检查 Windows 端，Windows 端的功能修复也应同步检查 macOS 端。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源许可。

Apache-2.0 允许使用、修改、分发、私有使用和商业使用，但需要遵守许可证条款。

第三方组件按各自许可证分发，详见 `licenses/` 目录。

## 社区

[LINUX DO](https://linux.do/) — 中文开发者社区

本项目认可并感谢 LINUX DO 社区在中文开发者开源交流、项目分享和技术讨论中的价值。除非社区另有明确说明，此处仅为社区致谢和链接，不代表官方背书。
