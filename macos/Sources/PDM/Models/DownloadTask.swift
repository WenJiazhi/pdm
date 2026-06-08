import Foundation

enum DownloadStatus: String, Codable {
    case queued = "排队中"
    case downloading = "下载中"
    case paused = "已暂停"
    case finished = "已完成"
    case failed = "失败"
    case canceled = "已取消"
}

@MainActor
final class DownloadTaskModel: ObservableObject, Identifiable {
    let id: UUID
    let filename: String
    let destination: URL
    let dlink: String
    let headers: [String]

    @Published var status: DownloadStatus = .queued
    @Published var progress: Double = 0
    @Published var receivedBytes: Int64 = 0
    @Published var totalBytes: Int64 = 0
    @Published var speedBytesPerSecond: Double = 0
    @Published var errorMessage = ""

    var onStatusChange: (() -> Void)?
    var onPersistentChange: (() -> Void)?

    private let expectedBytesHint: Int64
    private let cacheDirectory: URL
    private let maxConcurrentDownloads: Int
    private let connectionCount: Int
    private var downloadOperation: Task<Void, Never>?
    private var activeRunID: UUID?
    private var isPausing = false
    private var isCancelling = false
    private var lastProgressDate: Date?
    private var lastProgressBytes: Int64 = 0
    private var lastPersistedProgressDate = Date.distantPast
    private var lastPersistedProgressBytes: Int64 = 0

    init(
        id: UUID = UUID(),
        filename: String,
        destination: URL,
        dlink: String,
        headers: [String],
        totalBytes: Int64 = 0,
        maxConcurrentDownloads: Int = 2,
        connectionCount: Int = 1
    ) {
        self.id = id
        self.filename = filename
        self.destination = destination
        self.dlink = dlink
        self.headers = headers
        self.totalBytes = totalBytes
        self.expectedBytesHint = totalBytes
        self.maxConcurrentDownloads = min(max(maxConcurrentDownloads, 1), 8)
        self.connectionCount = min(max(connectionCount, 1), 16)
        self.cacheDirectory = Self.cacheRoot
            .appendingPathComponent(id.uuidString, isDirectory: true)
    }

    convenience init(record: DownloadTaskRecord) {
        self.init(
            id: record.id,
            filename: record.filename,
            destination: URL(fileURLWithPath: record.destinationPath),
            dlink: record.dlink,
            headers: record.headers,
            totalBytes: record.totalBytes > 0 ? record.totalBytes : record.expectedBytes,
            maxConcurrentDownloads: record.maxConcurrentDownloads,
            connectionCount: record.connectionCount
        )
        let restoredStatus: DownloadStatus
        switch record.status {
        case .downloading, .queued:
            restoredStatus = .paused
        default:
            restoredStatus = record.status
        }
        status = restoredStatus
        receivedBytes = record.receivedBytes
        totalBytes = max(record.totalBytes, record.expectedBytes)
        progress = record.progress
        errorMessage = record.errorMessage
        if restoredStatus == .paused, progress <= 0, totalBytes > 0 {
            let cachedBytes = resumableBytesOnDisk()
            if cachedBytes > 0 {
                receivedBytes = max(receivedBytes, cachedBytes)
                progress = min(1, Double(receivedBytes) / Double(totalBytes))
            }
        }
        lastProgressBytes = receivedBytes
        lastPersistedProgressBytes = receivedBytes
    }

    var isTerminal: Bool {
        status == .finished || status == .failed || status == .canceled
    }

    var needsTransferDirectory: Bool {
        status == .queued || status == .downloading
    }

    var shouldKeepResumeCache: Bool {
        status == .queued || status == .downloading || status == .paused || status == .failed
    }

