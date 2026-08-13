import SwiftUI

public struct ProviderSettingsView: View {
    @ObservedObject private var model: DivanViewModel

    public init(model: DivanViewModel) {
        self.model = model
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Sağlayıcı ve ayarlar")
                        .font(.title2.weight(.semibold))
                    Text("Bu ayarlar Divan’ın bu Mac’e özel güvenli veri alanına kaydedilir.")
                        .foregroundStyle(.secondary)
                    NativePreviewScopeBadge()
                }

                if let settings = model.settings {
                    settingsSummary(settings)
                } else {
                    HStack(spacing: 9) {
                        ProgressView().controlSize(.small)
                        Text("Sağlayıcı ayarları yükleniyor…")
                    }
                    .foregroundStyle(.secondary)
                }

                GroupBox("Görünüm") {
                    VStack(alignment: .leading, spacing: 14) {
                        Picker("Renk görünümü", selection: $model.appearancePreference) {
                            ForEach(DivanAppearancePreference.allCases) { preference in
                                Text(preference.title).tag(preference)
                            }
                        }
                        Picker("Yazı boyutu", selection: $model.textSizePreference) {
                            ForEach(DivanTextSizePreference.allCases) { preference in
                                Text(preference.title).tag(preference)
                            }
                        }

                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: "textformat.size")
                                .foregroundStyle(DivanPalette.wine)
                                .accessibilityHidden(true)
                            Text("Mesajlar bu boyutta görünecek.")
                            Spacer(minLength: 4)
                            Text("%\(Int(model.textSizePreference.scale * 100))")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 9))

                        Toggle(isOn: $model.keepsWindowOnTop) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Pencereyi hep üstte tut")
                                Text("Divan diğer uygulamaların üstünde kalır; sohbet açıkken başka bir işle uğraşabilirsiniz. Araç çubuğundaki raptiye ile de açıp kapatabilirsiniz (⇧⌘T).")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .toggleStyle(.switch)
                        .accessibilityIdentifier("divan.settings.keepsWindowOnTop")

                        Text("Görünüm tercihleri hemen uygulanır ve yalnız bu Mac’te saklanır; sağlayıcı veya API anahtarı ayarlarına gönderilmez.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, 6)
                }

                GroupBox("Sohbet sağlayıcısı") {
                    VStack(alignment: .leading, spacing: 14) {
                        Picker("Sağlayıcı", selection: $model.settingsProvider) {
                            ForEach(DivanProviderID.allCases) { provider in
                                Text(provider.title).tag(provider)
                            }
                        }
                        TextField("Model", text: $model.settingsModel)
                            .accessibilityLabel("Model adı")
                        if model.settingsProvider == .lmStudio {
                            TextField("LM Studio adresi", text: $model.settingsBaseURL)
                                .accessibilityLabel("LM Studio API adresi")
                                .help("Örnek: http://127.0.0.1:1234/v1")
                            Text("LM Studio’yu bu Mac’te başlatın ve modeli yükleyin.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            SecureField("Yeni API anahtarı", text: $model.settingsNewAPIKey)
                                .accessibilityLabel("Yeni \(model.settingsProvider.title) API anahtarı")
                            Text("Kayıtlı anahtar geri okunmaz veya ekranda gösterilmez. Boş bırakırsanız mevcut anahtar korunur.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.top, 6)

                    ViewThatFits(in: .horizontal) {
                        HStack {
                            storedKeyControls
                            Spacer()
                            saveSettingsButton
                        }
                        VStack(alignment: .leading, spacing: 9) {
                            storedKeyControls
                            saveSettingsButton
                        }
                    }
                    .padding(.top, 10)
                }

                if !model.settingsMessage.isEmpty {
                    Text(model.settingsMessage)
                        .font(.callout)
                        .foregroundStyle(settingsMessageColor)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                        .textSelection(.enabled)
                        .accessibilityLabel(model.settingsMessage)
                }

                GroupBox("Gizlilik sınırı") {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Anahtarlar yalnız güvenli ayar isteğiyle yazılır.", systemImage: "lock.shield")
                        Label("Arayüz hiçbir API anahtarını geri okumaz.", systemImage: "eye.slash")
                        Label("Bu kurulum başka Divan veri tabanlarını kendiliğinden açmaz.", systemImage: "externaldrive.badge.plus")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .font(.callout)
                }
            }
            .padding(22)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await model.refreshSettings() }
                } label: {
                    Label("Ayarları yenile", systemImage: "arrow.clockwise")
                }
            }
        }
    }

    @ViewBuilder
    private var storedKeyControls: some View {
        if currentChoiceHasStoredKey {
            Label("API anahtarı kayıtlı", systemImage: "key.fill")
                .font(.callout)
                .foregroundStyle(.secondary)
            Button("Kayıtlı anahtarı kaldır", role: .destructive) {
                Task { await model.clearCurrentProviderAPIKey() }
            }
            .disabled(model.isSavingSettings)
        }
    }

    private var saveSettingsButton: some View {
        Button {
            Task { await model.saveSettings() }
        } label: {
            if model.isSavingSettings {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("Kaydediliyor…")
                }
            } else {
                Text("Ayarları kaydet")
            }
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .keyboardShortcut("s", modifiers: [.command])
        .disabled(model.isSavingSettings)
    }

    private func settingsSummary(_ settings: DivanSettingsSummary) -> some View {
        GroupBox("Etkin bağlantı") {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    settingsIdentity(settings)
                    Spacer()
                    settingsStateBadge(settings)
                }
                VStack(alignment: .leading, spacing: 9) {
                    settingsIdentity(settings)
                    settingsStateBadge(settings)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
        }
    }

    private func settingsIdentity(_ settings: DivanSettingsSummary) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: providerStateIcon(settings.state))
                .font(.title2)
                .foregroundStyle(providerStateColor(settings.state))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(settings.providerName).font(.headline)
                Text(settings.modelName)
                    .font(.callout.monospaced())
                    .textSelection(.enabled)
                Text(settings.connectionDetail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
    }

    private func settingsStateBadge(_ settings: DivanSettingsSummary) -> some View {
        Text(settings.state == .ready ? "Hazır" : "Eylem gerekli")
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(providerStateColor(settings.state).opacity(0.14), in: Capsule())
    }

    private var currentChoiceHasStoredKey: Bool {
        model.settings?.provider == model.settingsProvider &&
            model.settings?.apiKeyStored == true
    }

    private var settingsMessageColor: Color {
        let lower = model.settingsMessage.localizedLowercase
        return lower.contains("kaydedildi") || lower.contains("kaldırıldı")
            ? .green : .secondary
    }

    private func providerStateIcon(_ state: DivanProviderState) -> String {
        switch state {
        case .ready: "checkmark.circle.fill"
        case .needsAttention: "exclamationmark.triangle.fill"
        case .unavailable: "xmark.octagon.fill"
        }
    }

    private func providerStateColor(_ state: DivanProviderState) -> Color {
        switch state {
        case .ready: .green
        case .needsAttention: .orange
        case .unavailable: .red
        }
    }
}

public struct AdvancedPreviewScopeView: View {
    public init() {}

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Önizleme kapsamı")
                        .font(.title2.weight(.semibold))
                    Text("İlk yerel SwiftUI sürümü, güvenilir temel görüşme akışına odaklanır.")
                        .foregroundStyle(.secondary)
                    NativePreviewScopeBadge()
                }

                ForEach(DivanAdvancedPreview.allCases) { feature in
                    HStack(alignment: .top, spacing: 13) {
                        Image(systemName: feature.systemImage)
                            .font(.title2)
                            .frame(width: 34)
                            .foregroundStyle(.secondary)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(feature.title).font(.headline)
                            Text("Bu özellik henüz yerel önizleme kapsamına alınmadı.")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text("Kullanılamıyor")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(.quaternary, in: Capsule())
                    }
                    .padding(14)
                    .background(.background, in: RoundedRectangle(cornerRadius: 12))
                    .overlay {
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color(nsColor: .separatorColor))
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(22)
            .frame(maxWidth: 720, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}
