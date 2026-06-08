import Foundation

enum DisplayFormat {
    static func size(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB, .useTB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }

    static func date(_ timestamp: TimeInterval) -> String {
        guard timestamp > 0 else { return "" }
        let date = Date(timeIntervalSince1970: timestamp)
        return date.formatted(date: .numeric, time: .shortened)
    }

    static func speed(_ bytesPerSecond: Double) -> String {
        guard bytesPerSecond > 0 else { return "" }
        return "\(size(Int64(bytesPerSecond)))/s"
    }

    static func eta(remainingBytes: Int64, bytesPerSecond: Double) -> String {
        guard remainingBytes > 0, bytesPerSecond > 1 else { return "" }
        let seconds = Int(Double(remainingBytes) / bytesPerSecond)
        if seconds < 60 {
            return "\(seconds) 秒"
        }
        if seconds < 3600 {
            return "\(seconds / 60) 分 \(seconds % 60) 秒"
        }
        return "\(seconds / 3600) 小时 \((seconds % 3600) / 60) 分"
    }
}

extension URL {
    func uniqueFileURL() -> URL {
        guard FileManager.default.fileExists(atPath: path) else {
            return self
        }

        let directory = deletingLastPathComponent()
        let base = deletingPathExtension().lastPathComponent
        let ext = pathExtension

        var index = 1
        while true {
            let name = ext.isEmpty ? "\(base) (\(index))" : "\(base) (\(index)).\(ext)"
            let candidate = directory.appendingPathComponent(name)
            if !FileManager.default.fileExists(atPath: candidate.path) {
                return candidate
            }
            index += 1
        }
    }
}
