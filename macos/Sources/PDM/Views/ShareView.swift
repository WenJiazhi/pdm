import SwiftUI

struct ShareView: View {
    @EnvironmentObject private var app: AppModel
    @State private var showingTransferPicker = false

    var body: some View {
        VStack(spacing: 0) {
            HeaderView(title: "分享转存", subtitle: currentPathText)
                .padding(.horizontal, 24)
                .padding(.top, 24)

            VStack(spacing: 10) {
                TextField("https://pan.baidu.com/s/1...", text: $app.shareLink)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        Task { await app.parseShare() }
                    }
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) {
                        passwordField
                        shareActionButtons
                        Spacer()
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        passwordField
                        shareActionButtons
                    }
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)

            FileListView(files: app.shareFiles, selection: $app.shareSelection) { file in
                Task { await app.openShareFile(file) }
            }

            HStack {
                Text("共 \(app.shareFiles.count) 个项目")
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    showingTransferPicker = true
                } label: {
                    Label("仅转存", systemImage: "tray.and.arrow.down")
                }
                .disabled(app.shareSelection.isEmpty)
                Button {
                    Task { await app.transferAndDownloadSelectedShareFiles() }
                } label: {
                    Label("转存并下载", systemImage: "arrow.down.circle")
                }
                .buttonStyle(.borderedProminent)
                .disabled(app.shareSelection.isEmpty)
            }
            .padding(16)
        }
        .sheet(isPresented: $showingTransferPicker) {
            RemoteDirectoryPickerView(title: "选择转存目录") { path in
                Task {
                    await app.transferSelectedShareFiles(to: path)
                }
            }
            .environmentObject(app)
        }
    }

    private var currentPathText: String {
        app.shareDirectoryStack.last ?? "粘贴百度网盘分享链接开始解析。"
    }

    private var passwordField: some View {
        TextField("提取码", text: $app.sharePassword)
            .textFieldStyle(.roundedBorder)
            .frame(maxWidth: 220)
    }

    private var shareActionButtons: some View {
        HStack(spacing: 8) {
            Button {
                Task { await app.parseShare() }
            } label: {
                Label("解析", systemImage: "link")
            }
            .buttonStyle(.borderedProminent)

            Button {
                Task { await app.shareBack() }
            } label: {
                Label("返回", systemImage: "chevron.left")
            }
            .disabled(app.shareDirectoryStack.isEmpty)
        }
    }
}
