import Foundation

struct PanFile: Decodable, Identifiable, Hashable {
    let fsID: Int64
    let path: String
    let serverFilename: String
    let size: Int64
    let isDirectory: Bool
    let serverMTime: TimeInterval
    let dlink: String?

    var id: String {
        "\(fsID)-\(path)"
    }

    enum CodingKeys: String, CodingKey {
        case fsID = "fs_id"
        case path
        case serverFilename = "server_filename"
        case size
        case isdir
        case serverMTime = "server_mtime"
        case dlink
    }

    init(
        fsID: Int64,
        path: String,
        serverFilename: String,
        size: Int64,
        isDirectory: Bool,
        serverMTime: TimeInterval,
        dlink: String? = nil
    ) {
        self.fsID = fsID
        self.path = path
        self.serverFilename = serverFilename
        self.size = size
        self.isDirectory = isDirectory
        self.serverMTime = serverMTime
        self.dlink = dlink
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        fsID = container.decodeLossyInt64(forKey: .fsID)
        path = (try? container.decode(String.self, forKey: .path)) ?? ""
        let fallbackName = path.split(separator: "/").last.map(String.init) ?? path
        serverFilename = (try? container.decode(String.self, forKey: .serverFilename)) ?? fallbackName
        size = container.decodeLossyInt64(forKey: .size)
        isDirectory = container.decodeLossyInt64(forKey: .isdir) == 1
        serverMTime = TimeInterval(container.decodeLossyInt64(forKey: .serverMTime))
        dlink = try? container.decode(String.self, forKey: .dlink)
    }
}

struct APIEnvelope<T: Decodable>: Decodable {
    let errno: Int
    let errmsg: String?
    let list: T?
    let info: T?
    let shareid: String?
    let uk: String?
    let randsk: String?

    enum CodingKeys: String, CodingKey {
        case errno
        case errmsg
        case list
        case info
        case shareid
        case uk
        case randsk
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        errno = Int(container.decodeLossyInt64(forKey: .errno))
        errmsg = try? container.decode(String.self, forKey: .errmsg)
        list = try? container.decode(T.self, forKey: .list)
        info = try? container.decode(T.self, forKey: .info)
        shareid = try? container.decode(String.self, forKey: .shareid)
        uk = try? container.decode(String.self, forKey: .uk)
        randsk = try? container.decode(String.self, forKey: .randsk)
    }
}

struct UserInfo {
    let username: String
}

struct QuotaInfo {
    let used: Int64
    let total: Int64
}

struct SavedAccount: Codable, Identifiable, Hashable {
    var id: String { username }
    var username: String
    var vipType: String
    var cookie: String

    enum CodingKeys: String, CodingKey {
        case username
        case vipType = "vip_type"
        case cookie
    }

    init(username: String, vipType: String, cookie: String) {
        self.username = username
        self.vipType = vipType
        self.cookie = cookie
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        username = (try? container.decode(String.self, forKey: .username)) ?? "未知"
        vipType = (try? container.decode(String.self, forKey: .vipType)) ?? "未知"
        cookie = (try? container.decode(String.self, forKey: .cookie)) ?? ""
    }
}

struct ResolvedDownload {
    let url: String
    let headers: [String]
}
