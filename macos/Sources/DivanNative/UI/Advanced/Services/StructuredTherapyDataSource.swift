import Foundation

/// UI boundary for the user-owned ADHD and Schema Therapy workspaces.
///
/// Implementations must forward the user's explicit privacy, consent and
/// safety answers without filling missing answers on their behalf.
public protocol StructuredTherapyDataSource: Sendable {
    func freudImagery(conversationID: Int) async throws -> FreudImageryWorkspace
    func mutateFreudImagerySelection(
        _ mutation: FreudImagerySelectionMutation
    ) async throws -> FreudImageryMutationResponse
    func suggestFreudImagery(
        _ mutation: FreudImagerySuggestionMutation
    ) async throws -> FreudImageryMutationResponse
    func freudImageryCardData(card: FreudImageryCard) async throws -> Data

    func adhdDashboard(conversationID: Int) async throws -> ADHDWorkspaceSnapshot
    func mutateADHDHabit(
        _ mutation: ADHDHabitMutation
    ) async throws -> ADHDHabitMutationResponse
    func mutateADHDEvent(
        _ mutation: ADHDEventMutation
    ) async throws -> ADHDEventMutationResponse
    func mutateADHDJournal(
        _ mutation: ADHDJournalMutation
    ) async throws -> ADHDJournalMutationResponse
    func adhdTUSPlanner(
        conversationID: Int,
        query: String?
    ) async throws -> ADHDTUSPlannerSnapshot
    func mutateADHDTUS(
        _ mutation: ADHDTUSMutation
    ) async throws -> ADHDTUSPlannerSnapshot

    func schemaPath(conversationID: Int) async throws -> SchemaPathSnapshot
    func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse
    func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse
}

public extension StructuredTherapyDataSource {
    func adhdTUSPlanner(
        conversationID: Int,
        query: String? = nil
    ) async throws -> ADHDTUSPlannerSnapshot {
        throw DivanUIClientError("TUS çalışma planlayıcısı bu veri kaynağında desteklenmiyor.")
    }

    func mutateADHDTUS(
        _ mutation: ADHDTUSMutation
    ) async throws -> ADHDTUSPlannerSnapshot {
        throw DivanUIClientError("TUS çalışma planlayıcısı bu veri kaynağında desteklenmiyor.")
    }

    func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        throw DivanUIClientError(
            "Tamamlanmış mesaj çifti incelemesi bu veri kaynağında desteklenmiyor."
        )
    }
}