    func start() {
        guard downloadOperation == nil else { return }
        guard URL(string: dlink) != nil else {
            fail(message: "下载链接无效")
            return
        }

        do {
            try prepareCacheDirectory()
        } catch {
            fail(message: "创建缓存目录失败：\(error.localizedDescription)")
            return
        }

        let runID = UUID()
        let plan = DownloadPlan(
            sourceURLString: dlink,
            headers: headers,
            destination: destination,
            cacheDirectory: cacheDirectory,
            expectedBytesHint: expectedBytesHint,
            maxConcurrentDownloads: maxConcurrentDownloads,
            connectionCount: self.connectionCount,
            filename: filename
        )

        activeRunID = runID
        isPausing = false
        isCancelling = false
        errorMessage = ""
        lastProgressDate = Date()
        lastProgressBytes = receivedBytes
        speedBytesPerSecond = 0
        status = .downloading
        notifyStatusChange()

        AppLog.info("download_start filename=\(filename) connections=\(connectionCount) destination=\(destination.path)")
        downloadOperation = Task { [weak self] in
            do {
                let result = try await Self.downloadToCache(plan: plan) { progress in
                    await MainActor.run {
                        self?.apply(progress: progress)
                    }
                }
                try Task.checkCancellation()
                await MainActor.run {
                    self?.complete(runID: runID, result: result)
                }
            } catch {
                await MainActor.run {
                    self?.handleDownloadFailure(runID: runID, error: error)
                }
            }
        }
    }

    func pause() {
        guard status == .downloading, downloadOperation != nil else { return }
        isPausing = true
        activeRunID = nil
        downloadOperation?.cancel()
        downloadOperation = nil
        speedBytesPerSecond = 0
        status = .paused
        notifyStatusChange()
    }

    func resume() {
        guard status == .paused || status == .queued else { return }
        start()
    }

    func queueForResume() {
        guard status == .paused else { return }
        status = .queued
        notifyStatusChange()
    }

    func retry() {
        cancelActiveTaskForRetry()
        let cachedBytes = resumableBytesOnDisk()
        receivedBytes = cachedBytes
        speedBytesPerSecond = 0
        totalBytes = expectedBytesHint
        progress = totalBytes > 0 ? min(1, Double(receivedBytes) / Double(totalBytes)) : 0
        errorMessage = ""
        status = .queued
        notifyStatusChange()
    }

    func cancel() {
        isCancelling = true
        activeRunID = nil
        downloadOperation?.cancel()
        downloadOperation = nil
        speedBytesPerSecond = 0
        cleanupCacheDirectory()
        status = .canceled
        notifyStatusChange()
    }

    private func apply(progress update: DownloadProgressUpdate) {
        guard status == .downloading else { return }
        if let reportedSpeed = update.speedBytesPerSecond {
            speedBytesPerSecond = reportedSpeed
            lastProgressDate = Date()
            lastProgressBytes = update.receivedBytes
        } else {
            updateSpeed(totalBytesWritten: update.receivedBytes)
        }
        receivedBytes = update.receivedBytes
        if update.totalBytes > 0 {
            totalBytes = update.totalBytes
        }
        if totalBytes > 0 {
            progress = min(1, Double(receivedBytes) / Double(totalBytes))
        }
        notifyProgressChangeIfNeeded(force: progress >= 1)
    }

    private func complete(runID: UUID, result: DownloadResult) {
        guard activeRunID == runID else { return }
        downloadOperation = nil
        activeRunID = nil

        if let validationError = validationFailureMessage(
            actualBytes: result.actualBytes,
            expectedBytes: result.expectedBytes,
            response: result.response
        ) {
            failAfterDownload(message: validationError, cachedFile: result.cachedFile)
            return
        }

        do {
            try installCachedFile(result.cachedFile)
            receivedBytes = result.actualBytes
            totalBytes = max(totalBytes, result.expectedBytes, result.actualBytes)
            progress = 1
            speedBytesPerSecond = 0
            status = .finished
            errorMessage = ""
            AppLog.info("download_finished filename=\(filename) bytes=\(result.actualBytes) destination=\(destination.path)")
        } catch {
            status = .failed
            errorMessage = "保存文件失败：\(error.localizedDescription)"
            AppLog.error("download_install_failed filename=\(filename) cache=\(result.cachedFile.path) destination=\(destination.path) error=\(error.localizedDescription)")
        }

        speedBytesPerSecond = 0
        cleanupCacheDirectory()
        notifyStatusChange()
    }

    private func handleDownloadFailure(runID: UUID, error: Error) {
        guard activeRunID == runID else { return }
        downloadOperation = nil
        activeRunID = nil

        if isPausing {
            isPausing = false
            speedBytesPerSecond = 0
            status = .paused
            notifyStatusChange()
            return
        }

        if isCancelling || Self.isCancellation(error) {
            isCancelling = false
            speedBytesPerSecond = 0
            cleanupCacheDirectory()
            status = .canceled
            notifyStatusChange()
            return
        }

        status = .failed
        errorMessage = error.localizedDescription
        speedBytesPerSecond = 0
        AppLog.error("download_failed filename=\(filename) error=\(error.localizedDescription)")
        notifyStatusChange()
    }

