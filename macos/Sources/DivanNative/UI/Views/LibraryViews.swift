import SwiftUI

// Divan'ın "defter" ekranları: Hakkımda, Defter (notlar + formülasyonlar),
// Mektuplar, Rüya defteri ve tüm konuşmalarda arama.
//
// Hepsi salt okunur birikimlerdir; Hakkımda tek istisnadır ve kullanıcı
// tarafından düzenlenir. Bu görünümler klinik karar üretmez.

// MARK: - Hakkımda

struct ProfileView: View {
    @ObservedObject var model: DivanViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            AdvancedSectionHeader(
                title: "Hakkımda",
                detail: "Buraya yazdıklarınızı her usta, her görüşmede bilir.",
                systemImage: "person.text.rectangle",
                showsDetail: true
            )
            TextEditor(text: $model.profileText)
                .font(.body)
                .frame(minHeight: 200)
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color(nsColor: .separatorColor))
                }
                .accessibilityLabel("Hakkımda metni")
            HStack {
                Text("Örneğin: adınız, mesleğiniz, üzerinde çalıştığınız konu.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if model.isProfileBusy { ProgressView().controlSize(.small) }
                Button("Kaydet") { Task { await model.saveProfile() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isProfileBusy)
            }
            Spacer()
        }
        .padding(20)
        .frame(maxWidth: 760, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task { await model.loadProfile() }
        .accessibilityIdentifier("divan.profile")
    }
}

// MARK: - Defter (notlar + formülasyonlar)

struct NotebookView: View {
    @ObservedObject var model: DivanViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let book = model.notebook, !book.isEmpty {
                    if !book.formulations.isEmpty {
                        LibrarySection(title: "Formülasyonlar",
                                       systemImage: "star.circle") {
                            ForEach(book.formulations) { item in
                                LibraryCard(
                                    heading: "\(item.createdAt) · \(item.noteCount) not",
                                    text: item.content,
                                    emphasised: true
                                )
                            }
                        }
                    }
                    LibrarySection(title: "Seans notları",
                                   systemImage: "note.text") {
                        ForEach(book.notes) { note in
                            LibraryCard(
                                heading: "\(note.createdAt) · \(note.conversationTitle)",
                                text: note.content
                            )
                        }
                    }
                } else {
                    DivanEmptyState(
                        systemImage: "note.text",
                        title: "Defter boş",
                        message: "Bir görüşmeyi bitirdiğinizde usta kendi notunu buraya yazar."
                    )
                }
            }
            .padding(20)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .task { await model.loadNotebook() }
        .accessibilityIdentifier("divan.notebook")
    }
}

// MARK: - Mektuplar

struct LettersView: View {
    @ObservedObject var model: DivanViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let box = model.letters, !box.isEmpty {
                    if !box.letters.isEmpty {
                        LibrarySection(title: "Veda mektupları",
                                       systemImage: "envelope") {
                            ForEach(box.letters) { letter in
                                LibraryCard(
                                    heading: "\(letter.createdAt) · \(letter.conversationTitle)",
                                    text: letter.content,
                                    emphasised: true
                                )
                            }
                        }
                    }
                    if !box.referrals.isEmpty {
                        LibrarySection(title: "Sevk mektupları",
                                       systemImage: "arrow.left.arrow.right") {
                            ForEach(box.referrals) { referral in
                                LibraryCard(
                                    heading: referralHeading(referral),
                                    text: referral.content
                                )
                            }
                        }
                    }
                } else {
                    DivanEmptyState(
                        systemImage: "envelope",
                        title: "Mektup yok",
                        message: "Bir terapi seansını bitirdiğinizde usta size kısa bir mektup yazar."
                    )
                }
            }
            .padding(20)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .task { await model.loadLetters() }
        .accessibilityIdentifier("divan.letters")
    }

    private func referralHeading(_ referral: LibraryReferral) -> String {
        let from = model.master(id: referral.fromMasterID)?.name
            ?? referral.fromMasterID
        let to = model.master(id: referral.toMasterID)?.name
            ?? referral.toMasterID
        return "\(referral.createdAt) · \(from) → \(to)"
    }
}

// MARK: - Rüya defteri

struct DreamJournalView: View {
    @ObservedObject var model: DivanViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                let journal = model.dreamJournal
                if let analysis = journal?.analysis, !analysis.isEmpty {
                    LibrarySection(title: "Motif yorumu",
                                   systemImage: "sparkles") {
                        LibraryCard(heading: "", text: analysis,
                                    emphasised: true)
                    }
                }
                if let dreams = journal?.dreams, !dreams.isEmpty {
                    LibrarySection(title: "Rüyalar", systemImage: "moon.stars") {
                        ForEach(dreams) { dream in
                            LibraryCard(
                                heading: "\(dream.createdAt) · \(dream.conversationTitle)",
                                text: dream.text
                            )
                        }
                    }
                    HStack {
                        Spacer()
                        if model.isDreamAnalysisBusy {
                            ProgressView().controlSize(.small)
                        }
                        Button("Motifleri yorumlat") {
                            Task { await model.analyzeDreams() }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isDreamAnalysisBusy)
                    }
                } else {
                    DivanEmptyState(
                        systemImage: "moon.stars",
                        title: "Rüya defteri boş",
                        message: "Terapi seansında bir rüya anlattığınızda burada birikir."
                    )
                }
            }
            .padding(20)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .task { await model.loadDreamJournal() }
        .accessibilityIdentifier("divan.dreams")
    }
}

// MARK: - Arama sonuçları

struct LibrarySearchResultsView: View {
    @ObservedObject var model: DivanViewModel

    var body: some View {
        List(model.searchHits) { hit in
            Button {
                Task { await openConversation(hit.conversationID) }
            } label: {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 6) {
                        Text(model.master(id: hit.masterID)?.name ?? hit.masterID)
                            .font(.subheadline.weight(.semibold))
                        if hit.isNote {
                            Text("not")
                                .font(.caption2.weight(.semibold))
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(.quaternary, in: Capsule())
                        }
                        Spacer()
                        Text(hit.createdAt)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text(hit.snippet)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                .padding(.vertical, 4)
            }
            .buttonStyle(.plain)
        }
        .overlay {
            if model.searchHits.isEmpty && !model.isSearching {
                DivanEmptyState(
                    systemImage: "magnifyingglass",
                    title: "Sonuç yok",
                    message: "Başka bir kelime deneyin."
                )
            }
        }
        .accessibilityIdentifier("divan.searchResults")
    }

    private func openConversation(_ id: Int) async {
        guard let conversation = (model.activeConversations
            + model.archivedConversations).first(where: { $0.id == id })
        else { return }
        await model.openConversation(conversation)
    }
}

// MARK: - Ortak bileşenler

private struct LibrarySection<Content: View>: View {
    let title: String
    let systemImage: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.headline)
                .foregroundStyle(DivanPalette.wine)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct LibraryCard: View {
    let heading: String
    let text: String
    var emphasised = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !heading.isEmpty {
                Text(heading)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(text)
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .padding(13)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            emphasised
                ? AnyShapeStyle(DivanPalette.gold.opacity(0.10))
                : AnyShapeStyle(.quaternary),
            in: RoundedRectangle(cornerRadius: 9)
        )
    }
}
