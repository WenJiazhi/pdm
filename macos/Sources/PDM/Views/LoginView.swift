import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var app: AppModel
    @State private var cookieText = ""
    @State private var showingWebLogin = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HeaderView(title: "登录", subtitle: app.username.isEmpty ? "选择已保存账号，或导入新的 Cookie。" : "已登录：\(app.username)")

                browserLoginCard
                savedAccountsCard
                cookieCard

                Spacer(minLength: 0)
            }
            .padding(24)
        }
        .onAppear {
            app.reloadAccounts()
            cookieText = ""
        }
        .sheet(isPresented: $showingWebLogin) {
            WebLoginView { cookie in
                await app.importCookieFromWebLogin(cookie)
            }
            .environmentObject(app)
        }
    }

    private var browserLoginCard: some View {
        GroupBox {
            HStack {
                Button {
                    showingWebLogin = true
                } label: {
                    Label("打开百度网盘登录", systemImage: "network")
                }
                .buttonStyle(.borderedProminent)

                Spacer()

                if app.hasImportedCookie {
                    Label("本机已有 Cookie", systemImage: "key.fill")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(4)
        } label: {
            Label("新账号登录", systemImage: "person.crop.circle.badge.plus")
        }
    }

    private var savedAccountsCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                if app.accounts.isEmpty {
                    ContentUnavailableView(
                        "没有已保存账号",
                        systemImage: "person.crop.circle.badge.questionmark",
                        description: Text("已导入 Windows 版 accounts.json 后会显示在这里。")
                    )
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                } else {
                    List(app.accounts, selection: $app.selectedAccountID) { account in
                        HStack(spacing: 12) {
                            Image(systemName: account.username == app.username ? "checkmark.seal.fill" : "person.crop.circle")
                                .foregroundStyle(account.username == app.username ? .green : .secondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(account.username)
                                    .font(.headline)
                                Text(account.username == app.username ? "已登录" : "已保存")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(account.vipType)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                        }
                        .tag(account.id)
                    }
                    .frame(minHeight: 120, maxHeight: 220)
                }

                HStack {
                    Button {
                        Task {
                            await app.loginSelectedAccount()
                            cookieText = ""
                        }
                    } label: {
                        Label("使用选中账号登录", systemImage: "person.crop.circle.badge.checkmark")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(app.accounts.isEmpty || app.selectedAccountID == nil)

                    Button {
                        app.reloadAccounts()
                    } label: {
                        Label("重新载入", systemImage: "arrow.clockwise")
                    }

                    Button(role: .destructive) {
                        app.deleteSelectedAccount()
                    } label: {
                        Label("删除选中", systemImage: "trash")
                    }
                    .disabled(app.accounts.isEmpty || app.selectedAccountID == nil)

                    Spacer()
                }
            }
            .padding(4)
        } label: {
            Label("已保存的账号", systemImage: "person.2")
        }
    }

    private var cookieCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                TextEditor(text: $cookieText)
                    .font(.system(.body, design: .monospaced))
                    .frame(minHeight: 150)
                    .overlay {
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(.separator)
                    }

                HStack {
                    Button {
                        app.updateCookie(cookieText)
                        Task {
                            await app.checkLogin()
                            cookieText = ""
                        }
                    } label: {
                        Label("导入并检测", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(cookieText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button {
                        Task {
                            await app.importConfigFile()
                            cookieText = ""
                        }
                    } label: {
                        Label("导入配置", systemImage: "square.and.arrow.down")
                    }

                    Button(role: .destructive) {
                        app.logout()
                        cookieText = ""
                    } label: {
                        Label("退出登录", systemImage: "rectangle.portrait.and.arrow.right")
                    }

                    Spacer()
                }
            }
            .padding(4)
        } label: {
            Label("手动 Cookie / 配置导入", systemImage: "key")
        }
    }
}