    private func fail(message: String) {
        status = .failed
        errorMessage = message
        speedBytesPerSecond = 0
        cleanupCacheDirectory()
        notifyStatusChange()
    }

    func removeLocalCache() {
        cleanupCacheDirectory()
    }

    func persistentRecord() -> DownloadTaskRecord {
        DownloadTaskRecord(
            id: id,
            filename: filename,
            destinationPath: destination.path,
            dlink: dlink,
            headers: headers,
            status: status,
            receivedBytes: receivedBytes,
            totalBytes: totalBytes,
            expectedBytes: expectedBytesHint,
            progress: progress,
            errorMessage: errorMessage,
            maxConcurrentDownloads: maxConcurrentDownloads,
            connectionCount: connectionCount,
            updatedAt: Date()
        )
    }

    private func failAfterDownload(message: String, cachedFile: URL) {
        status = .failed
        errorMessage = message
        speedBytesPerSecond = 0
        removeFileIfExists(at: cachedFile)
        cleanupCacheDirectory()
        AppLog.error("download_validation_failed filename=\(filename) error=\(message)")
        notifyStatusChange()
    }

    private func installCachedFile(_ cachedFile: URL) throws {
        let fileManager = FileManager.default
        let destinationDirectory = destination.deletingLastPathComponent()
        try fileManager.createDirectory(at: destinationDirectory, withIntermediateDirectories: true)

        let stagingName = ".\(destination.lastPathComponent).pdm-\(id.uuidString).tmp"
        let stagingURL = destinationDirectory.appendingPathComponent(stagingName)
        removeFileIfExists(at: stagingURL)
        defer { removeFileIfExists(at: stagingURL) }

        do {
            try fileManager.moveItem(at: cachedFile, to: stagingURL)
        } catch {
            AppLog.warning("download_cache_move_fallback filename=\(filename) from=\(cachedFile.path) to=\(stagingURL.path) error=\(error.localizedDescription)")
            try fileManager.copyItem(at: cachedFile, to: stagingURL)
            removeFileIfExists(at: cachedFile)
        }

        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }

