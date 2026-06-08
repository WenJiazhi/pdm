import AppKit
import Foundation
import UniformTypeIdentifiers

enum AppSection: String, CaseIterable, Identifiable {
    case login = "登录"
    case files = "我的文件"
    case share = "分享转存"
    case downloads = "下载"
    case settings = "设置"

    var id: String { rawValue }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var config: AppConfig {
        didSet {
            api.update(config: config)
        }
    }
    @Published var selectedSection: AppSection = .login
    @Published var username = ""
    @Published var quota: QuotaInfo?
    @Published var statusMessage = "未登录"
    @Published var isBusy = false

    @Published var currentPath = "/"
    @Published var pathHistory = ["/"]
    @Published var files: [PanFile] = []
    @Published var fileSelection = Set<PanFile.ID>()
    @Published var searchText = ""

    @Published var shareLink = ""
    @Published var sharePassword = ""
    @Published var shareFiles: [PanFile] = []
    @Published var shareSelection = Set<PanFile.ID>()
    @Published var currentShare: ShareListResult?
    @Published var shareDirectoryStack: [String] = []

    @Published var downloads: [DownloadTaskModel] = []
    @Published var accounts: [SavedAccount] = []
    @Published var selectedAccountID: SavedAccount.ID?

    private let api: BaiduPanAPI
    private var pendingLoginCookie = ""
    private let transferDownloadDirectory = "/PDM_Transfer_Temp"
    private var activeTransferCleanup: TransferCleanupState?
    private var transferCleanupWatcher: Task<Void, Never>?
    private var downloadSaveTask: Task<Void, Never>?

    init() {
        let loaded = ConfigStore.load()
        config = loaded
        api = BaiduPanAPI(config: loaded)
        accounts = AccountStore.load()
        restoreDownloads()
        selectAccountForCurrentSession()
        if !loaded.effectiveCookie.isEmpty {
            statusMessage = "已导入本机保存的 Cookie"
        }
    }

    var hasImportedCookie: Bool {
        !config.effectiveCookie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func autoLoginIfPossible() async {
        guard hasImportedCookie, username.isEmpty else { return }
        await checkLogin()
    }

    func saveConfig() {
        do {
            try ConfigStore.save(config)
            statusMessage = "设置已保存"
        } catch {
            statusMessage = "保存失败：\(error.localizedDescription)"
        }
    }

    func updateCookie(_ cookie: String) {
        applyCookie(cookie)
        saveConfig()
    }

    func importCookieFromWebLogin(_ cookie: String) async -> Bool {
        updateCookie(cookie)
        return await checkLogin()
    }

    private func applyCookie(_ cookie: String) {
        let normalized = cookie.trimmingCharacters(in: .whitespacesAndNewlines)
        config.fullCookie = normalized
        let parts = parseCookie(normalized)
        config.bduss = parts["BDUSS"] ?? config.bduss
        config.bdussBfess = parts["BDUSS_BFESS"] ?? config.bdussBfess
        pendingLoginCookie = normalized
    }

    func importConfigFile() async {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json]
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        guard panel.runModal() == .OK, let url = panel.url else { return }

        config = ConfigStore.load(from: url)
        pendingLoginCookie = config.effectiveCookie
        saveConfig()
        await checkLogin()
    }

    @discardableResult
    func checkLogin() async -> Bool {
        isBusy = true
        defer { isBusy = false }
        do {
            let user = try await api.getUserInfo()
            username = user.username
            selectedAccountID = user.username
            statusMessage = "已登录：\(user.username)"
            let vipType = await api.getVIPType()
            quota = try? await api.getQuota()
            saveAccount(username: user.username, vipType: vipType)
            if !hasActiveTransferDownloads {
                await cleanupStaleTransferDirectoryOnLaunch()
            }
            return true
        } catch {
            AppLog.error("operation failed error=\(error.localizedDescription)")
            statusMessage = error.localizedDescription
            return false
        }
    }

