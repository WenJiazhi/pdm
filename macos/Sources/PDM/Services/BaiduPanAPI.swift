import Foundation
import CryptoKit

enum BaiduPanError: LocalizedError {
    case invalidURL
    case invalidShareURL
    case api(Int, String)
    case parse(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "无效 URL"
        case .invalidShareURL:
            return "无效分享链接"
        case let .api(code, message):
            if code == -12 {
                return "提取码错误"
            }
            if code == -9 {
                return "链接已过期或不存在"
            }
            if code == 2 {
                return "转存目录暂时未就绪或存在冲突（errno=2），请稍后重试"
            }
            if code == 200025 {
                let suffix = message.isEmpty ? "" : "：\(message)"
                return "转存失败（errno=200025）\(suffix)。请重新导入浏览器中的完整 Cookie 后再试。"
            }
            return message.isEmpty ? "API 错误：\(code)" : message
        case let .parse(message):
            return message
        }
    }
}

@MainActor
final class BaiduPanAPI {
    nonisolated static let base = URL(string: "https://pan.baidu.com")!
    nonisolated static let userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    nonisolated static let pcsUserAgent = "softxm;netdisk"

    private let session: URLSession
    private var config: AppConfig
    private var bdstoken = ""
    private var bdclnd = ""
    private var cachedUID = ""

    init(config: AppConfig) {
        self.config = config
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 20
        configuration.httpCookieAcceptPolicy = .always
        self.session = URLSession(configuration: configuration)
    }

    func update(config: AppConfig) {
        self.config = config
        bdstoken = ""
        bdclnd = ""
        cachedUID = ""
    }

    func cookieHeader() -> String {
        cookieHeader(overridingBDCLND: nil)
    }

    private func cookieHeader(overridingBDCLND override: String?) -> String {
        let activeBDCLND = (override ?? bdclnd).trimmingCharacters(in: .whitespacesAndNewlines)
        var parts = config.effectiveCookie
            .split(separator: ";")
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        if !activeBDCLND.isEmpty {
            parts.removeAll { part in
                let name = part.split(separator: "=", maxSplits: 1).first.map(String.init) ?? ""
                return name.trimmingCharacters(in: .whitespacesAndNewlines).caseInsensitiveCompare("BDCLND") == .orderedSame
            }
            parts.append("BDCLND=\(activeBDCLND)")
        }
        return parts.joined(separator: "; ")
    }

    func getUserInfo() async throws -> UserInfo {
        let (data, response) = try await send(path: "/disk/home", acceptJSON: false)
        let text = String(decoding: data, as: UTF8.self)
        if let url = response.url?.absoluteString, url.contains("/login") || url.contains("/passport/") {
            throw BaiduPanError.api(-6, "BDUSS 无效或已过期")
        }

        let usernamePatterns = [
            #""username"\s*:\s*"([^"]+)""#,
            #""loginUserName"\s*:\s*"([^"]+)""#,
            #""UNAME"\s*:\s*"([^"]+)""#,
            #""user_name"\s*:\s*"([^"]+)""#,
            #""show_name"\s*:\s*"([^"]+)""#,
            #"data-username="([^"]+)""#
        ]
        let username = usernamePatterns.compactMap { text.firstMatch(pattern: $0) }.first
        if let token = text.firstMatch(pattern: #""bdstoken"\s*:\s*"([a-f0-9]{32})""#) {
            bdstoken = token
        }
        if let username, !username.isEmpty {
            return UserInfo(username: username)
        }
        if text.lowercased().contains("netdisk") || response.url?.absoluteString.contains("disk") == true {
            return UserInfo(username: "用户")
        }
        throw BaiduPanError.api(-6, "无法读取用户信息")
    }

    func getQuota() async throws -> QuotaInfo {
        let object = try await jsonObject(path: "/api/quota", query: [
            URLQueryItem(name: "checkexpire", value: "1"),
            URLQueryItem(name: "checkfree", value: "1")
        ], context: "获取容量 /api/quota")
        return QuotaInfo(
            used: object.int64("used"),
            total: object.int64("total")
        )
    }