        do {
            try fileManager.moveItem(at: stagingURL, to: destination)
        } catch {
            AppLog.warning("download_destination_move_fallback filename=\(filename) from=\(stagingURL.path) to=\(destination.path) error=\(error.localizedDescription)")
            try fileManager.copyItem(at: stagingURL, to: destination)
            removeFileIfExists(at: stagingURL)
        }
    }

    private func validationFailureMessage(
        actualBytes: Int64,
        expectedBytes: Int64,
        response: DownloadResponseInfo
    ) -> String? {
        if let statusCode = response.statusCode, !(200..<300).contains(statusCode) {
            return "HTTP 状态异常：\(statusCode)"
        }

        if isErrorContentType(response.mimeType) || isErrorContentType(response.contentType) {
            let contentType = response.contentType ?? response.mimeType ?? "未知"
            return "响应不是文件：Content-Type \(contentType)"
        }

        if expectedBytes > 0, actualBytes > 0, actualBytes < expectedBytes {
            return "下载内容不完整：实际 \(byteDescription(actualBytes))，期望 \(byteDescription(expectedBytes))"
        }

        if isSuspiciouslySmallFile(actualBytes: actualBytes, expectedBytes: expectedBytes) {
            return "下载内容异常：实际 \(byteDescription(actualBytes))，期望 \(byteDescription(expectedBytes))"
        }

        return nil
    }

    private func isErrorContentType(_ contentType: String?) -> Bool {
        guard let contentType else { return false }
        let normalized = contentType
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""

        return normalized == "text/html"
            || normalized == "application/json"
            || normalized.hasSuffix("+json")
    }

    private func isSuspiciouslySmallFile(actualBytes: Int64, expectedBytes: Int64) -> Bool {
        let smallFileLimit: Int64 = 512 * 1024
        let minimumExpectedBytes: Int64 = 1024 * 1024

        return expectedBytes >= minimumExpectedBytes
            && actualBytes >= 0
            && actualBytes <= smallFileLimit
            && actualBytes * 20 < expectedBytes
    }

    private func fileSize(at url: URL) -> Int64? {
        Self.fileSize(at: url)
    }

    private func removeFileIfExists(at url: URL) {
        Self.removeFileIfExists(at: url)
    }

    private static var cacheRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pdm", isDirectory: true)
            .appendingPathComponent("cache", isDirectory: true)
            .appendingPathComponent("downloads", isDirectory: true)
    }

    static func cleanupStaleCacheDirectories(keeping taskIDs: Set<UUID> = []) {
        let root = cacheRoot
        guard FileManager.default.fileExists(atPath: root.path) else { return }
        if taskIDs.isEmpty {
            try? FileManager.default.removeItem(at: root)
            cleanupEmptyCacheParents()
            return
        }

        let contents = (try? FileManager.default.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: nil
        )) ?? []
        for url in contents {
            guard let id = UUID(uuidString: url.lastPathComponent), taskIDs.contains(id) else {
                try? FileManager.default.removeItem(at: url)
                continue
            }
        }
        cleanupEmptyCacheParents()
    }

    private func prepareCacheDirectory() throws {
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
    }

    private func cleanupCacheDirectory() {
        if FileManager.default.fileExists(atPath: cacheDirectory.path) {
            try? FileManager.default.removeItem(at: cacheDirectory)
        }
        Self.cleanupEmptyParentDirectory(Self.cacheRoot)
        Self.cleanupEmptyCacheParents()
    }

    private func resumableBytesOnDisk() -> Int64 {
        let cachedFile = cacheDirectory.appendingPathComponent("download.cache")
        return fileSize(at: cachedFile) ?? 0
    }

    private static func cleanupEmptyCacheParents() {
        cleanupEmptyParentDirectory(cacheRoot.deletingLastPathComponent())
    }

    private static func cleanupEmptyParentDirectory(_ directory: URL) {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        let contents = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        guard contents.isEmpty else { return }
        try? FileManager.default.removeItem(at: directory)
    }

    private func byteDescription(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }

    private func updateSpeed(totalBytesWritten: Int64) {
        let now = Date()
        defer {
            lastProgressDate = now
            lastProgressBytes = totalBytesWritten
        }

        guard let lastProgressDate else { return }
        let elapsed = now.timeIntervalSince(lastProgressDate)
        guard elapsed >= 0.35 else { return }
        let delta = max(0, totalBytesWritten - lastProgressBytes)
        let instantSpeed = Double(delta) / elapsed
        if speedBytesPerSecond <= 0 {
            speedBytesPerSecond = instantSpeed
        } else {
            speedBytesPerSecond = speedBytesPerSecond * 0.65 + instantSpeed * 0.35
        }
    }

    private func cancelActiveTaskForRetry() {
        activeRunID = nil
        downloadOperation?.cancel()
        downloadOperation = nil
        isCancelling = false
        isPausing = false
    }

    private func notifyStatusChange() {
        lastPersistedProgressDate = .distantPast
        onStatusChange?()
        onPersistentChange?()
    }

    private func notifyProgressChangeIfNeeded(force: Bool = false) {
        let now = Date()
        let byteDelta = abs(receivedBytes - lastPersistedProgressBytes)
        guard force || now.timeIntervalSince(lastPersistedProgressDate) >= 1 || byteDelta >= 4 * 1024 * 1024 else {
            return
        }
        lastPersistedProgressDate = now
        lastPersistedProgressBytes = receivedBytes
        onPersistentChange?()
    }
}

private extension DownloadTaskModel {
    nonisolated static func downloadToCache(
        plan: DownloadPlan,
        progressHandler: @Sendable @escaping (DownloadProgressUpdate) async -> Void
    ) async throws -> DownloadResult {
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: plan.cacheDirectory, withIntermediateDirectories: true)
        let cachedFile = plan.cacheDirectory.appendingPathComponent("download.cache")

        do {
            return try await Aria2Service.shared.download(plan: plan, progressHandler: progressHandler)
        } catch {
            if isCancellation(error) {
                throw error
            }
            if (fileSize(at: cachedFile) ?? 0) > 0 {
                AppLog.warning("aria2_download_failed_preserving_cache filename=\(plan.filename) error=\(error.localizedDescription)")
                throw error
            }
            AppLog.warning("aria2_download_fallback filename=\(plan.filename) error=\(error.localizedDescription)")
            removeFileIfExists(at: cachedFile)
        }

