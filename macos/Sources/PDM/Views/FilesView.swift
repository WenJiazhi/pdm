import SwiftUI

struct FilesView: View {
    @EnvironmentObject private var app: AppModel
    @State private var confirmingDelete = false

    var body: some View {
        VStack(spacing: 0) {
            HeaderView(title: "我的文件", subtitle: app.currentPath)
                .padding(.horizontal, 24)
                .padding(.top, 24)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    navigationButtons
                    searchField
                    searchButtons
                }

                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        navigationButtons
                        searchButtons
                    }
                    searchField
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)

            FileListView(files: app.files, selection: $app.fileSelection) { file in
                Task { await app.openFile(file) }
            }

            HStack {
                Text("共 \(app.files.count) 个项目")
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    Task { await app.downloadSelectedFiles() }
                } label: {
                    Label("下载选中", systemImage: "arrow.down.circle")
                }
                .buttonStyle(.borderedProminent)
                .disabled(app.fileSelection.isEmpty)

                Button(role: .destructive) {
                    confirmingDelete = true
                } label: {
                    Label("删除选中", systemImage: "trash")
                }
                .disabled(app.fileSelection.isEmpty)
            }
            .padding(16)
        }
        .confirmationDialog(
            "确认删除选中的 \(app.fileSelection.count) 个项目？",
            isPresented: $confirmingDelete,
            titleVisibility: .visible
        ) {
            Button("删除", role: .destructive) {
                Task { await app.deleteSelectedFiles() }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("这些文件或文件夹会从百度网盘删除。")
        }
        .task {
            if app.files.isEmpty {
                await app.loadFiles()
            }
        }
    }

    private var navigationButtons: some View {
        HStack(spacing: 8) {
            Button {
                Task { await app.goBack() }
            } label: {
                Label("返回", systemImage: "chevron.left")
            }
            .disabled(app.pathHistory.count <= 1)

            Button {
                Task { await app.goHome() }
            } label: {
                Label("根目录", systemImage: "house")
            }
        }
    }

    private var searchField: some View {
        TextField("搜索文件", text: $app.searchText)
            .textFieldStyle(.roundedBorder)
            .onSubmit {
                Task { await app.searchFiles() }
            }
    }

    private var searchButtons: some View {
        HStack(spacing: 8) {
            Button {
                Task { await app.searchFiles() }
            } label: {
                Label("搜索", systemImage: "magnifyingglass")
            }

            Button {
                Task { await app.loadFiles() }
            } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }
        }
    }
}
