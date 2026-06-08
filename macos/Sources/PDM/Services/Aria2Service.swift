import Darwin
import Foundation

actor Aria2Service {
    static let shared = Aria2Service()

    private var process: Process?
    private var logHandle: FileHandle?
    private var rpcPort = 0
    private var rpcSecret = ""
    private var isReady = false
    private let session: URLSession

    private init() {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 5
        configuration.timeoutIntervalForResource = 20
        session = URLSession(configuration: configuration)
    }

    func download(
        plan: DownloadPlan,
        progressHandler: @Sendable @escaping (DownloadProgressUpdate) async -> Void
    ) async throws -> DownloadResult {
        try await ensureStarted(plan: plan)

        let cachedFile = plan.cacheDirectory.appendingPathComponent("download.cache")
        try FileManager.default.createDirectory(at: plan.cacheDirectory, withIntermediateDirectories: true)

        let options: [String: Any] = [
            "dir": plan.cacheDirectory.path,
            "out": cachedFile.lastPathComponent,
            "header": plan.headers,
            "split": String(plan.connectionCount),
            "max-connection-per-server": String(plan.connectionCount),
            "min-split-size": "1M",
            "continue": "true",
            "allow-overwrite": "true",
            "auto-file-renaming": "false",
            "file-allocation": "none",
            "check-certificate": "false"
        ]

        guard let gid = try await rpc("aria2.addUri", params: [[plan.sourceURLString], options]) as? String else {
            throw DownloadFileError.aria2("Aria 未返回任务 ID")
        }
        AppLog.info("aria2_task_started filename=\(plan.filename) gid=\(gid) connections=\(plan.connectionCount)")

        do {
            var lastCompleted: Int64 = 0
            var lastTotal: Int64 = plan.expectedBytesHint
            while true {
                try Task.checkCancellation()
                try await Task.sleep(for: .milliseconds(450))

                let status = try await tellStatus(gid: gid)
                let completed = status.int64("completedLength")
                let total = max(status.int64("totalLength"), plan.expectedBytesHint)
                let speed = Double(status.int64("downloadSpeed"))
                if completed != lastCompleted || total != lastTotal {
                    lastCompleted = completed
                    lastTotal = total
                    await progressHandler(DownloadProgressUpdate(receivedBytes: completed, totalBytes: total, speedBytesPerSecond: speed))
                }

                switch status.string("status") {
                case "complete":
                    _ = try? await rpc("aria2.removeDownloadResult", params: [gid])
                    let actualBytes = fileSize(at: cachedFile) ?? completed
                    let expectedBytes = max(total, plan.expectedBytesHint, actualBytes)
                    await progressHandler(DownloadProgressUpdate(receivedBytes: actualBytes, totalBytes: expectedBytes))
                    AppLog.info("aria2_task_finished filename=\(plan.filename) gid=\(gid) bytes=\(actualBytes)")
                    return DownloadResult(
                        cachedFile: cachedFile,
                        actualBytes: actualBytes,
                        expectedBytes: expectedBytes,
                        response: DownloadResponseInfo(
                            statusCode: 200,
                            contentType: nil,
                            mimeType: nil,
                            expectedBytes: expectedBytes
                        )
                    )
                case "error":
                    let code = status.string("errorCode")
                    let message = status.string("errorMessage")
                    _ = try? await rpc("aria2.removeDownloadResult", params: [gid])
                    throw DownloadFileError.aria2(message.isEmpty ? "Aria 下载失败：\(code)" : "Aria 下载失败：\(message)（\(code)）")
                case "removed":
                    throw CancellationError()
                default:
                    continue
                }
            }
        } catch {
            _ = try? await rpc("aria2.remove", params: [gid])
            _ = try? await rpc("aria2.removeDownloadResult", params: [gid])
            throw error
        }
    }

    func shutdown() async {
        if isReady {
            _ = try? await rpc("aria2.shutdown")
        }
        process?.terminate()
        process = nil
        isReady = false
        try? logHandle?.close()
        logHandle = nil
    }

    private func ensureStarted(plan: DownloadPlan) async throws {
        if isReady, process?.isRunning == true {
            try await applyOptions(plan: plan)
            return
        }

        guard let executableURL = bundledAria2ExecutableURL() else {
            throw DownloadFileError.aria2("未找到内置 Aria：Contents/Resources/aria2/aria2c")
        }

        rpcPort = Self.availablePort(in: 16850...16950) ?? 16850
        rpcSecret = UUID().uuidString.replacingOccurrences(of: "-", with: "")

        let logURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pdm", isDirectory: true)
            .appendingPathComponent("logs", isDirectory: true)
            .appendingPathComponent("aria2c.log")
        try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            try Data().write(to: logURL)
        }
        let handle = try FileHandle(forWritingTo: logURL)
        try handle.seekToEnd()

        let ariaProcess = Process()
        ariaProcess.executableURL = executableURL
        ariaProcess.currentDirectoryURL = executableURL.deletingLastPathComponent()
        ariaProcess.standardOutput = handle
        ariaProcess.standardError = handle
        ariaProcess.arguments = [
            "--enable-rpc=true",
            "--rpc-listen-all=false",
            "--rpc-listen-port=\(rpcPort)",
            "--rpc-secret=\(rpcSecret)",
            "--rpc-allow-origin-all=false",
            "--max-concurrent-downloads=\(plan.maxConcurrentDownloads)",
            "--max-connection-per-server=\(plan.connectionCount)",
            "--split=\(plan.connectionCount)",
            "--min-split-size=1M",
            "--continue=true",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--file-allocation=none",
            "--summary-interval=0",
            "--console-log-level=warn",
            "--check-certificate=false",
            "--stop-with-process=\(ProcessInfo.processInfo.processIdentifier)"
        ]

        process = ariaProcess
        logHandle = handle
        try ariaProcess.run()
        AppLog.info("aria2_process_started path=\(executableURL.path) pid=\(ariaProcess.processIdentifier) port=\(rpcPort)")

        for _ in 0..<40 {
            if ariaProcess.isRunning == false {
                throw DownloadFileError.aria2("Aria 启动后立即退出")
            }
            do {
                _ = try await rpc("aria2.getVersion")
                try await applyOptions(plan: plan)
                isReady = true
                AppLog.info("aria2_rpc_ready port=\(rpcPort)")
                return
            } catch {
                try await Task.sleep(for: .milliseconds(200))
            }
        }

        ariaProcess.terminate()
        process = nil
        isReady = false
        throw DownloadFileError.aria2("Aria RPC 启动超时")
    }

    private func applyOptions(plan: DownloadPlan) async throws {
        try await rpc("aria2.changeGlobalOption", params: [[
            "max-concurrent-downloads": String(plan.maxConcurrentDownloads),
            "max-connection-per-server": String(plan.connectionCount),
            "split": String(plan.connectionCount)
        ]])
    }

    private func bundledAria2ExecutableURL() -> URL? {
        guard let resourceURL = Bundle.main.resourceURL else { return nil }
        let executableURL = resourceURL
            .appendingPathComponent("aria2", isDirectory: true)
            .appendingPathComponent("aria2c")
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            return nil
        }
        return executableURL
    }

    private func tellStatus(gid: String) async throws -> [String: Any] {
        let keys = [
            "status",
            "completedLength",
            "totalLength",
            "downloadSpeed",
            "errorCode",
            "errorMessage"
        ]
        guard let object = try await rpc("aria2.tellStatus", params: [gid, keys]) as? [String: Any] else {
            throw DownloadFileError.aria2("Aria 状态返回无效")
        }
        return object
    }

    @discardableResult
    private func rpc(_ method: String, params: [Any] = []) async throws -> Any? {
        guard rpcPort > 0 else {
            throw DownloadFileError.aria2("Aria RPC 未启动")
        }
        let payload: [String: Any] = [
            "jsonrpc": "2.0",
            "id": UUID().uuidString,
            "method": method,
            "params": ["token:\(rpcSecret)"] + params
        ]
        let body = try JSONSerialization.data(withJSONObject: payload)
        guard let url = URL(string: "http://127.0.0.1:\(rpcPort)/jsonrpc") else {
            throw DownloadFileError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, _) = try await session.data(for: request)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw DownloadFileError.aria2("Aria RPC 返回无效")
        }
        if let error = object["error"] as? [String: Any] {
            let code = error["code"] as? Int ?? 0
            let message = error["message"] as? String ?? "未知错误"
            throw DownloadFileError.aria2("Aria RPC \(method) 失败：\(message)（\(code)）")
        }
        return object["result"]
    }

    private func removeFileIfExists(at url: URL) {
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    private func fileSize(at url: URL) -> Int64? {
        guard
            let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
            let size = attributes[.size] as? NSNumber
        else {
            return nil
        }
        return size.int64Value
    }

    private static func availablePort(in range: ClosedRange<Int>) -> Int? {
        for port in range {
            if canBind(port: port) {
                return port
            }
        }
        return nil
    }

    private static func canBind(port: Int) -> Bool {
        let fileDescriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard fileDescriptor >= 0 else { return false }
        defer { close(fileDescriptor) }

        var value: Int32 = 1
        setsockopt(fileDescriptor, SOL_SOCKET, SO_REUSEADDR, &value, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(port).bigEndian
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        return withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
                bind(fileDescriptor, socketAddress, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}

private extension Dictionary where Key == String, Value == Any {
    func string(_ key: String) -> String {
        if let value = self[key] as? String {
            return value
        }
        if let value = self[key] as? NSNumber {
            return value.stringValue
        }
        return ""
    }

    func int64(_ key: String) -> Int64 {
        if let value = self[key] as? Int64 {
            return value
        }
        if let value = self[key] as? Int {
            return Int64(value)
        }
        if let value = self[key] as? NSNumber {
            return value.int64Value
        }
        if let value = self[key] as? String {
            return Int64(value) ?? 0
        }
        return 0
    }
}