        let probe = await probeRangeSupport(plan: plan)
        let probedTotal = probe?.totalBytes ?? 0
        let expectedBytes = max(plan.expectedBytesHint, probedTotal)
        let supportsRanges = probe?.supportsRanges == true
        let shouldSplit = supportsRanges
            && plan.connectionCount > 1
            && expectedBytes >= 2 * 1024 * 1024

        let response: DownloadResponseInfo
        if shouldSplit {
            do {
                response = try await downloadSegments(
                    plan: plan,
                    cachedFile: cachedFile,
                    expectedBytes: expectedBytes,
                    probeResponse: probe?.response,
                    progressHandler: progressHandler
                )
            } catch DownloadFileError.rangeUnsupported {
                AppLog.warning("download_range_fallback filename=\(plan.filename) reason=range_unsupported")
                response = try await downloadSingleStream(
                    plan: plan,
                    cachedFile: cachedFile,
                    expectedBytes: expectedBytes,
                    progressHandler: progressHandler
                )
            }
        } else {
            response = try await downloadSingleStream(
                plan: plan,
                cachedFile: cachedFile,
                expectedBytes: expectedBytes,
                progressHandler: progressHandler
            )
        }

        let actualBytes = fileSize(at: cachedFile) ?? 0
        let expectedCandidates: [Int64] = [plan.expectedBytesHint, expectedBytes, response.expectedBytes]
        let finalExpectedBytes: Int64 = expectedCandidates
            .filter { $0 > 0 }
            .max() ?? 0
        AppLog.info(
            "download_cached filename=\(plan.filename) bytes=\(actualBytes) expected=\(finalExpectedBytes) split=\(shouldSplit) connections=\(shouldSplit ? plan.connectionCount : 1) cache=\(cachedFile.path)"
        )
        return DownloadResult(
            cachedFile: cachedFile,
            actualBytes: actualBytes,
            expectedBytes: finalExpectedBytes,
            response: response
        )
    }

    nonisolated static func downloadSingleStream(
        plan: DownloadPlan,
        cachedFile: URL,
        expectedBytes: Int64,
        progressHandler: @Sendable @escaping (DownloadProgressUpdate) async -> Void
    ) async throws -> DownloadResponseInfo {
        guard let url = URL(string: plan.sourceURLString) else {
            throw DownloadFileError.invalidURL
        }

        let session = makeSession(connectionCount: 1)
        defer { session.invalidateAndCancel() }

        let (temporaryFile, response) = try await session.download(for: request(url: url, headers: plan.headers))
        let responseInfo = DownloadResponseInfo(response: response)
        try validateInitialResponse(responseInfo, allowPartialContent: false)

        let total = max(expectedBytes, responseInfo.expectedBytes)

        removeFileIfExists(at: cachedFile)
        do {
            try FileManager.default.moveItem(at: temporaryFile, to: cachedFile)
        } catch {
            AppLog.warning("download_single_cache_move_fallback filename=\(plan.filename) from=\(temporaryFile.path) to=\(cachedFile.path) error=\(error.localizedDescription)")
            try FileManager.default.copyItem(at: temporaryFile, to: cachedFile)
            removeFileIfExists(at: temporaryFile)
        }

        let received = fileSize(at: cachedFile) ?? 0
        await progressHandler(DownloadProgressUpdate(receivedBytes: received, totalBytes: total))
        return responseInfo
    }

    nonisolated static func downloadSegments(
        plan: DownloadPlan,
        cachedFile: URL,
        expectedBytes: Int64,
        probeResponse: DownloadResponseInfo?,
        progressHandler: @Sendable @escaping (DownloadProgressUpdate) async -> Void
    ) async throws -> DownloadResponseInfo {
        guard expectedBytes > 0 else {
            throw DownloadFileError.rangeUnsupported
        }
        guard let url = URL(string: plan.sourceURLString) else {
            throw DownloadFileError.invalidURL
        }

        let segmentDirectory = plan.cacheDirectory.appendingPathComponent("segments", isDirectory: true)
        try FileManager.default.createDirectory(at: segmentDirectory, withIntermediateDirectories: true)
        let ranges = byteRanges(totalBytes: expectedBytes, connectionCount: plan.connectionCount)
        let counter = DownloadProgressCounter(totalBytes: expectedBytes, progressHandler: progressHandler)
        let session = makeSession(connectionCount: plan.connectionCount)
        defer { session.invalidateAndCancel() }

        try await withThrowingTaskGroup(of: Void.self) { group in
            for range in ranges {
                let partFile = segmentDirectory.appendingPathComponent("\(range.index).part")
                group.addTask {
                    try await downloadRange(
                        url: url,
                        headers: plan.headers,
                        range: range,
                        partFile: partFile,
                        session: session,
                        counter: counter
                    )
                }
            }
            try await group.waitForAll()
        }

        try concatenateSegments(ranges: ranges, segmentDirectory: segmentDirectory, cachedFile: cachedFile)
        await progressHandler(DownloadProgressUpdate(receivedBytes: expectedBytes, totalBytes: expectedBytes))
        return probeResponse ?? DownloadResponseInfo(
            statusCode: 206,
            contentType: nil,
            mimeType: nil,
            expectedBytes: expectedBytes
        )
    }

    nonisolated static func downloadRange(
        url: URL,
        headers: [String],
        range: DownloadByteRange,
        partFile: URL,
        session: URLSession,
        counter: DownloadProgressCounter
    ) async throws {
        removeFileIfExists(at: partFile)

        try FileManager.default.createFile(at: partFile)
        let handle = try FileHandle(forWritingTo: partFile)
        defer { try? handle.close() }

        let chunkSize: Int64 = 1024 * 1024
        var received: Int64 = 0
        var chunkStart = range.start
        while chunkStart <= range.end {
            try Task.checkCancellation()
            let chunkEnd = min(range.end, chunkStart + chunkSize - 1)
            var request = request(url: url, headers: headers)
            request.setValue("bytes=\(chunkStart)-\(chunkEnd)", forHTTPHeaderField: "Range")
            let (data, response) = try await session.data(for: request)
            let responseInfo = DownloadResponseInfo(response: response)
            guard responseInfo.statusCode == 206 else {
                throw DownloadFileError.rangeUnsupported
            }
            try validateInitialResponse(responseInfo, allowPartialContent: true)
            let expectedChunkBytes = chunkEnd - chunkStart + 1
            guard Int64(data.count) == expectedChunkBytes else {
                throw DownloadFileError.incompleteRange(index: range.index)
            }
            try handle.write(contentsOf: data)
            received += Int64(data.count)
            try validateRangeSize(received: received, range: range)
            await counter.add(Int64(data.count))
            chunkStart = chunkEnd + 1
        }

        guard received == range.length else {
            throw DownloadFileError.incompleteRange(index: range.index)
        }
    }

    nonisolated static func probeRangeSupport(plan: DownloadPlan) async -> RangeProbeResult? {
        guard let url = URL(string: plan.sourceURLString) else { return nil }
        let session = makeSession(connectionCount: 1)
        defer { session.invalidateAndCancel() }

        var request = request(url: url, headers: plan.headers)
        request.setValue("bytes=0-0", forHTTPHeaderField: "Range")
        do {
            let (_, response) = try await session.bytes(for: request)
            let responseInfo = DownloadResponseInfo(response: response)
            guard responseInfo.statusCode == 206 else {
                return RangeProbeResult(
                    supportsRanges: false,
                    totalBytes: max(plan.expectedBytesHint, responseInfo.expectedBytes),
                    response: responseInfo
                )
            }
            let totalBytes = parseTotalBytes(fromContentRange: (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Range"))
            return RangeProbeResult(
                supportsRanges: totalBytes > 0,
                totalBytes: max(plan.expectedBytesHint, totalBytes),
                response: responseInfo.replacingExpectedBytes(max(plan.expectedBytesHint, totalBytes))
            )
        } catch {
            AppLog.warning("download_range_probe_failed filename=\(plan.filename) error=\(error.localizedDescription)")
            return nil
        }
    }

    nonisolated static func request(url: URL, headers: [String]) -> URLRequest {
        var request = URLRequest(url: url)
        request.timeoutInterval = 60
        for header in headers {
            let pieces = header.split(separator: ":", maxSplits: 1).map {
                String($0).trimmingCharacters(in: .whitespacesAndNewlines)
            }
            if pieces.count == 2 {
                request.setValue(pieces[1], forHTTPHeaderField: pieces[0])
            }
        }
        return request
    }

    nonisolated static func makeSession(connectionCount: Int) -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 24 * 60 * 60
        configuration.waitsForConnectivity = true
        configuration.httpMaximumConnectionsPerHost = max(1, min(connectionCount, 16))
        return URLSession(configuration: configuration)
    }

    nonisolated static func validateInitialResponse(_ response: DownloadResponseInfo, allowPartialContent: Bool) throws {
        guard let statusCode = response.statusCode else { return }
        let validStatuses: Range<Int>
        if allowPartialContent {
            validStatuses = 200..<300
        } else {
            validStatuses = 200..<300
        }
        guard validStatuses.contains(statusCode) else {
            throw DownloadFileError.httpStatus(statusCode)
        }
        if isErrorContentType(response.mimeType) || isErrorContentType(response.contentType) {
            let contentType = response.contentType ?? response.mimeType ?? "未知"
            throw DownloadFileError.errorContentType(contentType)
        }
    }

    nonisolated static func isErrorContentType(_ contentType: String?) -> Bool {
        guard let contentType else { return false }
        let normalized = contentType
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""
        return normalized == "text/html"
            || normalized == "application/json"
            || normalized.hasSuffix("+json")
    }

    nonisolated static func byteRanges(totalBytes: Int64, connectionCount: Int) -> [DownloadByteRange] {
        let count = Int(min(max(Int64(connectionCount), 1), min(16, totalBytes)))
        let segmentSize = Int64(ceil(Double(totalBytes) / Double(count)))
        return (0..<count).compactMap { index in
            let start = Int64(index) * segmentSize
            let end = min(totalBytes - 1, start + segmentSize - 1)
            guard start <= end else { return nil }
            return DownloadByteRange(index: index, start: start, end: end)
        }
    }

    nonisolated static func concatenateSegments(
        ranges: [DownloadByteRange],
        segmentDirectory: URL,
        cachedFile: URL
    ) throws {
        removeFileIfExists(at: cachedFile)
        try FileManager.default.createFile(at: cachedFile)
        let output = try FileHandle(forWritingTo: cachedFile)
        defer { try? output.close() }

        for range in ranges {
            let partFile = segmentDirectory.appendingPathComponent("\(range.index).part")
            guard FileManager.default.fileExists(atPath: partFile.path) else {
                throw DownloadFileError.missingSegment(index: range.index)
            }
            let input = try FileHandle(forReadingFrom: partFile)
            defer { try? input.close() }
            while true {
                try Task.checkCancellation()
                let data = try input.read(upToCount: 1024 * 1024) ?? Data()
                if data.isEmpty { break }
                try output.write(contentsOf: data)
            }
        }
    }

    nonisolated static func validateRangeSize(received: Int64, range: DownloadByteRange) throws {
        if received > range.length {
            throw DownloadFileError.incompleteRange(index: range.index)
        }
    }

    nonisolated static func parseTotalBytes(fromContentRange contentRange: String?) -> Int64 {
        guard let contentRange else { return 0 }
        guard let slashIndex = contentRange.lastIndex(of: "/") else { return 0 }
        let suffix = contentRange[contentRange.index(after: slashIndex)...]
        return Int64(suffix) ?? 0
    }

    nonisolated static func fileSize(at url: URL) -> Int64? {
        guard
            let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
            let size = attributes[.size] as? NSNumber
        else {
            return nil
        }
        return size.int64Value
    }

    nonisolated static func removeFileIfExists(at url: URL) {
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    nonisolated static func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        let nsError = error as NSError
        return nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled
    }
}

