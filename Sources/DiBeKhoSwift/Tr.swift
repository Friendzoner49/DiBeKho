import DiBeKhoCore

/// A text of the Swift app that the Python i18n files do not have (they are the source of `t("key")`): Vietnamese, English,
/// Chinese written side by side. Prefer `t("key")` when the key exists; this is for the rest.
func tr(_ vi: String, _ en: String, _ zh: String) -> String {
    switch L10n.language {
    case "en": return en
    case "zh": return zh
    default: return vi
    }
}
