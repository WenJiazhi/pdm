import SwiftUI

struct RemoteDirectoryPickerView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var app: AppModel

    let title: String
    let onSelect: (String) -> Void

    @State private var currentPath = "/"
    @State private var pathHistory = ["/"]
    @State private var targetPath = "/"
    @State private var directories: [PanFile] = []
    @State private var selection = Set<PanFile.ID>()
    @State private var isLoading = false
    @State private var errorMessage = ""

    var body: some View {
        VStack(spacing: 0) {
            HeaderView(title: title, subtitle: currentPath)
                .padding(.horizontal, 24)
                .padding(.top, 24)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    navigationButtons
                    targetPathField
                    actionButtons
                }

                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        navigationButtons
                        actionButtons
                    }
                    targetPathField
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)

            ZStack {
                FileListView(files: directories, selection: $selection) { file in
                    Task { await openDirectory(file) }
                }

                if isLoading {
                    ProgressView()
                        .controlSize(.large)
                        .padding()
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                } else if directories.isEmpty {
                    ContentUnavailableView(
                        "没有子文件夹",
                        systemImage: "folder",
                        description: Text("可以直接选择当前位置作为目标目录。")
                    )
                    .padding()
                }
            }

            if !errorMessage.isEmpty {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 24)
                    .padding(.top, 8)
            }

            HStack {
                Text("共 \(directories.count) 个文件夹")
                    .foregroundStyle(.secondary)
                Spacer()

                Button("取消") {
                    dismiss()
                }

                Button {
                    onSelect(normalizedPath(targetPath))
                    dismiss()
                } label: {
                    Label("转存到当前位置", systemImage: "checkmark.circle")
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(16)
        }
        .frame(minWidth: 680, minHeight: 500)
        .task {
            await loadDirectories()
        }
    }

    private var navigationButtons: some View {
        HStack(spacing: 8) {
            Button {
                Task { await goBack() }
            } label: {
                Label("返回", systemImage: "chevron.left")
            }
            .disabled(pathHistory.count <= 1 || isLoading)

            Button {
                Task { await goHome() }
            } label: {
                Label("根目录", systemImage: "house")
            }
            .disabled(isLoading)
        }
    }

    private var targetPathField: some View {
        TextField("目标路径", text: $targetPath)
            .textFieldStyle(.roundedBorder)
            .onSubmit {
                Task { await openTypedPath() }
            }
    }

    private var actionButtons: some View {
        HStack(spacing: 8) {
            Button {
                Task { await openTypedPath() }
            } label: {
                Label("打开", systemImage: "arrow.right.circle")
            }
            .disabled(isLoading)

            Button {
                Task { await loadDirectories() }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
            .disabled(isLoading)
        }
    }

    private func loadDirectories() async {
        isLoading = true
        errorMessage = ""
        defer { isLoading = false }
        do {
            directories = try await app.listRemoteDirectories(path: currentPath)
            selection = []
            targetPath = currentPath
        } catch {
            directories = []
            errorMessage = error.localizedDescription
        }
    }

    private func openDirectory(_ directory: PanFile) async {
        guard directory.isDirectory else { return }
        currentPath = normalizedPath(directory.path)
        pathHistory.append(currentPath)
        await loadDirectories()
    }

    private func goBack() async {
        guard pathHistory.count > 1 else { return }
        pathHistory.removeLast()
        currentPath = pathHistory.last ?? "/"
        await loadDirectories()
    }

    private func goHome() async {
        currentPath = "/"
        pathHistory = ["/"]
        await loadDirectories()
    }

    private func openTypedPath() async {
        currentPath = normalizedPath(targetPath)
        if pathHistory.last != currentPath {
            pathHistory.append(currentPath)
        }
        await loadDirectories()
    }

    private func normalizedPath(_ path: String) -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "/" }
        var normalized = trimmed.hasPrefix("/") ? trimmed : "/\(trimmed)"
        while normalized.count > 1 && normalized.hasSuffix("/") {
            normalized.removeLast()
        }
        return normalized
    }
}
