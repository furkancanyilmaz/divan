import Foundation
import XCTest
@testable import DivanNative

final class ModelsTests: XCTestCase {
    func testJSONValueRoundTripPreservesCapabilityDocument() throws {
        let value: JSONValue = .object([
            "enabled": .bool(true),
            "version": .number(2),
            "labels": .array([.string("bir"), .string("iki")]),
            "missing": .null,
        ])
        let encoded = try JSONEncoder().encode(value)
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: encoded), value)
    }

    func testChatTerminalStatesAreExplicit() {
        func status(_ value: String) -> ChatRequestStatus {
            ChatRequestStatus(
                requestID: "native-123456789012",
                conversationID: 1,
                status: value,
                retryable: false,
                userMessageID: 1,
                assistantMessageID: nil,
                replyTo: nil,
                provider: "openai",
                model: "model",
                content: "",
                errorCode: "",
                attempt: 1,
                maxAttempts: 4,
                automaticRetry: false,
                pending: value == "running",
                waitingForProvider: false,
                nextRetryAt: nil
            )
        }
        XCTAssertFalse(status("running").isTerminal)
        XCTAssertTrue(status("completed").isTerminal)
        XCTAssertTrue(status("failed").isTerminal)
        XCTAssertTrue(status("interrupted").isTerminal)
        XCTAssertTrue(status("cancelled").isTerminal)
    }

    func testPublicModelsRemainCodableForSwiftUIStateRestoration() throws {
        let master = MasterSummary(
            id: "freud",
            name: "Sigmund Freud",
            school: "Psikanaliz",
            subtitle: "Wien · 1856–1939",
            portraitURL: URL(string: "http://127.0.0.1:1234/assets/portraits/freud.jpg"),
            kind: .therapist,
            isLiving: false,
            supportedModes: ["terapi", "ders"]
        )
        let data = try JSONEncoder().encode(master)
        XCTAssertEqual(try JSONDecoder().decode(MasterSummary.self, from: data), master)
    }
}
