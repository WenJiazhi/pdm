import AppKit
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $app.selectedSection) { section in
                Label(section.rawValue, systemImage: icon(for: section))
                    .tag(section)
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200)
        } detail: {
            VStack(spacing: 0) {
                Group {
                    switch app.selectedSection {
                    case .login:
                        LoginView()
                    case .files:
                        FilesView()
                    case .share:
                        ShareView()
                    case .downloads:
                        DownloadsView()
                    case .settings:
                        SettingsView()
                    }
                }
                StatusBarView()
            }
        }
        .task {
            await app.autoLoginIfPossible()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
            app.saveDownloadsNow()
        }
    }

    private func icon(for section: AppSection) -> String {
        switch section {
        case .login: "person.crop.circle"
        case .files: "folder"
        case .share: "link"
        case .downloads: "arrow.down.circle"
        case .settings: "gearshape"
        }
    }
}

private struct StatusBarView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        HStack {
            if app.isBusy {
                ProgressView()
                    .controlSize(.small)
            }
            Text(app.statusMessage)
                .lineLimit(1)
                .foregroundStyle(.secondary)
            Spacer()
            if let quota = app.quota, quota.total > 0 {
                Text("\(DisplayFormat.size(quota.used)) / \(DisplayFormat.size(quota.total))")
                    .foregroundStyle(.secondary)
            }
        }
        .font(.caption)
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(.bar)
    }
}
