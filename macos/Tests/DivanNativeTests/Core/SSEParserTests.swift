import XCTest
@testable import DivanNative

final class SSEParserTests: XCTestCase {
    func testCombinesDataLinesAndFlushesOnBlankLine() throws {
        var parser = SSEParser()
        XCTAssertNil(parser.consume(line: "data: {\"type\":\"delta\","))
        XCTAssertNil(parser.consume(line: "data: \"text\":\"merhaba\"}"))
        let data = try XCTUnwrap(parser.consume(line: ""))
        XCTAssertEqual(
            String(decoding: data, as: UTF8.self),
            "{\"type\":\"delta\",\n\"text\":\"merhaba\"}"
        )
    }

    func testIgnoresCommentsAndUnknownFields() {
        var parser = SSEParser()
        XCTAssertNil(parser.consume(line: ": keep alive"))
        XCTAssertNil(parser.consume(line: "event: message"))
        XCTAssertNil(parser.finish())
    }

    func testFinishReturnsUnterminatedEvent() throws {
        var parser = SSEParser()
        XCTAssertNil(parser.consume(line: "data: final"))
        let data = try XCTUnwrap(parser.finish())
        XCTAssertEqual(String(decoding: data, as: UTF8.self), "final")
        XCTAssertNil(parser.finish())
    }
}
