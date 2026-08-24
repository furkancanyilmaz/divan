import Foundation

/// Authenticated loopback adapter for the native structured workspaces.
public actor CoreStructuredTherapyDataSource: StructuredTherapyDataSource {
    private let loader: DivanRuntimeLoader

    public init(loader: DivanRuntimeLoader) {
        self.loader = loader
    }

    public func freudImagery(
        conversationID: Int
    ) async throws -> FreudImageryWorkspace {
        let (client, _) = try await loader.service()
        return try await client.freudImagery(conversationID: conversationID)
    }

    public func mutateFreudImagerySelection(
        _ mutation: FreudImagerySelectionMutation
    ) async throws -> FreudImageryMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateFreudImagerySelection(mutation)
    }

    public func suggestFreudImagery(
        _ mutation: FreudImagerySuggestionMutation
    ) async throws -> FreudImageryMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.suggestFreudImagery(mutation)
    }

    public func freudImageryCardData(
        card: FreudImageryCard
    ) async throws -> Data {
        let (client, _) = try await loader.service()
        return try await client.freudImageryCardData(card: card)
    }

    public func adhdDashboard(
        conversationID: Int
    ) async throws -> ADHDWorkspaceSnapshot {
        let (client, _) = try await loader.service()
        return try await client.adhdDashboard(conversationID: conversationID)
    }

    public func mutateADHDHabit(
        _ mutation: ADHDHabitMutation
    ) async throws -> ADHDHabitMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateADHDHabit(mutation)
    }

    public func mutateADHDEvent(
        _ mutation: ADHDEventMutation
    ) async throws -> ADHDEventMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateADHDEvent(mutation)
    }

    public func mutateADHDJournal(
        _ mutation: ADHDJournalMutation
    ) async throws -> ADHDJournalMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateADHDJournal(mutation)
    }

    public func adhdTUSPlanner(
        conversationID: Int,
        query: String? = nil
    ) async throws -> ADHDTUSPlannerSnapshot {
        let (client, _) = try await loader.service()
        return try await client.adhdTUSPlanner(
            conversationID: conversationID,
            query: query
        )
    }

    public func mutateADHDTUS(
        _ mutation: ADHDTUSMutation
    ) async throws -> ADHDTUSPlannerSnapshot {
        let (client, _) = try await loader.service()
        return try await client.mutateADHDTUS(mutation)
    }

    public func schemaPath(
        conversationID: Int
    ) async throws -> SchemaPathSnapshot {
        let (client, _) = try await loader.service()
        return try await client.schemaPath(conversationID: conversationID)
    }

    public func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaPath(mutation)
    }

    public func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaTurnAnalysis(mutation)
    }
}
