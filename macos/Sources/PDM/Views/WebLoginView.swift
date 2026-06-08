import SwiftUI
import WebKit

struct WebLoginView: View {
    @Environment(\.dismiss) private var dismiss
    let onCookieReady: (String) async -> Bool

    @State private var latestCookie = ""
    @State private var statusText = "请在内置窗口中完成百度网盘登录"
    @State private var isImporting = false
    @State private var hasSubmittedCookie = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Label("百度网盘登录", systemImage: "network")
                    .font(.headline)
                Text(statusText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
                Button("关闭") {
                    dismiss()
                }
            }
            .padding(14)

            Divider()

            BaiduWebLoginWebView(
                cookieString: $latestCookie,
                statusText: $statusText
            )
            .frame(minHeight: 420)

            Divider()

            HStack {
                Label(
                    canImportCookie ? "已检测到登录 Cookie" : "登录完成后会自动导入 Cookie",
                    systemImage: canImportCookie ? "checkmark.seal.fill" : "key"
                )
                .foregroundStyle(canImportCookie ? .green : .secondary)

                Spacer()

                if isImporting {
                    ProgressView()
                        .controlSize(.small)
                }

                Button {
                    Task {
                        await importLatestCookie(autoClose: true)
                    }
                } label: {
                    Label("使用当前登录", systemImage: "checkmark.circle")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canImportCookie || isImporting)
            }
            .padding(14)
        }
        .frame(minWidth: 720, minHeight: 560)
        .onChange(of: latestCookie) { _, cookie in
            guard !hasSubmittedCookie, containsLoginCookie(cookie) else { return }
            hasSubmittedCookie = true
            Task {
                await importLatestCookie(autoClose: true)
            }
        }
    }

    private var canImportCookie: Bool {
        containsLoginCookie(latestCookie)
    }

    private func importLatestCookie(autoClose: Bool) async {
        guard canImportCookie, !isImporting else { return }
        isImporting = true
        statusText = "正在导入并验证登录状态..."
        let succeeded = await onCookieReady(latestCookie)
        isImporting = false
        if succeeded, autoClose {
            dismiss()
        } else if !succeeded {
            hasSubmittedCookie = false
            statusText = "Cookie 已读取，但登录验证失败，请确认页面已登录"
        }
    }

    private func containsLoginCookie(_ cookie: String) -> Bool {
        cookie
            .split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .contains { part in
                part.hasPrefix("BDUSS=") || part.hasPrefix("BDUSS_BFESS=")
            }
    }
}

private struct BaiduWebLoginWebView: NSViewRepresentable {
    @Binding var cookieString: String
    @Binding var statusText: String

    func makeCoordinator() -> Coordinator {
        Coordinator(
            onCookieString: { cookieString = $0 },
            onStatusText: { statusText = $0 }
        )
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.customUserAgent = BaiduPanAPI.userAgent
        webView.allowsBackForwardNavigationGestures = true
        webView.configuration.websiteDataStore.httpCookieStore.add(context.coordinator)

        if let url = URL(string: "https://pan.baidu.com/disk/home") {
            webView.load(URLRequest(url: url))
        }
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onCookieString = { cookieString = $0 }
        context.coordinator.onStatusText = { statusText = $0 }
    }

    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.websiteDataStore.httpCookieStore.remove(coordinator)
        webView.navigationDelegate = nil
        webView.uiDelegate = nil
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKHTTPCookieStoreObserver {
        var onCookieString: (String) -> Void
        var onStatusText: (String) -> Void

        init(onCookieString: @escaping (String) -> Void, onStatusText: @escaping (String) -> Void) {
            self.onCookieString = onCookieString
            self.onStatusText = onStatusText
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            publishStatus("正在打开百度网盘登录页...")
        }

        func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
            collectCookies(from: webView.configuration.websiteDataStore.httpCookieStore)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            publishStatus("页面已加载，等待登录 Cookie")
            collectCookies(from: webView.configuration.websiteDataStore.httpCookieStore)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            publishStatus("页面加载失败：\(error.localizedDescription)")
            collectCookies(from: webView.configuration.websiteDataStore.httpCookieStore)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            publishStatus("页面加载失败：\(error.localizedDescription)")
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        func cookiesDidChange(in cookieStore: WKHTTPCookieStore) {
            collectCookies(from: cookieStore)
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if navigationAction.targetFrame == nil {
                webView.load(navigationAction.request)
            }
            return nil
        }

        private func collectCookies(from cookieStore: WKHTTPCookieStore) {
            cookieStore.getAllCookies { [weak self] cookies in
                let cookieHeader = Self.cookieHeader(from: cookies)
                guard !cookieHeader.isEmpty else { return }
                DispatchQueue.main.async {
                    self?.onCookieString(cookieHeader)
                    if Self.containsLoginCookie(cookieHeader) {
                        self?.onStatusText("已捕获百度网盘登录 Cookie")
                    }
                }
            }
        }

        private func publishStatus(_ text: String) {
            DispatchQueue.main.async { [weak self] in
                self?.onStatusText(text)
            }
        }

        private static func cookieHeader(from cookies: [HTTPCookie]) -> String {
            var selected = [String: HTTPCookie]()
            for cookie in cookies where isBaiduCookie(cookie) {
                if let existing = selected[cookie.name] {
                    if cookieScore(cookie) > cookieScore(existing) {
                        selected[cookie.name] = cookie
                    }
                } else {
                    selected[cookie.name] = cookie
                }
            }

            return selected.values
                .sorted { lhs, rhs in
                    let lhsRank = importantCookieRank(lhs.name)
                    let rhsRank = importantCookieRank(rhs.name)
                    if lhsRank != rhsRank {
                        return lhsRank < rhsRank
                    }
                    return lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
                }
                .map { "\($0.name)=\($0.value)" }
                .joined(separator: "; ")
        }

        private static func containsLoginCookie(_ cookie: String) -> Bool {
            cookie
                .split(separator: ";")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .contains { part in
                    part.hasPrefix("BDUSS=") || part.hasPrefix("BDUSS_BFESS=")
                }
        }

        private static func isBaiduCookie(_ cookie: HTTPCookie) -> Bool {
            var domain = cookie.domain.lowercased()
            while domain.hasPrefix(".") {
                domain.removeFirst()
            }
            return domain == "baidu.com" || domain.hasSuffix(".baidu.com")
        }

        private static func cookieScore(_ cookie: HTTPCookie) -> Int {
            let domain = cookie.domain.lowercased()
            let domainScore: Int
            if domain == "pan.baidu.com" {
                domainScore = 5
            } else if domain == ".pan.baidu.com" {
                domainScore = 4
            } else if domain == ".baidu.com" {
                domainScore = 3
            } else if domain == "baidu.com" {
                domainScore = 2
            } else {
                domainScore = 1
            }
            return domainScore * 1_000 + cookie.path.count
        }

        private static func importantCookieRank(_ name: String) -> Int {
            let names = ["BDUSS", "BDUSS_BFESS", "STOKEN", "BAIDUID", "BDCLND", "PANWEB", "csrfToken"]
            return names.firstIndex(of: name) ?? 1_000
        }
    }
}
