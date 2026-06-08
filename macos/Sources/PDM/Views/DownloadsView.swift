import AppKit
import SwiftUI

struct DownloadsView: View {
    @EnvironmentObject private var app: AppModel
    @State private var selection = Set<DownloadTaskModel.ID>()

    var body: some View {
        let summary = DownloadSummary(tasks: app.downloads)

        VStack(alignment: .leading, spacing: 0) {
            HeaderView(title: "下载", subtitle: app.config.downloadDir)
                .padding(.horizontal, 24)
                .padding(.top, 24)

            VStack(alignment: .leading, spacing: 16) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 12) {
                        downloadSummaryLabel(summary)
                        Spacer()
                        downloadToolbar(summary)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        downloadSummaryLabel(summary)
                        downloadToolbar(summary)
                    }
                }

                if app.downloads.isEmpty {
                    ContentUnavailableView(
                        "暂无下载任务",
                        systemImage: "tray",
                        description: Text("从我的文件或分享转存添加下载后会显示在这里。")
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(selection: $selection) {
                        ForEach(app.downloads) { task in
                            DownloadTaskRow(
                                task: task,
                                pauseAction: { app.pauseDownload(id: task.id) },
                                resumeAction: { app.resumeDownload(id: task.id) },
                                retryAction: { app.retryDownload(id: task.id) },
                                openAction: { revealInFinder(task) },
                                removeAction: { removeDownload(task) }
                            )
                            .tag(task.id)
                            .contextMenu {
                                Button {
                                    revealInFinder(task)
                                } label: {
                                    Label("在 Finder 中显示", systemImage: "magnifyingglass")
                                }

                                if task.status == .downloading {
                                    Button {
                                        app.pauseDownload(id: task.id)
                                    } label: {
                                        Label("暂停", systemImage: "pause.circle")
                                    }
                                }

                                if task.status == .paused {
                                    Button {
                                        app.resumeDownload(id: task.id)
                                    } label: {
                                        Label("恢复", systemImage: "play.circle")
                                    }
                                }

                                if task.status == .failed || task.status == .canceled {
                                    Button {
                                        app.retryDownload(id: task.id)
                                    } label: {
                                        Label("重试", systemImage: "arrow.clockwise")
                                    }
                                }

                                Divider()

                                Button(role: .destructive) {
                                    removeDownload(task)
                                } label: {
                                    Label("移除任务", systemImage: "trash")
                                }
                            }
                        }
                    }
                    .listStyle(.inset)
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 16)
            .padding(.bottom, 24)
        }
    }

    private func openDownloadDirectory() {
        let directory = URL(fileURLWithPath: app.config.downloadDir, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            NSWorkspace.shared.open(directory)
        } catch {
            app.statusMessage = "打开下载目录失败：\(error.localizedDescription)"
        }
    }

    private func revealInFinder(_ task: DownloadTaskModel) {
        if FileManager.default.fileExists(atPath: task.destination.path) {
            NSWorkspace.shared.activateFileViewerSelecting([task.destination])
        } else {
            NSWorkspace.shared.open(task.destination.deletingLastPathComponent())
        }
    }

    private func clearCompletedDownloads() {
        app.clearFinishedDownloads()
        trimSelection()
    }

    private func removeSelectedDownloads() {
        let selectedIDs = selection
        app.removeDownloads(ids: selectedIDs)
        selection.removeAll()
    }

    private func removeDownload(_ task: DownloadTaskModel) {
        app.removeDownload(id: task.id)
        selection.remove(task.id)
    }

    private func trimSelection() {
        let remainingIDs = Set(app.downloads.map(\.id))
        selection.formIntersection(remainingIDs)
    }

    private func downloadSummaryLabel(_ summary: DownloadSummary) -> some View {
        Label(summary.text, systemImage: "arrow.down.circle")
            .font(.callout)
            .foregroundStyle(.secondary)
            .lineLimit(2)
    }

    private func downloadToolbar(_ summary: DownloadSummary) -> some View {
        HStack(spacing: 8) {
            Button {
                app.pauseAllDownloads()
            } label: {
                Label("全部暂停", systemImage: "pause.circle")
            }
            .disabled(!summary.hasRunningTasks)

            Button {
                app.resumeAllDownloads()
            } label: {
                Label("全部恢复", systemImage: "play.circle")
            }
            .disabled(!summary.hasPausedTasks)

            Button {
                openDownloadDirectory()
            } label: {
                Label("打开目录", systemImage: "folder")
            }

            Button {
                clearCompletedDownloads()
            } label: {
                Label("清除已完成", systemImage: "checkmark.circle")
            }
            .disabled(!summary.hasClearableTasks)

            Button(role: .destructive) {
                removeSelectedDownloads()
            } label: {
                Label("移除所选", systemImage: "trash")
            }
            .disabled(selection.isEmpty)
        }
        .labelStyle(.titleAndIcon)
    }
}

