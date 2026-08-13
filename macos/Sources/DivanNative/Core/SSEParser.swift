import Foundation

struct SSEParser: Sendable {
    private var dataLines: [String] = []

    mutating func consume(line: String) -> Data? {
        if line.isEmpty {
            return flush()
        }
        if line.hasPrefix(":" ) {
            return nil
        }
        guard line.hasPrefix("data:") else { return nil }
        var value = String(line.dropFirst(5))
        if value.first == " " { value.removeFirst() }
        dataLines.append(value)
        return nil
    }

    mutating func finish() -> Data? { flush() }

    private mutating func flush() -> Data? {
        guard !dataLines.isEmpty else { return nil }
        let payload = dataLines.joined(separator: "\n")
        dataLines.removeAll(keepingCapacity: true)
        return payload.data(using: .utf8)
    }
}
