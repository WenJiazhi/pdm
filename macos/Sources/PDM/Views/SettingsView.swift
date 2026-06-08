import AppKit
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppModel
    @State private var downloadDirectoryStatus = DownloadDirectoryStatus.check(path: "")

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 14) {
                    Text("下载")
                        .font(.headline)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("下载目录")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            TextField("下载目录", text: $app.config.downloadDir)
                                .textFieldStyle(.roundedBorder)
                                .frame(maxWidth: .infinity, alignment: .leading)

                            Button {
                                app.chooseDownloadDirectory()
                                refreshLocalStatus()
                            } label: {
                                Label("选择", systemImage: "folder")
                            }

                            Button {
                                openDownloadDirectory()
                            } label: {
                                Label("打开", systemImage: "arrow.up.forward.app")
                            }
                        }

                        Label(downloadDirectoryStatus.message, systemImage: downloadDirectoryStatus.systemImage)
                            .font(.caption)
                            .foregroundStyle(downloadDirectoryStatus.tint)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Divider()

                    SettingStepperRow(
                        title: "并发任务",
                        valueText: "\(app.config.maxConcurrentTasks)",
                        value: $app.config.maxConcurrentTasks,
                        range: 1...8
                    )

                    SettingStepperRow(
                        title: "单任务连接数",
                        valueText: "\(app.config.taskConnections)",
                        value: $app.config.taskConnections,
                        range: 1...16
                    )
                    .help("用于 Aria split / max-connection-per-server")
                }
                .padding(16)
                .background(.regularMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8))

                Button {
                    app.saveConfig()
                } label: {
                    Label("保存设置", systemImage: "checkmark.circle")
                }
                .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .onAppear(perform: refreshLocalStatus)
        .onChange(of: app.config.downloadDir) {
            refreshLocalStatus()
        }
    }

    private func refreshLocalStatus() {
        downloadDirectoryStatus = DownloadDirectoryStatus.check(path: app.config.downloadDir)
    }

    private func openDownloadDirectory() {
        let directory = URL(fileURLWithPath: app.config.downloadDir, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            NSWorkspace.shared.open(directory)
            refreshLocalStatus()
        } catch {
            app.statusMessage = "打开下载目录失败：\(error.localizedDescription)"
            refreshLocalStatus()
        }
    }

}

private struct SettingStepperRow: View {
    let title: String
    let valueText: String
    @Binding var value: Int
    let range: ClosedRange<Int>

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(title)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(valueText)
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 36, alignment: .trailing)

            Stepper(title, value: $value, in: range)
                .labelsHidden()
        }
    }
}

private struct DownloadDirectoryStatus {
    let message: String
    let systemImage: String
    let tint: Color

    static func check(path: String) -> DownloadDirectoryStatus {
        let trimmedPath = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty else {
            return DownloadDirectoryStatus(
                message: "下载目录未设置",
                systemImage: "exclamationmark.triangle.fill",
                tint: .red
            )
        }

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: trimmedPath, isDirectory: &isDirectory)
        if exists, isDirectory.boolValue {
            let writable = FileManager.default.isWritableFile(atPath: trimmedPath)
            return DownloadDirectoryStatus(
                message: writable ? "下载目录可用" : "下载目录存在，但可能不可写",
                systemImage: writable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                tint: writable ? .green : .orange
            )
        }

        return DownloadDirectoryStatus(
            message: "下载目录不存在，保存或打开时会尝试创建",
            systemImage: "folder.badge.plus",
            tint: .orange
        )
    }
}