    func getVIPType() async -> String {
        do {
            let object = try await jsonObject(path: "/api/gettemplatevariable", query: [
                URLQueryItem(name: "clienttype", value: "0"),
                URLQueryItem(name: "web", value: "1"),
                URLQueryItem(name: "fields", value: #"["is_vip","is_svip"]"#)
            ], context: "检测会员 /api/gettemplatevariable")
            guard object.int("errno") == 0,
                  let result = object["result"] as? [String: Any] else {
                return "普通用户"
            }
            if result.int("is_svip") == 1 {
                return "SVIP"
            }
            if result.int("is_vip") == 1 {
                return "VIP"
            }
            return "普通用户"
        } catch {
            return "未知"
        }
    }

    func listFiles(path: String) async throws -> [PanFile] {
        try await fetchBDSToken()
        var query = standardQuery()
        query.append(contentsOf: [
            URLQueryItem(name: "dir", value: path),
            URLQueryItem(name: "page", value: "1"),
            URLQueryItem(name: "num", value: "100"),
            URLQueryItem(name: "order", value: "name"),
            URLQueryItem(name: "desc", value: "0")
        ])
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }
        return try await decodeFileList(path: "/api/list", query: query)
    }

    func searchFiles(keyword: String, directory: String = "/") async throws -> [PanFile] {
        try await fetchBDSToken()
        var query = standardQuery()
        query.append(contentsOf: [
            URLQueryItem(name: "key", value: keyword),
            URLQueryItem(name: "dir", value: directory),
            URLQueryItem(name: "page", value: "1"),
            URLQueryItem(name: "num", value: "100"),
            URLQueryItem(name: "recursion", value: "1")
        ])
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }
        return try await decodeFileList(path: "/api/search", query: query)
    }

    func getDownloadLink(fsID: Int64) async throws -> String {
        try await fetchBDSToken()
        var query = standardQuery()
        query.append(contentsOf: [
            URLQueryItem(name: "fsids", value: "[\(fsID)]"),
            URLQueryItem(name: "dlink", value: "1")
        ])
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }

        let object = try await jsonObject(path: "/api/filemetas", query: query, context: "获取下载链接 /api/filemetas")
        if object.int("errno") != 0 {
            throw apiError(object, context: "获取下载链接 /api/filemetas")
        }
        let items = object.array("list").isEmpty ? object.array("info") : object.array("list")
        guard let dlink = items.first?.string("dlink"), !dlink.isEmpty else {
            throw BaiduPanError.parse("没有返回下载链接")
        }
        return dlink
    }

    func resolveDownloadURL(dlink: String, panPath: String, fsID: Int64 = 0) async -> ResolvedDownload {
        let resolved = await resolveCDNURL(dlink: dlink, panPath: panPath, fsID: fsID)
        if resolved.isLocate {
            return ResolvedDownload(
                url: resolved.url,
                headers: [
                    "User-Agent: \(Self.pcsUserAgent)",
                    "Cookie: BDUSS=\(bdussValue());"
                ]
            )
        }
        if resolved.isCDN {
            return ResolvedDownload(
                url: resolved.url,
                headers: [
                    "User-Agent: \(Self.userAgent)",
                    "Referer: https://pan.baidu.com/disk/home"
                ]
            )
        }
        return ResolvedDownload(
            url: resolved.url,
            headers: [
                "User-Agent: \(Self.userAgent)",
                "Cookie: \(cookieHeader())",
                "Referer: https://pan.baidu.com/disk/home"
            ]
        )
    }

    private func resolveCDNURL(dlink: String, panPath: String, fsID: Int64) async -> CDNResolveResult {
        if !panPath.isEmpty {
            for appID in ["250528", "778750"] {
                if let locateURL = await getLocateDownloadURL(path: panPath, appID: appID), !locateURL.isEmpty {
                    return CDNResolveResult(url: locateURL, isCDN: true, isLocate: true)
                }
            }
        }

        if let sessionRedirect = await resolveViaSessionRedirect(dlink: dlink) {
            return sessionRedirect
        }

        if !panPath.isEmpty {
            for appID in ["250528", "778750"] {
                if let pcsURL = await resolveViaPCSDownload(path: panPath, appID: appID) {
                    return CDNResolveResult(url: pcsURL, isCDN: true, isLocate: false)
                }
            }
        }

        if let location = await resolveViaDirect302(dlink: dlink) {
            return CDNResolveResult(url: location, isCDN: true, isLocate: false)
        }

        return CDNResolveResult(url: dlink, isCDN: false, isLocate: false)
    }

    private func getLocateDownloadURL(path: String, appID: String) async -> String? {
        let bduss = bdussValue()
        guard !bduss.isEmpty else { return nil }

        let uid = await userID()
        let encodedBDUSS = bduss.sha1Hex
        let devuid = "\(bduss.md5Hex.uppercased())|0"
        let timestamp = String(Int(Date().timeIntervalSince1970))
        let randSource = encodedBDUSS + uid + "ebrcUYiuxaZv2XGu7KIYKxUrqfnOfpDF" + timestamp + devuid

        let query: [(String, String)] = [
            ("apn_id", "1_0"),
            ("app_id", appID),
            ("channel", "0"),
            ("check_blue", "1"),
            ("clienttype", "17"),
            ("es", "1"),
            ("esl", "1"),
            ("freeisp", "0"),
            ("method", "locatedownload"),
            ("path", path.urlQueryPlusEncoded),
            ("queryfree", "0"),
            ("use", "0"),
            ("ver", "4.0"),
            ("time", timestamp),
            ("rand", randSource.sha1Hex),
            ("devuid", devuid),
            ("cuid", devuid)
        ]
        let queryString = query
            .map { key, value in "\(key)=\(value)" }
            .joined(separator: "&")
        guard let url = URL(string: "https://pcs.baidu.com/rest/2.0/pcs/file?\(queryString)") else {
            return nil
        }

        do {
            let (data, _) = try await requestAbsoluteURL(
                url,
                headers: [
                    "User-Agent": Self.pcsUserAgent,
                    "Cookie": "BDUSS=\(bduss);"
                ],
                followRedirects: true
            )
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                AppLog.error("locatedownload app_id=\(appID) invalid_json bytes=\(data.count)")
                return nil
            }
            let errno = object.int("errno")
            let host = object.string("host")
            let urls = object["urls"] as? [[String: Any]] ?? []
            AppLog.info("locatedownload app_id=\(appID) errno=\(errno) host=\(host.isEmpty ? "-" : host) urls=\(urls.count)")
            if object.string("host") == "issuecdn.baidupcs.com" {
                return nil
            }
            if let first = urls.first?.string("url"),
               !first.isEmpty {
                return first
            }
        } catch {
            AppLog.error("locatedownload app_id=\(appID) error=\(error.localizedDescription)")
            return nil
        }
        return nil
    }

    private func resolveViaSessionRedirect(dlink: String) async -> CDNResolveResult? {
        guard let url = URL(string: dlink) else { return nil }
        do {
            let response = try await responseOnlyAbsoluteURL(
                url,
                headers: ["Referer": "https://pan.baidu.com/disk/home"],
                followRedirects: true
            )
            let finalURL = response.url?.absoluteString ?? dlink
            if response.statusCode == 200, finalURL != dlink {
                return CDNResolveResult(url: finalURL, isCDN: true, isLocate: false)
            }
            if response.statusCode == 200 {
                return CDNResolveResult(url: dlink, isCDN: false, isLocate: false)
            }
        } catch {
            return nil
        }
        return nil
    }

    private func resolveViaPCSDownload(path: String, appID: String) async -> String? {
        let encodedPath = path.pcsPathEncoded
        guard let url = URL(string: "https://d.pcs.baidu.com/rest/2.0/pcs/file?method=download&path=\(encodedPath)&app_id=\(appID)") else {
            return nil
        }

        do {
            let response = try await responseOnlyAbsoluteURL(
                url,
                headers: ["Referer": "https://pan.baidu.com/disk/home"],
                followRedirects: false
            )
            if (301...308).contains(response.statusCode),
               let location = response.value(forHTTPHeaderField: "Location"),
               !location.isEmpty {
                return location
            }
            if response.statusCode == 200,
               let finalURL = response.url?.absoluteString,
               finalURL.contains("baidupcs.com") {
                return finalURL
            }
        } catch {
            return nil
        }
        return nil
    }

    private func resolveViaDirect302(dlink: String) async -> String? {
        guard let url = URL(string: dlink) else { return nil }
        do {
            let response = try await responseOnlyAbsoluteURL(
                url,
                headers: ["Referer": "https://pan.baidu.com/disk/home"],
                followRedirects: false
            )
            if (301...308).contains(response.statusCode),
               let location = response.value(forHTTPHeaderField: "Location"),
               !location.isEmpty {
                return location
            }
        } catch {
            return nil
        }
        return nil
    }

    private func userID() async -> String {
        if !cachedUID.isEmpty { return cachedUID }
        do {
            let object = try await jsonObject(path: "/rest/2.0/xpan/nas", query: [
                URLQueryItem(name: "method", value: "uinfo")
            ], context: "获取用户 UID /rest/2.0/xpan/nas")
            cachedUID = object.string("uk")
        } catch {
            cachedUID = ""
        }
        return cachedUID
    }

    private func bdussValue() -> String {
        if !config.bduss.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return config.bduss.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return cookiePairs()["BDUSS"] ?? ""
    }

    static func parseShareURL(_ url: String) -> String? {
        if let match = url.firstMatch(pattern: #"pan\.baidu\.com/s/1([A-Za-z0-9_-]+)"#) {
            return match
        }
        if let match = url.firstMatch(pattern: #"surl=([A-Za-z0-9_-]+)"#) {
            return match
        }
        return nil
    }

    func listShareFiles(shareURL: String, password: String) async throws -> ShareListResult {
        guard let surl = Self.parseShareURL(shareURL) else {
            throw BaiduPanError.invalidShareURL
        }

        var randsk = ""
        if !password.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let verify = try await verifyShare(surl: surl, password: password)
            if verify.int("errno") != 0 {
                throw apiError(verify, context: "验证分享提取码 /share/verify")
            }
            randsk = verify.string("randsk")
            bdclnd = randsk
        } else if let savedBDCLND = cookiePairs()["BDCLND"] {
            randsk = savedBDCLND
            bdclnd = savedBDCLND
        }

        let pageInfo = try await getSharePageInfo(surl: surl)
        let shareid = pageInfo.shareID
        let uk = pageInfo.uk

        if !pageInfo.files.isEmpty {
            return ShareListResult(surl: surl, shareID: shareid, uk: uk, randsk: randsk, files: pageInfo.files)
        }
        if shareid.isEmpty || uk.isEmpty {
            throw BaiduPanError.parse("无法提取 shareid/uk")
        }
        let files = try await listShareDirectory(shareID: shareid, uk: uk, directory: "/")
        return ShareListResult(surl: surl, shareID: shareid, uk: uk, randsk: randsk, files: files)
    }

    func listShareDirectory(shareID: String, uk: String, directory: String) async throws -> [PanFile] {
        let query = standardQuery() + [
            URLQueryItem(name: "shareid", value: shareID),
            URLQueryItem(name: "uk", value: uk),
            URLQueryItem(name: "dir", value: directory),
            URLQueryItem(name: "page", value: "1"),
            URLQueryItem(name: "num", value: "100"),
            URLQueryItem(name: "order", value: "name")
        ]
        return try await decodeFileList(path: "/share/list", query: query)
    }

    func createDirectory(path: String) async throws {
        try await fetchBDSToken()
        var query = standardQuery()
        query.append(URLQueryItem(name: "a", value: "commit"))
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }
        let object = try await postForm(path: "/api/create", query: query, form: [
            ("path", path),
            ("isdir", "1"),
            ("block_list", "[]")
        ], context: "创建目录 /api/create")
        if object.int("errno") != 0 {
            throw apiError(object, context: "创建目录 /api/create")
        }
    }

    func deleteFiles(paths: [String], onNest: String = "fail") async throws {
        guard !paths.isEmpty else { return }
        try await fetchBDSToken()
        var query = [
            URLQueryItem(name: "opera", value: "delete"),
            URLQueryItem(name: "async", value: "2"),
            URLQueryItem(name: "onnest", value: onNest)
        ] + standardQuery()
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }

        let fileListData = try JSONSerialization.data(withJSONObject: paths)
        let fileList = String(decoding: fileListData, as: UTF8.self)
        let object = try await postForm(path: "/api/filemanager", query: query, form: [
            ("filelist", fileList)
        ], context: "删除文件 /api/filemanager")
        if object.int("errno") != 0 {
            throw apiError(object, context: "删除文件 /api/filemanager")
        }
    }

    func transferShareFiles(
        surl: String,
        shareID: String,
        uk: String,
        fsIDs: [Int64],
        toPath: String,
        randsk: String
    ) async throws {
        try await fetchBDSToken()
        let originalRandsk = randsk.trimmingCharacters(in: .whitespacesAndNewlines)
        let decodedRandsk = originalRandsk.percentDecodedRepeatedly
        if !originalRandsk.isEmpty {
            bdclnd = originalRandsk
        }

        let pageInfo = try await getSharePageInfo(surl: surl)
        let transferShareID = pageInfo.shareID.isEmpty ? shareID : pageInfo.shareID
        let transferUK = pageInfo.uk.isEmpty ? uk : pageInfo.uk

        guard !transferShareID.isEmpty, !transferUK.isEmpty else {
            throw BaiduPanError.parse("无法提取 shareid/uk")
        }

        let baseQuery = [
            URLQueryItem(name: "shareid", value: transferShareID),
            URLQueryItem(name: "from", value: transferUK)
        ] + standardQuery()

        var query = baseQuery
        if !bdstoken.isEmpty {
            query.append(URLQueryItem(name: "bdstoken", value: bdstoken))
        }

        let compactFSIDList = "[" + fsIDs.map(String.init).joined(separator: ",") + "]"
        let spacedFSIDList = "[" + fsIDs.map(String.init).joined(separator: ", ") + "]"
        let attempts = transferAttempts(
            decodedRandsk: decodedRandsk,
            originalRandsk: originalRandsk,
            compactFSIDList: compactFSIDList,
            spacedFSIDList: spacedFSIDList,
            surl: surl
        )

        var lastObject: [String: Any]?
        for attempt in attempts {
            var attemptQuery = attempt.includeBDSToken ? query : baseQuery
            if let sekey = attempt.sekey, !sekey.isEmpty {
                attemptQuery.append(URLQueryItem(name: "sekey", value: sekey))
            }
            let transferCookieHeader = cookieHeader(overridingBDCLND: attempt.cookieBDCLND)

            AppLog.info(
                "transfer_share_files attempt=\(attempt.name) shareid_len=\(transferShareID.count) uk_len=\(transferUK.count) fsid_count=\(fsIDs.count) fsidlist_len=\(attempt.fsidList.count) to_path=\(toPath) has_bdstoken=\(attempt.includeBDSToken && !bdstoken.isEmpty) has_bdclnd=\(transferCookieHeader.contains("BDCLND=")) has_sekey=\(attempt.sekey?.isEmpty == false) sekey_len=\(attempt.sekey?.count ?? 0)"
            )
            let object = try await postForm(
                path: "/share/transfer",
                query: attemptQuery,
                form: [
                    ("fsidlist", attempt.fsidList),
                    ("path", toPath)
                ],
                referer: attempt.referer,
                cookieHeaderValue: transferCookieHeader,
                extraHeaders: [
                    "Origin": "https://pan.baidu.com",
                    "X-Requested-With": "XMLHttpRequest"
                ],
                context: "转存分享 /share/transfer \(attempt.name)",
                logNonZeroAsWarning: true
            )
            if object.int("errno") == 0 {
                return
            }
            lastObject = object
            AppLog.warning("transfer_share_files attempt=\(attempt.name) retryable errno=\(object.int("errno")) request_id=\(object.string("request_id")) errmsg=\(object.string("errmsg"))")
        }

        if let lastObject {
            throw apiError(lastObject, context: "转存分享 /share/transfer")
        }
    }

    private func transferAttempts(
        decodedRandsk: String,
        originalRandsk: String,
        compactFSIDList: String,
        spacedFSIDList: String,
        surl: String
    ) -> [TransferAttempt] {
        let shareReferer = "https://pan.baidu.com/share/init?surl=\(surl)"
        let pageReferer = "https://pan.baidu.com/s/1\(surl)"
        let activeCookieBDCLND = originalRandsk.isEmpty ? decodedRandsk : originalRandsk
        var attempts = [
            TransferAttempt(name: "legacy", sekey: decodedRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: nil, includeBDSToken: true),
            TransferAttempt(name: "share_referer", sekey: decodedRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: shareReferer, includeBDSToken: true),
            TransferAttempt(name: "page_referer", sekey: decodedRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: pageReferer, includeBDSToken: true),
            TransferAttempt(name: "json_spaces", sekey: decodedRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: spacedFSIDList, referer: nil, includeBDSToken: true),
            TransferAttempt(name: "no_bdstoken", sekey: decodedRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: nil, includeBDSToken: false),
            TransferAttempt(name: "no_sekey", sekey: nil, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: nil, includeBDSToken: true)
        ]
        if originalRandsk != decodedRandsk {
            attempts.insert(
                TransferAttempt(name: "original_sekey", sekey: originalRandsk, cookieBDCLND: activeCookieBDCLND, fsidList: compactFSIDList, referer: nil, includeBDSToken: true),
                at: 1
            )
            attempts.append(
                TransferAttempt(name: "decoded_cookie", sekey: decodedRandsk, cookieBDCLND: decodedRandsk, fsidList: compactFSIDList, referer: nil, includeBDSToken: true)
            )
        }

        var seen = Set<String>()
        return attempts.filter { attempt in
            let key = "\(attempt.sekey ?? "")|\(attempt.cookieBDCLND ?? "")|\(attempt.fsidList)|\(attempt.referer ?? "")|\(attempt.includeBDSToken)"
            if seen.contains(key) {
                return false
            }
            seen.insert(key)
            return true
        }
    }

    private func verifyShare(surl: String, password: String) async throws -> [String: Any] {
        let query = [URLQueryItem(name: "surl", value: surl)]
        return try await postForm(path: "/share/verify", query: query, form: [
            ("pwd", password),
            ("vcode", ""),
            ("vcode_str", "")
        ], referer: "https://pan.baidu.com/share/init?surl=\(surl)", context: "验证分享提取码 /share/verify")
    }

    private func getSharePageInfo(surl: String) async throws -> SharePageInfo {
        let (data, _) = try await send(path: "/s/1\(surl)", acceptJSON: false)
        let text = String(decoding: data, as: UTF8.self)

        let shareID = [
            #""shareid"\s*:\s*["']?(\d+)"#,
            #"shareid\s*:\s*"(\d+)""#
        ].compactMap { text.firstMatch(pattern: $0) }.first ?? ""
        let uk = [
            #""share_uk"\s*:\s*"(\d+)""#,
            #"share_uk\s*:\s*"(\d+)""#,
            #""uk"\s*:\s*["']?(\d+)"#
        ].compactMap { text.firstMatch(pattern: $0) }.first ?? ""

        var files: [PanFile] = []
        if let json = text.firstMatch(pattern: #"locals\.mset\((\{.*?\})\)"#, options: [.dotMatchesLineSeparators]),
           let data = json.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            files = decodeShareFileList(from: object["file_list"])
        }
        if files.isEmpty,
           let json = text.firstMatch(pattern: #""file_list"\s*:\s*(\[.*?\])"#, options: [.dotMatchesLineSeparators]) {
            files = decodeShareFileList(fromJSONString: json)
        }

        return SharePageInfo(shareID: shareID, uk: uk, files: files)
    }

    private func fetchBDSToken() async throws {
        guard bdstoken.isEmpty else { return }
        let (data, _) = try await send(path: "/disk/home", acceptJSON: false)
        let text = String(decoding: data, as: UTF8.self)
        bdstoken = text.firstMatch(pattern: #""bdstoken"\s*:\s*"([a-f0-9]{32})""#) ?? ""
        AppLog.info("fetch_bdstoken success=\(!bdstoken.isEmpty)")
    }

    private func decodeFileList(path: String, query: [URLQueryItem]) async throws -> [PanFile] {
        let object = try await jsonObject(path: path, query: query, context: "读取列表 \(path)")
        if object.int("errno") != 0 {
            throw apiError(object, context: "读取列表 \(path)")
        }
        return decodeShareFileList(from: object["list"])
    }

    private func standardQuery() -> [URLQueryItem] {
        [
            URLQueryItem(name: "channel", value: "chunlei"),
            URLQueryItem(name: "web", value: "1"),
            URLQueryItem(name: "clienttype", value: "0")
        ]
    }

    private func jsonObject(path: String, query: [URLQueryItem], context: String) async throws -> [String: Any] {
        let (data, _) = try await send(path: path, query: query)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            AppLog.error("\(context) invalid_json bytes=\(data.count)")
            throw BaiduPanError.parse("接口返回的 JSON 无效")
        }
        logAPIObject(object, context: context)
        return object
    }

    private func logAPIObject(_ object: [String: Any], context: String, logNonZeroAsWarning: Bool = false) {
        guard object.keys.contains("errno") else {
            AppLog.info("\(context) response=no_errno")
            return
        }
        let errno = object.int("errno")
        let requestID = object.string("request_id")
        let message = object.string("errmsg")
        let levelPrefix = "\(context) errno=\(errno)"
        let suffix = " request_id=\(requestID.isEmpty ? "-" : requestID) errmsg=\(message.isEmpty ? "-" : message)"
        if errno == 0 {
            AppLog.info(levelPrefix + suffix)
        } else if logNonZeroAsWarning {
            AppLog.warning(levelPrefix + suffix)
        } else {
            AppLog.error(levelPrefix + suffix)
        }
    }

    private func apiError(_ object: [String: Any], context: String) -> BaiduPanError {
        let errno = object.int("errno")
        let message = object.string("errmsg")
        let requestID = object.string("request_id")
        let detail = message.isEmpty ? "API 错误：\(errno)" : "\(message)（errno=\(errno)）"
        let suffix = requestID.isEmpty ? "" : " request_id=\(requestID)"
        AppLog.error("\(context) failed errno=\(errno) errmsg=\(message.isEmpty ? "-" : message)\(suffix)")
        return .api(errno, "\(context)：\(detail)")
    }

    @discardableResult
    private func postForm(
        path: String,
        query: [URLQueryItem],
        form: [(String, String)],
        referer: String? = nil,
        cookieHeaderValue: String? = nil,
        extraHeaders: [String: String] = [:],
        context: String,
        logNonZeroAsWarning: Bool = false
    ) async throws -> [String: Any] {
        let body = form
            .map { key, value in
                "\(key.urlFormEncoded)=\(value.urlFormEncoded)"
            }
            .joined(separator: "&")
            .data(using: .utf8) ?? Data()

        let (data, _) = try await send(
            path: path,
            query: query,
            method: "POST",
            body: body,
            referer: referer,
            cookieHeaderValue: cookieHeaderValue,
            extraHeaders: extraHeaders,
            contentType: "application/x-www-form-urlencoded"
        )
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            AppLog.error("\(context) invalid_json bytes=\(data.count)")
            throw BaiduPanError.parse("接口返回的 JSON 无效")
        }
        logAPIObject(object, context: context, logNonZeroAsWarning: logNonZeroAsWarning)
        return object
    }

    private func send(
        path: String,
        query: [URLQueryItem] = [],
        method: String = "GET",
        body: Data? = nil,
        referer: String? = nil,
        cookieHeaderValue: String? = nil,
        extraHeaders: [String: String] = [:],
        contentType: String? = nil,
        acceptJSON: Bool = true
    ) async throws -> (Data, HTTPURLResponse) {
        guard var components = URLComponents(url: Self.base, resolvingAgainstBaseURL: false) else {
            throw BaiduPanError.invalidURL
        }
        components.path = path.hasPrefix("/") ? path : "/\(path)"
        components.percentEncodedQuery = query.isEmpty ? nil : formEncodedQuery(query)
        guard let url = components.url else {
            throw BaiduPanError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(referer ?? "https://pan.baidu.com/disk/home", forHTTPHeaderField: "Referer")
        request.setValue(cookieHeaderValue ?? cookieHeader(), forHTTPHeaderField: "Cookie")
        request.setValue(acceptJSON ? "application/json, text/plain, */*" : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", forHTTPHeaderField: "Accept")
        if let contentType {
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        for (key, value) in extraHeaders {
            request.setValue(value, forHTTPHeaderField: key)
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BaiduPanError.parse("HTTP 响应无效")
        }
        return (data, http)
    }

    private func formEncodedQuery(_ items: [URLQueryItem]) -> String {
        items
            .map { item in
                "\(item.name.urlFormEncoded)=\((item.value ?? "").urlFormEncoded)"
            }
            .joined(separator: "&")
    }

    private func requestAbsoluteURL(
        _ url: URL,
        headers: [String: String],
        followRedirects: Bool
    ) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(cookieHeader(), forHTTPHeaderField: "Cookie")
        for (key, value) in headers {
            request.setValue(value, forHTTPHeaderField: key)
        }

        let delegate = RedirectControlDelegate(followRedirects: followRedirects)
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 15
        configuration.httpCookieAcceptPolicy = .always
        let urlSession = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        defer { urlSession.finishTasksAndInvalidate() }

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BaiduPanError.parse("HTTP 响应无效")
        }
        return (data, http)
    }

    private func responseOnlyAbsoluteURL(
        _ url: URL,
        headers: [String: String],
        followRedirects: Bool
    ) async throws -> HTTPURLResponse {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(cookieHeader(), forHTTPHeaderField: "Cookie")
        for (key, value) in headers {
            request.setValue(value, forHTTPHeaderField: key)
        }

        let delegate = RedirectControlDelegate(followRedirects: followRedirects)
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 15
        configuration.httpCookieAcceptPolicy = .always
        let urlSession = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        defer { urlSession.invalidateAndCancel() }

        let (_, response) = try await urlSession.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BaiduPanError.parse("HTTP 响应无效")
        }
        return http
    }

    private func cookiePairs() -> [String: String] {
        cookieHeader()
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

    private func decodeShareFileList(from value: Any?) -> [PanFile] {
        if let object = value as? [String: Any] {
            return decodeShareFileList(from: object["list"])
        }
        guard let array = value as? [[String: Any]],
              let data = try? JSONSerialization.data(withJSONObject: array) else {
            return []
        }
        return (try? JSONDecoder().decode([PanFile].self, from: data)) ?? []
    }

    private func decodeShareFileList(fromJSONString json: String) -> [PanFile] {
        guard let data = json.data(using: .utf8),
              let array = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            return []
        }
        return decodeShareFileList(from: array)
    }
}

