import Foundation

enum AccountStore {
    static var accountsURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pdm", isDirectory: true)
            .appendingPathComponent("accounts.json")
    }

    static var legacyAccountsURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".bduss_downloader", isDirectory: true)
            .appendingPathComponent("accounts.json")
    }

    static func load() -> [SavedAccount] {
        let url = FileManager.default.fileExists(atPath: accountsURL.path) ? accountsURL : legacyAccountsURL
        guard let data = try? Data(contentsOf: url) else { return [] }
        return (try? JSONDecoder().decode([SavedAccount].self, from: data)) ?? []
    }

    static func save(_ accounts: [SavedAccount]) throws {
        let directory = accountsURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(accounts)
        try data.write(to: accountsURL, options: .atomic)
    }
}