struct DownloadPlan: Sendable {
    let sourceURLString: String
    let headers: [String]
    let destination: URL
    let cacheDirectory: URL
    let expectedBytesHint: Int64
    let maxConcurrentDownloads: Int
    let connectionCount: Int
    let filename: String
}

struct DownloadProgressUpdate: Sendable {
    let receivedBytes: Int64
    let totalBytes: Int64
    let speedBytesPerSecond: Double?

    init(receivedBytes: Int64, totalBytes: Int64, speedBytesPerSecond: Double? = nil) {
        self.receivedBytes = receivedBytes
        self.totalBytes = totalBytes
        self.speedBytesPerSecond = speedBytesPerSecond
    }
}

struct DownloadResult: Sendable {
    let cachedFile: URL
    let actualBytes: Int64
    let expectedBytes: Int64
    let response: DownloadResponseInfo
}

struct DownloadTaskRecord: Codable {
    let id: UUID
    let filename: String
    let destinationPath: String
    let dlink: String
    let headers: [String]
    let status: DownloadStatus
    let receivedBytes: Int64
    let totalBytes: Int64
    let expectedBytes: Int64
    let progress: Double
    let errorMessage: String
    let maxConcurrentDownloads: Int
    let connectionCount: Int
    let updatedAt: Date
}

