import Foundation

/// Birden çok katmanda tekrarlanan kullanıcı metinleri.
///
/// Aynı cümlenin farklı dosyalarda elle yazılması sessiz sapmalara yol
/// açıyordu: "Yanıt tamamlanamadı." yedi yerde geçiyor, bir tanesinde
/// nokta eksikti. Metin buraya taşındığında hem sapma imkânsızlaşır hem
/// de ileride yerelleştirme tek noktadan yapılabilir.
///
/// Yalnızca *paylaşılan* metinler buraya girer; bir ekrana özgü tek
/// kullanımlık cümleler kendi View'ında kalır.
public enum DivanStrings {

    // MARK: - Sohbet

    /// Model yanıtı yarıda kaldığında gösterilir.
    public static let responseIncomplete = "Yanıt tamamlanamadı."

    // MARK: - Erişilebilirlik

    /// Güvenlik gereği her koşulda erişilebilir kalan durdurma/çıkış
    /// eylemlerinin ipucu.
    public static let alwaysAvailableActionHint =
        "Başka bir işlem sürerken ve güvenlik bekletmesinde de kullanılabilir"

    // MARK: - Yaşantısal çalışma

    /// Aynı anda ikinci bir yaşantısal çalışma açılmak istendiğinde.
    public static let finishOpenWorkFirst =
        "Önce açık olan diğer çalışmayı bitirin."
}
