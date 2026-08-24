import Foundation

/// A bounded, typed representation of JSON used for forward-compatible
/// capability documents. Clinical/user content should use explicit DTOs.
public enum JSONValue: Codable, Equatable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Desteklenmeyen JSON değeri."
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    public func hash(into hasher: inout Hasher) {
        switch self {
        case .string(let value):
            hasher.combine(0)
            hasher.combine(value)
        case .number(let value):
            hasher.combine(1)
            hasher.combine(value)
        case .bool(let value):
            hasher.combine(2)
            hasher.combine(value)
        case .object(let value):
            hasher.combine(3)
            for key in value.keys.sorted() {
                hasher.combine(key)
                hasher.combine(value[key])
            }
        case .array(let value):
            hasher.combine(4)
            hasher.combine(value)
        case .null:
            hasher.combine(5)
        }
    }
}