enum DownloadTaskStore {
    static var recordsURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pdm", isDirectory: true)
            .appendingPathComponent("downloads.json")
    }

    static func load() -> [DownloadTaskRecord] {
        guard let data = try? Data(contentsOf: recordsURL) else {
            return []
        }
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try decoder.decode([DownloadTaskRecord].self, from: data)
        } catch {
            AppLog.error("download_records_load_failed error=\(error.localizedDescription)")
            return []
        }
    }

    static func save(_ records: [DownloadTaskRecord]) throws {
        let directory = recordsURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(records)
        try data.write(to: recordsURL, options: .atomic)
    }
}

struct DownloadResponseInfo: Sendable {
    let statusCode: Int?
    let contentType: String?
    let mimeType: String?
    let expectedBytes: Int64

    init(statusCode: Int?, contentType: String?, mimeType: String?, expectedBytes: Int64) {
        self.statusCode = statusCode
        self.contentType = contentType
        self.mimeType = mimeType
        self.expectedBytes = expectedBytes
    }

    init(response: URLResponse) {
        let http = response as? HTTPURLResponse
        statusCode = http?.statusCode
        contentType = http?.value(forHTTPHeaderField: "Content-Type") ?? response.mimeType
        mimeType = response.mimeType
        expectedBytes = response.expectedContentLength > 0 ? response.expectedContentLength : 0
    }