    func reloadAccounts() {
        accounts = AccountStore.load()
        selectAccountForCurrentSession()
    }

    func loginSelectedAccount() async {
        guard let account = selectedAccount else {
            statusMessage = "请先选择一个账号"
            return
        }
        guard !account.cookie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            statusMessage = "该账号没有保存 Cookie，请重新登录"
            return
        }

        promoteAccountToTop(account.id)
        applyCookie(account.cookie)
        saveConfig()
        await checkLogin()
    }

    func deleteSelectedAccount() {
        guard let account = selectedAccount else {
            statusMessage = "请先选择要删除的账号"
            return
        }
        accounts.removeAll { $0.username == account.username }
        do {
            try AccountStore.save(accounts)
            selectAccountForCurrentSession()
            if username == account.username {
                logout()
            } else {
                statusMessage = "已删除账号：\(account.username)"
            }
        } catch {
            statusMessage = "删除账号失败：\(error.localizedDescription)"
        }
    }

    func logout() {
        username = ""
        quota = nil
        files = []
        fileSelection = []
        config.bduss = ""
        config.bdussBfess = ""
        config.fullCookie = ""
        pendingLoginCookie = ""
        saveConfig()
        statusMessage = "已退出登录"
        selectedSection = .login
    }

    func refreshCurrentSection() async {
        switch selectedSection {
        case .login:
            await checkLogin()
        case .files:
            try? await refreshFiles()
        case .share:
            if !shareLink.isEmpty {
                await parseShare()
            }
        case .downloads, .settings:
            break
        }
    }

    func refreshFiles() async throws {
        let loaded = try await api.listFiles(path: currentPath)
        files = loaded
        fileSelection = []
        statusMessage = "共 \(loaded.count) 个项目"
    }

    func loadFiles() async {
        await runBusy {
            try await refreshFiles()
        }
    }

    func openFile(_ file: PanFile) async {
        guard file.isDirectory else { return }
        currentPath = file.path
        pathHistory.append(currentPath)
        await loadFiles()
    }

    func goBack() async {
        guard pathHistory.count > 1 else { return }
        pathHistory.removeLast()
        currentPath = pathHistory.last ?? "/"
        await loadFiles()
    }

    func goHome() async {
        currentPath = "/"
        pathHistory = ["/"]
        await loadFiles()
    }

    func searchFiles() async {
        let keyword = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !keyword.isEmpty else {
            await loadFiles()
            return
        }
        await runBusy {
            files = try await api.searchFiles(keyword: keyword, directory: currentPath)
            fileSelection = []
            statusMessage = "搜索到 \(files.count) 个项目"
        }
    }

    func downloadSelectedFiles() async {
        let selected = files.filter { fileSelection.contains($0.id) && !$0.isDirectory }
        guard !selected.isEmpty else {
            statusMessage = "请先选择要下载的文件"
            return
        }
        await addDownloads(for: selected)
    }

    func deleteSelectedFiles() async {
        let selected = files.filter { fileSelection.contains($0.id) }
        guard !selected.isEmpty else {
            statusMessage = "请先选择要删除的文件"
            return
        }
        await runBusy {
            try await api.deleteFiles(paths: selected.map(\.path))
            statusMessage = "已删除 \(selected.count) 个项目"
            try await refreshFiles()
        }
    }

    func parseShare() async {
        await runBusy {
            let autoPassword = extractSharePassword(from: shareLink)
            if sharePassword.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !autoPassword.isEmpty {
                sharePassword = autoPassword
            }
            let result = try await api.listShareFiles(shareURL: shareLink, password: sharePassword)
            currentShare = result
            shareFiles = result.files
            shareSelection = []
            shareDirectoryStack = []
            statusMessage = "解析到 \(result.files.count) 个分享项目"
        }
    }

    func openShareFile(_ file: PanFile) async {
        guard file.isDirectory, let share = currentShare else { return }
        await runBusy {
            let loaded = try await api.listShareDirectory(
                shareID: share.shareID,
                uk: share.uk,
                directory: file.path
            )
            shareDirectoryStack.append(file.path)
            shareFiles = loaded
            shareSelection = []
            statusMessage = "共 \(loaded.count) 个分享项目"
        }
    }

    func shareBack() async {
        guard let share = currentShare, !shareDirectoryStack.isEmpty else { return }
        shareDirectoryStack.removeLast()
        let directory = shareDirectoryStack.last ?? "/"
        await runBusy {
            shareFiles = try await api.listShareDirectory(
                shareID: share.shareID,
                uk: share.uk,
                directory: directory
            )
            shareSelection = []
        }
    }

    func transferSelectedShareFiles(to targetPath: String) async {
        guard let share = currentShare else { return }
        let selected = shareFiles.filter { shareSelection.contains($0.id) }
        guard !selected.isEmpty else {
            statusMessage = "请先选择分享文件"
            return
        }
        let path = normalizedRemotePath(targetPath)
        await runBusy {
            try await createRemoteDirectoryTree(path)
            try await api.transferShareFiles(
                surl: share.surl,
                shareID: share.shareID,
                uk: share.uk,
                fsIDs: selected.map(\.fsID),
                toPath: path,
                randsk: share.randsk
            )
            await refreshFilesIfShowingDirectory(path)
            await refreshFilesIfShowingParent(of: [path])
            statusMessage = "已转存到 \(path)"
        }
    }

    func listRemoteDirectories(path: String) async throws -> [PanFile] {
        try await api.listFiles(path: normalizedRemotePath(path))
            .filter(\.isDirectory)
    }

    func transferAndDownloadSelectedShareFiles() async {
        guard let share = currentShare else { return }
        let selected = shareFiles.filter { shareSelection.contains($0.id) && !$0.isDirectory }
        guard !selected.isEmpty else {
            statusMessage = "请先选择要下载的分享文件"
            return
        }
        await cleanupTransferDirectoryIfReady(reason: "已清理上一轮转存目录")
        guard !hasActiveTransferDownloads else {
            statusMessage = "已有转存下载任务正在进行，请等待完成或先移除任务"
            return
        }

        await runBusy {
            let folder = transferDownloadDirectory
            do {
                try await transferShareFilesToTemporaryDirectory(
                    share: share,
                    selectedFiles: selected,
                    folder: folder
                )

                try await Task.sleep(for: .seconds(1))
                let transferred = try await api.listFiles(path: folder)
                let filesByName = Dictionary(uniqueKeysWithValues: transferred.map { ($0.serverFilename, $0) })
                let tasks = await addDownloads(for: selected.compactMap { filesByName[$0.serverFilename] })
                if tasks.isEmpty {
                    try? await api.deleteFiles(paths: [folder], onNest: "ignore")
                    await refreshFilesIfShowingParent(of: [folder])
                    statusMessage = "转存成功，但没有创建下载任务，已清理临时目录"
                } else {
                    scheduleTransferCleanup(folder: folder, tasks: tasks)
                    statusMessage = "已转存并添加 \(tasks.count) 个下载任务，完成后会自动删除 \(folder)"
                }
            } catch {
                try? await api.deleteFiles(paths: [folder], onNest: "ignore")
                await refreshFilesIfShowingParent(of: [folder])
                throw error
            }
        }
    }

    private func transferShareFilesToTemporaryDirectory(
        share: ShareListResult,
        selectedFiles: [PanFile],
        folder: String
    ) async throws {
        let fsIDs = selectedFiles.map(\.fsID)
        var lastError: Error?
        let maxAttempts = 3

        for attempt in 1...maxAttempts {
            do {
                AppLog.info("transfer_temp_prepare attempt=\(attempt) folder=\(folder)")
                try await resetTransferDirectory(folder)
                try await api.transferShareFiles(
                    surl: share.surl,
                    shareID: share.shareID,
                    uk: share.uk,
                    fsIDs: fsIDs,
                    toPath: folder,
                    randsk: share.randsk
                )
                if attempt > 1 {
                    AppLog.info("transfer_temp_retry_success attempt=\(attempt) folder=\(folder)")
                }
                return
            } catch {
                lastError = error
                guard isTransientTransferError(error), attempt < maxAttempts else {
                    throw error
                }

                let delaySeconds = Double(attempt * 2)
                AppLog.warning("transfer_temp_retry errno=2 attempt=\(attempt) next_delay=\(delaySeconds)s folder=\(folder)")
                try? await api.deleteFiles(paths: [folder], onNest: "ignore")
                await refreshFilesIfShowingParent(of: [folder])
                try await Task.sleep(for: .seconds(delaySeconds))
            }
        }

        if let lastError {
            throw lastError
        }
    }

    func clearFinishedDownloads() {
        let oldCount = downloads.count
        downloads.removeAll { task in
            task.isTerminal
        }
        let removedCount = oldCount - downloads.count
        statusMessage = removedCount > 0 ? "已清除 \(removedCount) 个已结束任务" : "没有可清除的任务"
        saveDownloadsNow()
        Task { await cleanupTransferDirectoryIfReady(reason: "下载队列已清理，已删除转存目录") }
    }

    func removeDownloads(ids: Set<DownloadTaskModel.ID>) {
        let targets = downloads.filter { ids.contains($0.id) }
        for task in targets {
            task.cancel()
            task.removeLocalCache()
        }
        downloads.removeAll { ids.contains($0.id) }
        statusMessage = targets.isEmpty ? "请先选择下载任务" : "已移除 \(targets.count) 个下载任务"
        saveDownloadsNow()
        Task { await cleanupTransferDirectoryIfReady(reason: "下载任务已移除，已删除转存目录") }
    }

    func removeDownload(id: DownloadTaskModel.ID) {
        removeDownloads(ids: [id])
    }

    func pauseDownload(id: DownloadTaskModel.ID) {
        guard let task = downloads.first(where: { $0.id == id }) else { return }
        task.pause()
        startQueuedDownloads()
        saveDownloadsNow()
    }

    func resumeDownload(id: DownloadTaskModel.ID) {
        guard let task = downloads.first(where: { $0.id == id }) else { return }
        task.queueForResume()
        startQueuedDownloads()
        saveDownloadsNow()
    }

    func retryDownload(id: DownloadTaskModel.ID) {
        guard let task = downloads.first(where: { $0.id == id }) else { return }
        task.retry()
        startQueuedDownloads()
        saveDownloadsNow()
    }

    func pauseAllDownloads() {
        for task in downloads where task.status == .downloading {
            task.pause()
        }
        statusMessage = "已暂停所有下载任务"
        saveDownloadsNow()
    }

    func resumeAllDownloads() {
        for task in downloads where task.status == .paused {
            task.queueForResume()
        }
        startQueuedDownloads()
        statusMessage = "已恢复下载队列"
        saveDownloadsNow()
    }

    func saveDownloadsNow() {
        downloadSaveTask?.cancel()
        downloadSaveTask = nil
        do {
            try DownloadTaskStore.save(downloads.map { $0.persistentRecord() })
        } catch {
            AppLog.error("download_records_save_failed error=\(error.localizedDescription)")
        }
    }

    func chooseDownloadDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: config.downloadDir)
        if panel.runModal() == .OK, let url = panel.url {
            config.downloadDir = url.path
            saveConfig()
        }
    }

    @discardableResult
    private func addDownloads(for panFiles: [PanFile]) async -> [DownloadTaskModel] {
        var createdTasks: [DownloadTaskModel] = []
        for file in panFiles where !file.isDirectory {
            do {
                let dlink = try await api.getDownloadLink(fsID: file.fsID)
                let resolved = await api.resolveDownloadURL(
                    dlink: dlink,
                    panPath: file.path,
                    fsID: file.fsID
                )
                let destination = URL(fileURLWithPath: config.downloadDir)
                    .appendingPathComponent(file.serverFilename)
                    .uniqueFileURL()

                let task = DownloadTaskModel(
                    filename: file.serverFilename,
                    destination: destination,
                    dlink: resolved.url,
                    headers: resolved.headers,
                    totalBytes: file.size,
                    maxConcurrentDownloads: config.maxConcurrentTasks,
                    connectionCount: config.taskConnections
                )
                configureDownloadTask(task)
                downloads.insert(task, at: 0)
                createdTasks.append(task)
                saveDownloadsDebounced()
                startQueuedDownloads()
            } catch {
                let message = error.localizedDescription
                AppLog.error("add_download failed filename=\(file.serverFilename) error=\(message)")
                statusMessage = "获取下载链接失败：\(file.serverFilename)：\(message)"
            }
        }
        selectedSection = .downloads
        return createdTasks
    }

    private func configureDownloadTask(_ task: DownloadTaskModel) {
        task.onStatusChange = { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                self.startQueuedDownloads()
                await self.cleanupTransferDirectoryIfReady(reason: "下载已停止，已自动删除转存目录")
            }
        }
        task.onPersistentChange = { [weak self] in
            Task { @MainActor in
                self?.saveDownloadsDebounced()
            }
        }
    }

    private func restoreDownloads() {
        downloads = DownloadTaskStore.load().map { DownloadTaskModel(record: $0) }
        for task in downloads {
            configureDownloadTask(task)
        }
        cleanupUntrackedDownloadCaches()
    }

    private func saveDownloadsDebounced() {
        downloadSaveTask?.cancel()
        downloadSaveTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(500))
            self?.saveDownloadsNow()
        }
    }

    private func startQueuedDownloads() {
        let limit = max(1, min(config.maxConcurrentTasks, 8))
        let activeCount = downloads.filter { $0.status == .downloading }.count
        var slots = max(0, limit - activeCount)
        guard slots > 0 else { return }
        for task in downloads.reversed() where task.status == .queued {
            task.start()
            slots -= 1
            if slots <= 0 {
                break
            }
        }
    }

    private func scheduleTransferCleanup(folder: String, tasks: [DownloadTaskModel]) {
        guard !tasks.isEmpty else { return }
        let taskIDs = Set(tasks.map(\.id))
        activeTransferCleanup = TransferCleanupState(folder: folder, taskIDs: taskIDs)
        transferCleanupWatcher?.cancel()
        transferCleanupWatcher = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))
                guard let self, self.activeTransferCleanup != nil else { return }
                await self.cleanupTransferDirectoryIfReady(reason: "下载已停止，已自动删除转存目录")
                if self.activeTransferCleanup == nil {
                    return
                }
            }
        }
    }

    private var hasActiveTransferDownloads: Bool {
        guard let cleanup = activeTransferCleanup else { return false }
        return downloads.contains { task in
            cleanup.taskIDs.contains(task.id) && task.needsTransferDirectory
        }
    }

    private func resetTransferDirectory(_ folder: String) async throws {
        do {
            try await api.deleteFiles(paths: [folder], onNest: "ignore")
        } catch {
            AppLog.info("reset_transfer_directory ignored delete path=\(folder) error=\(error.localizedDescription)")
        }
        await refreshFilesIfShowingParent(of: [folder])
        try await Task.sleep(for: .seconds(1))
        try await createRemoteDirectoryTree(folder)
        try await Task.sleep(for: .milliseconds(700))
        await refreshFilesIfShowingParent(of: [folder])
    }

    private func cleanupTransferDirectoryIfReady(reason: String) async {
        guard let cleanup = activeTransferCleanup else { return }
        let tracked = downloads.filter { cleanup.taskIDs.contains($0.id) }
        let allTrackedInactive = tracked.allSatisfy { task -> Bool in
            !task.needsTransferDirectory
        }
        let shouldCleanup = tracked.isEmpty || allTrackedInactive
        guard shouldCleanup else { return }

        activeTransferCleanup = nil
        transferCleanupWatcher = nil
        do {
            try await api.deleteFiles(paths: [cleanup.folder], onNest: "ignore")
            await refreshFilesIfShowingParent(of: [cleanup.folder])
            statusMessage = reason
        } catch {
            AppLog.error("cleanup_transfer_folder failed path=\(cleanup.folder) error=\(error.localizedDescription)")
            statusMessage = "转存目录清理失败：\(cleanup.folder)"
        }
    }

    private func cleanupStaleTransferDirectoryOnLaunch() async {
        cleanupUntrackedDownloadCaches()
        do {
            try await api.deleteFiles(paths: [transferDownloadDirectory], onNest: "ignore")
            await refreshFilesIfShowingParent(of: [transferDownloadDirectory])
            AppLog.info("cleanup_stale_transfer_directory path=\(transferDownloadDirectory)")
        } catch {
            AppLog.info("cleanup_stale_transfer_directory ignored path=\(transferDownloadDirectory) error=\(error.localizedDescription)")
        }
    }

    private func cleanupUntrackedDownloadCaches() {
        let resumableTaskIDs = Set(downloads.filter(\.shouldKeepResumeCache).map(\.id))
        DownloadTaskModel.cleanupStaleCacheDirectories(keeping: resumableTaskIDs)
    }

    private func runBusy(_ operation: () async throws -> Void) async {
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation()
        } catch {
            AppLog.error("operation failed error=\(error.localizedDescription)")
            statusMessage = error.localizedDescription
        }
    }

    private func createRemoteDirectoryTree(_ path: String) async throws {
        var current = ""
        for part in path.split(separator: "/") {
            current += "/\(part)"
            do {
                try await api.createDirectory(path: current)
            } catch {
                AppLog.error("create_remote_directory ignored path=\(current) error=\(error.localizedDescription)")
            }
        }
    }

    private func refreshFilesIfShowingParent(of paths: [String]) async {
        guard selectedSection == .files else { return }
        let normalizedCurrentPath = normalizedRemotePath(currentPath)
        let shouldRefresh = paths.contains { path in
            parentRemotePath(of: path) == normalizedCurrentPath
        }
        guard shouldRefresh else { return }
        try? await refreshFiles()
    }

    private func refreshFilesIfShowingDirectory(_ path: String) async {
        guard selectedSection == .files else { return }
        guard normalizedRemotePath(currentPath) == normalizedRemotePath(path) else { return }
        try? await refreshFiles()
    }

    private var selectedAccount: SavedAccount? {
        guard let selectedAccountID else { return nil }
        return accounts.first { $0.id == selectedAccountID }
    }

    private func selectAccountForCurrentSession() {
        if !username.isEmpty, accounts.contains(where: { $0.id == username }) {
            selectedAccountID = username
            promoteAccountToTop(username)
            return
        }

        let activeCookie = config.effectiveCookie.trimmingCharacters(in: .whitespacesAndNewlines)
        if !activeCookie.isEmpty {
            if let matchedAccount = accounts.first(where: { cookiesMatch($0.cookie, activeCookie) }) {
                selectedAccountID = matchedAccount.id
                promoteAccountToTop(matchedAccount.id)
            } else if let selectedAccountID, accounts.contains(where: { $0.id == selectedAccountID }) {
                return
            } else {
                selectedAccountID = nil
            }
            return
        }

        if let selectedAccountID, accounts.contains(where: { $0.id == selectedAccountID }) {
            return
        }
        selectedAccountID = accounts.first?.id
    }

    private func saveAccount(username: String, vipType: String) {
        let cookie = pendingLoginCookie.isEmpty ? config.effectiveCookie : pendingLoginCookie
        guard !cookie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        accounts.removeAll { $0.username == username }
        accounts.insert(SavedAccount(username: username, vipType: vipType, cookie: cookie), at: 0)
        do {
            try AccountStore.save(accounts)
            selectedAccountID = username
            pendingLoginCookie = ""
        } catch {
            statusMessage = "账号保存失败：\(error.localizedDescription)"
        }
    }

    private func promoteAccountToTop(_ id: SavedAccount.ID) {
        guard let index = accounts.firstIndex(where: { $0.id == id }), index > 0 else { return }
        let account = accounts.remove(at: index)
        accounts.insert(account, at: 0)
        do {
            try AccountStore.save(accounts)
        } catch {
            AppLog.error("promote_account_failed id=\(id) error=\(error.localizedDescription)")
        }
    }

    private func extractSharePassword(from text: String) -> String {
        let patterns = [
            #"[?&]pwd=([A-Za-z0-9]{4})"#,
            #"提取码\s*[:：]\s*([A-Za-z0-9]{4})"#,
            #"(?:https?://\S+)\s+([A-Za-z0-9]{4})$"#
        ]
        for pattern in patterns {
            if let match = text.firstMatch(pattern: pattern) {
                return match
            }
        }
        return ""
    }

    private func parseCookie(_ cookie: String) -> [String: String] {
        cookie
            .split(separator: ";")
            .reduce(into: [String: String]()) { result, part in
                let pieces = part.split(separator: "=", maxSplits: 1).map {
                    String($0).trimmingCharacters(in: .whitespacesAndNewlines)
                }
                if pieces.count == 2 {
                    result[pieces[0]] = pieces[1]
                }
            }
    }

    private func cookiesMatch(_ lhs: String, _ rhs: String) -> Bool {
        let lhsParts = parseCookie(lhs)
        let rhsParts = parseCookie(rhs)

        let lhsBDUSS = lhsParts["BDUSS"] ?? ""
        let rhsBDUSS = rhsParts["BDUSS"] ?? ""
        if !lhsBDUSS.isEmpty || !rhsBDUSS.isEmpty {
            return !lhsBDUSS.isEmpty && lhsBDUSS == rhsBDUSS
        }

        let lhsBDUSSBfess = lhsParts["BDUSS_BFESS"] ?? ""
        let rhsBDUSSBfess = rhsParts["BDUSS_BFESS"] ?? ""
        if !lhsBDUSSBfess.isEmpty || !rhsBDUSSBfess.isEmpty {
            return !lhsBDUSSBfess.isEmpty && lhsBDUSSBfess == rhsBDUSSBfess
        }

        let normalizedLHS = normalizedCookie(lhs)
        let normalizedRHS = normalizedCookie(rhs)
        return !normalizedLHS.isEmpty && normalizedLHS == normalizedRHS
    }

    private func normalizedCookie(_ cookie: String) -> String {
        parseCookie(cookie)
            .map { key, value in "\(key)=\(value)" }
            .sorted()
            .joined(separator: ";")
    }

    private func parentRemotePath(of path: String) -> String {
        let normalized = normalizedRemotePath(path)
        guard normalized != "/" else { return "/" }
        let parts = normalized.split(separator: "/").dropLast()
        return parts.isEmpty ? "/" : "/" + parts.joined(separator: "/")
    }

    private func normalizedRemotePath(_ path: String) -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "/" }
        var normalized = trimmed.hasPrefix("/") ? trimmed : "/\(trimmed)"
        while normalized.count > 1 && normalized.hasSuffix("/") {
            normalized.removeLast()
        }
        return normalized
    }

    private func isTransientTransferError(_ error: Error) -> Bool {
        if case BaiduPanError.api(2, _) = error {
            return true
        }
        return error.localizedDescription.contains("errno=2")
            || error.localizedDescription.contains("API 错误：2")
    }
}

private struct TransferCleanupState {
    let folder: String
    let taskIDs: Set<DownloadTaskModel.ID>
}

private extension String {
    func firstMatch(pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return nil
        }
        let range = NSRange(startIndex..<endIndex, in: self)
        guard let match = regex.firstMatch(in: self, range: range),
              match.numberOfRanges > 1,
              let capture = Range(match.range(at: 1), in: self) else {
            return nil
        }
        return String(self[capture])
    }
}
