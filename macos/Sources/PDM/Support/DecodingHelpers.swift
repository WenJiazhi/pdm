import Foundation

extension KeyedDecodingContainer {
    func decodeLossyInt64(forKey key: Key) -> Int64 {
        if let value = try? decode(Int64.self, forKey: key) {
            return value
        }
        if let value = try? decode(Int.self, forKey: key) {
            return Int64(value)
        }
        if let value = try? decode(String.self, forKey: key), let number = Int64(value) {
            return number
        }
        return 0
    }
}
