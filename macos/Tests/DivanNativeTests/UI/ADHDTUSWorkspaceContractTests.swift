import Foundation
import XCTest
@testable import DivanNative

final class ADHDTUSWorkspaceContractTests: XCTestCase {
    func testFourthTabLoadsOnlyTheServerOwnedTUSPlanner() throws {
        let source = try workspaceSource()

        XCTAssertTrue(source.contains("case today, routines, notebook, tus"))
        XCTAssertTrue(source.contains("case .tus: \"TUS Çalışma\""))
        XCTAssertTrue(source.contains("if selectedTab == .tus { await model.loadTUSIfNeeded() }"))
        XCTAssertTrue(source.contains("case .tus: tusView"))
        XCTAssertTrue(source.contains("accessibilityIdentifier(\"adhd.tus.mode\")"))
        XCTAssertTrue(source.contains("accessibilityIdentifier(\"adhd.tus.question\")"))
        XCTAssertTrue(source.contains("accessibilityIdentifier(\"adhd.tus.plan\")"))
        XCTAssertTrue(source.contains("model.isBusy || model.tusIsBusy"))
    }

    func testOneQuestionConversationAndFilterAreVisibleWithoutLocalDraftState() throws {
        let source = try workspaceSource()

        XCTAssertTrue(source.contains("tusHistory(tus.history)"))
        XCTAssertTrue(source.contains("if let question = tus.question"))
        XCTAssertTrue(source.contains("Text(question.prompt)"))
        XCTAssertTrue(source.contains("TextField(\"Konu veya kaynak ara\""))
        XCTAssertTrue(source.contains("Task { await model.searchTUSAreas() }"))
        XCTAssertTrue(source.contains("ForEach(question.options)"))
        XCTAssertTrue(source.contains("questionCount = tus.catalog.questionCount"))
        XCTAssertTrue(source.contains("sentenceCount = tus.catalog.sentenceCount"))
        XCTAssertTrue(source.contains("(!tus.enabled"))
        XCTAssertTrue(source.contains("tus.safetyHold || !tus.catalog.available"))
        XCTAssertFalse(source.contains("UserDefaults"))
        XCTAssertFalse(source.contains("raw_question"))
        XCTAssertFalse(source.contains("sentence_text"))
    }

    func testOnlyCurrentStepIsExpandedAndFinishedPlanCreatesNoDebtList() throws {
        let source = try workspaceSource()

        XCTAssertTrue(source.contains("if let step = plan.currentStep"))
        XCTAssertTrue(source.contains("accessibilityIdentifier(\"adhd.tus.current-step\")"))
        XCTAssertTrue(source.contains("DisclosureGroup(\"Sonraki adımlar"))
        XCTAssertTrue(source.contains("let future = plan.status == \"finished\" ? []"))
        XCTAssertTrue(source.contains("!$0.visible && $0.status == \"pending\""))
        XCTAssertTrue(source.contains("Yarım kalan adımlar yarına borç değil."))
        XCTAssertFalse(source.contains("details.open"))
    }

    func testTypedWireHasNoRawQuestionOrSentenceContentProperties() throws {
        let source = try modelSource()
        let start = try XCTUnwrap(source.range(of: "// MARK: - ADHD TUS study planner"))
        let end = try XCTUnwrap(source.range(
            of: "// MARK: - User-owned Schema Therapy path",
            range: start.upperBound..<source.endIndex
        ))
        let tus = String(source[start.lowerBound..<end.lowerBound])

        for forbidden in [
            "public let rawQuestion", "public let rawSentence",
            "public let questionText", "public let sentenceText",
            "public let choices", "public let answerKey",
            "public let explanation", "public let solution",
        ] {
            XCTAssertFalse(tus.contains(forbidden), "Forbidden TUS wire field: \(forbidden)")
        }
        XCTAssertTrue(tus.contains("public let questionCount: Int?"))
        XCTAssertTrue(tus.contains("public let tusDefaultQuestionCount: Int?"))
        XCTAssertTrue(tus.contains("public let sentenceCount: Int?"))
        XCTAssertTrue(tus.contains("public let readingArea: ADHDTUSStudyArea?"))
        XCTAssertTrue(tus.contains("public let questionArea: ADHDTUSStudyArea?"))
    }

    func testLongSessionContractAcceptsTwentyBoundedCollapsedSteps() {
        var steps: [ADHDTUSStep] = []
        for index in 0..<20 {
            let identifier = String(format: "%032x", index + 2)
            let title = "Küçük soru bloğu \(index + 1)"
            steps.append(ADHDTUSStep(
                id: identifier,
                title: title,
                detail: "Yalnız seçilen alandaki adet bilgisi.",
                kind: "questions",
                durationMinutes: 9,
                quantity: 3,
                unit: "soru",
                status: index == 0 ? "active" : "pending",
                visible: index == 0,
                collapsed: index != 0
            ))
        }
        let plan = ADHDTUSPlan(
            id: String(repeating: "f", count: 32),
            title: "180 dakikalık uzun tur",
            summary: "Yirmi küçük ve tekrar edebilir çalışma adımı.",
            status: "active",
            activity: "questions",
            lesson: ADHDTUSCatalogChoice(key: "farmakoloji", name: "Farmakoloji"),
            readingArea: nil,
            questionArea: ADHDTUSStudyArea(
                key: "farma-soru",
                name: "Otonom sinir sistemi",
                source: "TümTUS",
                availableCount: 240,
                unit: "soru"
            ),
            availableMinutes: 180,
            startFriction: "normal",
            progress: ADHDTUSProgress(completed: 0, total: 20),
            currentStep: steps[0],
            steps: steps
        )

        XCTAssertTrue(plan.contractIsSupported(for: "active"))
        XCTAssertEqual(plan.steps.filter { $0.visible }.count, 1)
        XCTAssertEqual(plan.steps.filter { !$0.visible }.count, 19)
        XCTAssertTrue(plan.steps.dropFirst().allSatisfy { $0.collapsed })
    }

    private func workspaceSource() throws -> String {
        try String(contentsOf: packageRoot()
            .appendingPathComponent(
                "Sources/DivanNative/UI/Advanced/Views/StructuredTherapyWorkspaceView.swift"
            ), encoding: .utf8)
    }

    private func modelSource() throws -> String {
        try String(contentsOf: packageRoot()
            .appendingPathComponent(
                "Sources/DivanNative/Core/StructuredTherapyModels.swift"
            ), encoding: .utf8)
    }

    private func packageRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }
}