    func replacingExpectedBytes(_ bytes: Int64) -> DownloadResponseInfo {
        DownloadResponseInfo(
            statusCode: statusCode,
            contentType: contentType,
            mimeType: mimeType,
            expectedBytes: bytes
        )
    }
}

private struct RangeProbeResult: Sendable {
    let supportsRanges: Bool
    let totalBytes: Int64
    let response: DownloadResponseInfo
}

private struct DownloadByteRange: Sendable {
    let index: Int
    let start: Int64
    let end: Int64

    var length: Int64 {
        end - start + 1
    }
}

private actor DownloadProgressCounter {
    private let totalBytes: Int64
    private let progressHandler: @Sendable (DownloadProgressUpdate) async -> Void
    private var receivedBytes: Int64 = 0
    private var lastReportDate = Date.distantPast

    init(
        totalBytes: Int64,
        progressHandler: @Sendable @escaping (DownloadProgressUpdate) async -> Void
    ) {
        self.totalBytes = totalBytes
        self.progressHandler = progressHandler
    }

    func add(_ byteCount: Int64) async {
        receivedBytes += byteCount
        let now = Date()
        guard now.timeIntervalSince(lastReportDate) >= 0.2 || receivedBytes >= totalBytes else {
            return
        }
        lastReportDate = now
        await progressHandler(DownloadProgressUpdate(receivedBytes: receivedBytes, totalBytes: totalBytes))
    }
}

enum DownloadFileError: LocalizedError {
    case invalidURL
    case httpStatus(Int)
    case errorContentType(String)
    case rangeUnsupported
    case missingSegment(index: Int)
    case incompleteRange(index: Int)
    case aria2(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "下载链接无效"
        case let .httpStatus(status):
            return "HTTP 状态异常：\(status)"
        case let .errorContentType(contentType):
            return "响应不是文件：Content-Type \(contentType)"
        case .rangeUnsupported:
            return "服务器不支持多连接分段下载"
        case let .missingSegment(index):
            return "下载分段缺失：\(index + 1)"
        case let .incompleteRange(index):
            return "下载分段不完整：\(index + 1)"
        case let .aria2(message):
            return message
        }
    }
}

private extension FileManager {
    func createFile(at url: URL) throws {
        let created = createFile(atPath: url.path, contents: nil)
        if !created, !fileExists(atPath: url.path) {
            throw CocoaError(.fileWriteUnknown)
        }
    }
}
