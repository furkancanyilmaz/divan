import Foundation

public struct DivanAPIError: LocalizedError, Equatable, Sendable {
    public let message: String
    public let statusCode: Int?
    public let errorCode: String?
    public let errorID: String?
    public let retryable: Bool

    public init(
        message: String,
        statusCode: Int? = nil,
        errorCode: String? = nil,
        errorID: String? = nil,
        retryable: Bool = false
    ) {
        self.message = message
        self.statusCode = statusCode
        self.errorCode = errorCode
        self.errorID = errorID
        self.retryable = retryable
    }

    public var errorDescription: String? { message }

    public static let invalidEndpoint = DivanAPIError(
        message: "Divan yalnızca bu Mac'teki güvenli yerel bağlantıya erişebilir.",
        errorCode: "invalid_endpoint"
    )
}

struct ErrorEnvelope: Decodable {
    let error: String?
    /// Experiential guidance endpoints historically use `code`, while newer
    /// endpoints use `error_code`.
    let code: String?
    let errorCode: String?
    let errorId: String?
    let retryable: Bool?
}