private struct DownloadTaskRow: View {
    @ObservedObject var task: DownloadTaskModel
    let pauseAction: () -> Void
    let resumeAction: () -> Void
    let retryAction: () -> Void
    let openAction: () -> Void
    let removeAction: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: task.status.symbolName)
                .font(.title3)
                .foregroundStyle(task.status.tintColor)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Text(task.filename)
                        .fontWeight(.medium)
                        .lineLimit(1)

                    Spacer(minLength: 12)

                    Text(task.status.rawValue)
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundStyle(task.status.tintColor)
                }

                ProgressView(value: task.progress)
                    .progressViewStyle(.linear)

                HStack(spacing: 12) {
                    Text(progressText)
                        .monospacedDigit()

                    if task.totalBytes > 0 {
                        Text(percentText)
                            .monospacedDigit()
                    }

                    Spacer(minLength: 12)

                    Text(task.destination.path)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                if !speedAndETA.isEmpty {
                    Text(speedAndETA)
                        .font(.caption)
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                }

                if !task.errorMessage.isEmpty {
                    Text(task.errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
            }

            HStack(spacing: 6) {
                if task.status == .downloading {
                    Button(action: pauseAction) {
                        Image(systemName: "pause.circle")
                    }
                    .help("暂停")
                }
                if task.status == .paused {
                    Button(action: resumeAction) {
                        Image(systemName: "play.circle")
                    }
                    .help("恢复")
                }
                if task.status == .failed || task.status == .canceled {
                    Button(action: retryAction) {
                        Image(systemName: "arrow.clockwise")
                    }
                    .help("重试")
                }
            }
            .buttonStyle(.borderless)
            .fixedSize()

            Menu {
                Button {
                    openAction()
                } label: {
                    Label("在 Finder 中显示", systemImage: "magnifyingglass")
                }

                Divider()

                Button(role: .destructive) {
                    removeAction()
                } label: {
                    Label("移除任务", systemImage: "trash")
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .imageScale(.large)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .padding(.vertical, 8)
    }

    private var progressText: String {
        if task.totalBytes > 0 {
            "\(DisplayFormat.size(task.receivedBytes)) / \(DisplayFormat.size(task.totalBytes))"
        } else {
            "\(DisplayFormat.size(task.receivedBytes)) / 未知大小"
        }
    }

    private var percentText: String {
        "\(Int((task.progress * 100).rounded()))%"
    }

    private var speedAndETA: String {
        let speed = DisplayFormat.speed(task.speedBytesPerSecond)
        let remaining = max(0, task.totalBytes - task.receivedBytes)
        let eta = DisplayFormat.eta(remainingBytes: remaining, bytesPerSecond: task.speedBytesPerSecond)
        if speed.isEmpty { return "" }
        return eta.isEmpty ? speed : "\(speed)  剩余 \(eta)"
    }
}

@MainActor
private struct DownloadSummary {
    let total: Int
    let downloading: Int
    let paused: Int
    let finished: Int
    let failed: Int
    let canceled: Int

    init(tasks: [DownloadTaskModel]) {
        total = tasks.count
        downloading = tasks.filter { $0.status == .downloading }.count
        paused = tasks.filter { $0.status == .paused }.count
        finished = tasks.filter { $0.status == .finished }.count
        failed = tasks.filter { $0.status == .failed }.count
        canceled = tasks.filter { $0.status == .canceled }.count
    }

    var hasClearableTasks: Bool {
        finished > 0 || failed > 0 || canceled > 0
    }

    var hasRunningTasks: Bool {
        downloading > 0
    }

    var hasPausedTasks: Bool {
        paused > 0
    }

    var text: String {
        guard total > 0 else { return "暂无下载任务" }

        var parts = [
            "共 \(total) 个任务",
            "下载中 \(downloading)",
            "已完成 \(finished)"
        ]

        if paused > 0 {
            parts.append("暂停 \(paused)")
        }
        if failed > 0 {
            parts.append("失败 \(failed)")
        }
        if canceled > 0 {
            parts.append("取消 \(canceled)")
        }

        return parts.joined(separator: "  |  ")
    }
}

private extension DownloadStatus {
    var tintColor: Color {
        switch self {
        case .queued:
            .secondary
        case .paused:
            .orange
        case .downloading:
            .blue
        case .finished:
            .green
        case .failed, .canceled:
            .red
        }
    }

    var symbolName: String {
        switch self {
        case .queued:
            "clock"
        case .paused:
            "pause.circle.fill"
        case .downloading:
            "arrow.down.circle.fill"
        case .finished:
            "checkmark.circle.fill"
        case .failed:
            "exclamationmark.triangle.fill"
        case .canceled:
            "xmark.circle.fill"
        }
    }
}
