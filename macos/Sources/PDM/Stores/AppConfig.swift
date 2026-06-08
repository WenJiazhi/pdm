import Foundation

struct AppConfig: Codable {
    var bduss = ""
    var bdussBfess = ""
    var fullCookie = ""
    var downloadDir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Downloads")
        .path
    var maxConcurrentTasks = 2
    var taskConnections = 16

    enum CodingKeys: String, CodingKey {
        case bduss
        case bdussBfess = "bduss_bfess"
        case fullCookie = "full_cookie"
        case downloadDir = "download_dir"
        case maxConcurrentTasks = "max_concurrent_tasks"
        case taskConnections = "task_connections"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        bduss = (try? container.decode(String.self, forKey: .bduss)) ?? ""
        bdussBfess = (try? container.decode(String.self, forKey: .bdussBfess)) ?? ""
        fullCookie = (try? container.decode(String.self, forKey: .fullCookie)) ?? ""
        downloadDir = (try? container.decode(String.self, forKey: .downloadDir)) ?? downloadDir
        maxConcurrentTasks = (try? container.decode(Int.self, forKey: .maxConcurrentTasks)) ?? maxConcurrentTasks
        taskConnections = (try? container.decode(Int.self, forKey: .taskConnections)) ?? taskConnections
    }

    var effectiveCookie: String {
        if !fullCookie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return fullCookie
        }

        var parts: [String] = []
        if !bduss.isEmpty {
            parts.append("BDUSS=\(bduss)")
        }
        if !bdussBfess.isEmpty {
            parts.append("BDUSS_BFESS=\(bdussBfess)")
        }
        return parts.joined(separator: "; ")
    }
}

enum ConfigStore {
    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pdm", isDirectory: true)
            .appendingPathComponent("config.json")
    }

    static var legacyConfigURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".bduss_downloader", isDirectory: true)
            .appendingPathComponent("config.json")
    }

    static func load() -> AppConfig {
        let url = FileManager.default.fileExists(atPath: configURL.path) ? configURL : legacyConfigURL
        return load(from: url)
    }

    static func load(from url: URL) -> AppConfig {
        guard let data = try? Data(contentsOf: url) else {
            return AppConfig()
        }

        do {
            var config = try JSONDecoder().decode(AppConfig.self, from: data)
            config.maxConcurrentTasks = min(max(config.maxConcurrentTasks, 1), 8)
            config.taskConnections = min(max(config.taskConnections, 1), 16)
            config.normalizeDownloadDirectory()
            return config
        } catch {
            var config = AppConfig()
            config.normalizeDownloadDirectory()
            return config
        }
    }

    static func save(_ config: AppConfig) throws {
        let directory = configURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(config)
        try data.write(to: configURL, options: .atomic)
    }
}

private extension AppConfig {
    mutating func normalizeDownloadDirectory() {
        if downloadDir.contains("\\") || downloadDir.range(of: #"^[A-Za-z]:"#, options: .regularExpression) != nil {
            downloadDir = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Downloads")
                .path
        }
    }
}