struct SharePageInfo {
    let shareID: String
    let uk: String
    let files: [PanFile]
}

struct ShareListResult {
    let surl: String
    let shareID: String
    let uk: String
    let randsk: String
    let files: [PanFile]
}

private struct CDNResolveResult {
    let url: String
    let isCDN: Bool
    let isLocate: Bool
}

private struct TransferAttempt {
    let name: String
    let sekey: String?
    let cookieBDCLND: String?
    let fsidList: String
    let referer: String?
    let includeBDSToken: Bool
}

private final class RedirectControlDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let followRedirects: Bool

    init(followRedirects: Bool) {
        self.followRedirects = followRedirects
    }

    nonisolated func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(followRedirects ? request : nil)
    }
}

private extension String {
    func firstMatch(
        pattern: String,
        options: NSRegularExpression.Options = []
    ) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: options) else {
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

    var urlFormEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .quotePlusAllowed)?
            .replacingOccurrences(of: "%20", with: "+") ?? self
    }

    var urlQueryPlusEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .quotePlusAllowed)?
            .replacingOccurrences(of: "%20", with: "+") ?? self
    }

    var pcsPathEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .pcsPathAllowed) ?? self
    }

    var percentDecodedRepeatedly: String {
        var current = self
        for _ in 0..<3 {
            guard let decoded = current.removingPercentEncoding, decoded != current else {
                return current
            }
            current = decoded
        }
        return current
    }

    var sha1Hex: String {
        Insecure.SHA1.hash(data: Data(utf8)).map { String(format: "%02x", $0) }.joined()
    }

    var md5Hex: String {
        Insecure.MD5.hash(data: Data(utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

private extension CharacterSet {
    static let pcsPathAllowed: CharacterSet = {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "?#[]@!$&'()*+,;=")
        return allowed
    }()

    static let quotePlusAllowed: CharacterSet = {
        CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
    }()
}

private extension Dictionary where Key == String, Value == Any {
    func int(_ key: String) -> Int {
        Int(int64(key))
    }

    func int64(_ key: String) -> Int64 {
        if let number = self[key] as? NSNumber {
            return number.int64Value
        }
        if let number = self[key] as? Int64 {
            return number
        }
        if let string = self[key] as? String, let number = Int64(string) {
            return number
        }
        return 0
    }

    func string(_ key: String) -> String {
        if let string = self[key] as? String {
            return string
        }
        if let number = self[key] as? NSNumber {
            return number.stringValue
        }
        return ""
    }

    func array(_ key: String) -> [[String: Any]] {
        self[key] as? [[String: Any]] ?? []
    }
}
