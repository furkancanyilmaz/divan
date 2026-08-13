import XCTest
@testable import DivanNative

/// Yaşantısal çalışmaların klinik yoğunluk eşiği.
///
/// Bu kural daha önce iki ayrı View'da elle yazılıydı ve imgelem yolu
/// sunucunun bildirdiği `intensityLimit` değerini hiç dikkate almıyordu:
/// sunucu sınırı 6 iken kullanıcı 7 yoğunlukta imgelemeye dönebiliyor,
/// aynı durumda sandalye çalışmasına dönemiyordu. Bu testler iki yolun
/// aynı sözleşmeye uymasını korur.
final class WorkspaceSafetyTests: XCTestCase {

    func testResumeIsBlockedAtOrAboveCeiling() {
        XCTAssertTrue(WorkspaceSafety.intensityBlocksResume(
            intensity: 8, limit: 10))
        XCTAssertTrue(WorkspaceSafety.intensityBlocksResume(
            intensity: 9, limit: 10))
        XCTAssertFalse(WorkspaceSafety.intensityBlocksResume(
            intensity: 7, limit: 10))
    }

    func testServerLimitIsHonouredBelowCeiling() {
        // Sunucu sınırı tavandan düşükse, tavan değil sunucu sınırı geçerlidir.
        XCTAssertTrue(WorkspaceSafety.intensityBlocksResume(
            intensity: 7, limit: 6))
        XCTAssertFalse(WorkspaceSafety.intensityBlocksResume(
            intensity: 6, limit: 6))
    }

    func testChairAndImageryShareTheSameContract() {
        // Aynı yoğunluk ve aynı sınır, iki yolda aynı sonucu vermelidir.
        for intensity in 1...10 {
            for limit in 1...10 {
                let chair = WorkspaceChairSession.probe(
                    intensity: intensity, limit: limit)
                let imagery = WorkspaceImagerySession.probe(
                    intensity: intensity, limit: limit)
                XCTAssertEqual(
                    chair.intensityBlocksResume,
                    imagery.intensityBlocksResume,
                    "Yoğunluk \(intensity), sınır \(limit): sandalye ve imgelem farklı karar verdi."
                )
            }
        }
    }
}

private extension WorkspaceChairSession {
    static func probe(intensity: Int, limit: Int) -> WorkspaceChairSession {
        WorkspaceChairSession(
            id: "probe", title: "", frame: "", goalText: "", stopSignal: "",
            participants: [], minimumParticipants: 2, maximumParticipants: 4,
            allowsAddingParticipants: false, orientationConfirmed: true,
            frameConfirmed: true, stages: [], currentStageID: "",
            currentStageIndex: 0, activeChairID: "", turns: [], guidance: [],
            phase: .active, intensity: intensity, intensityLimit: limit,
            updatedAt: Date()
        )
    }
}

private extension WorkspaceImagerySession {
    static func probe(intensity: Int, limit: Int) -> WorkspaceImagerySession {
        WorkspaceImagerySession(
            id: "probe", phase: .active, title: "", frame: "",
            stages: [], currentStageID: "", currentStageIndex: 0,
            checkpoint: WorkspaceImageryCheckpoint(
                id: "cp", stageID: "", title: "", prompt: "",
                safetyNote: "", choices: [], isConfirmed: false
            ),
            sceneBoundary: "", stopSignal: "",
            orientationConfirmed: true, frameConfirmed: true,
            realityConfirmed: true, intensity: intensity,
            intensityLimit: limit, updatedAt: Date()
        )
    }
}
