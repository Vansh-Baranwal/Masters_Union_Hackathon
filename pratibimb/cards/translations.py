"""
Pre-translated fixed card strings for the reply cards.
Keys are verdict names; values are dicts keyed by BCP-47 language code.
Dynamic reason text is translated on demand via SarvamClient.translate().

Languages covered here: en, hi-IN, kn-IN (Kannada — the metro's primary regional language).
Add more by calling SarvamClient.translate() offline and pasting results here.
"""

CARD_STRINGS: dict[str, dict[str, str]] = {
    # ── Header labels ────────────────────────────────────────────────────── #
    "app_name": {
        "en":    "Pratibimb",
        "hi-IN": "Pratibimb",
        "kn-IN": "Pratibimb",
    },
    "ticket_received": {
        "en":    "Ticket received",
        "hi-IN": "टिकट प्राप्त हुई",
        "kn-IN": "ಟಿಕೆಟ್ ಸ್ವೀಕರಿಸಲಾಗಿದೆ",
    },
    "payment_found": {
        "en":    "Payment found — no ticket yet",
        "hi-IN": "भुगतान मिला — टिकट नहीं मिला",
        "kn-IN": "ಪಾವತಿ ಕಂಡುಬಂದಿದೆ — ಟಿಕೆಟ್ ಇಲ್ಲ",
    },
    "needs_review": {
        "en":    "Needs review",
        "hi-IN": "समीक्षा आवश्यक है",
        "kn-IN": "ಪರಿಶೀಲನೆ ಅಗತ್ಯ",
    },
    "unreadable": {
        "en":    "Could not read screenshot",
        "hi-IN": "स्क्रीनशॉट पढ़ा नहीं जा सका",
        "kn-IN": "ಸ್ಕ್ರೀನ್‌ಶಾಟ್ ಓದಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ",
    },
    "corroborated": {
        "en":    "Corroborated",
        "hi-IN": "पुष्टि हुई",
        "kn-IN": "ದೃಢಪಡಿಸಲಾಗಿದೆ",
    },
    "extracted": {
        "en":    "Recorded",
        "hi-IN": "दर्ज किया गया",
        "kn-IN": "ದಾಖಲಿಸಲಾಗಿದೆ",
    },
    # ── Field labels ─────────────────────────────────────────────────────── #
    "label_amount": {
        "en":    "Amount",
        "hi-IN": "राशि",
        "kn-IN": "ಮೊತ್ತ",
    },
    "label_from": {
        "en":    "From",
        "hi-IN": "से",
        "kn-IN": "ನಿಂದ",
    },
    "label_to": {
        "en":    "To",
        "hi-IN": "तक",
        "kn-IN": "ಗೆ",
    },
    "label_link": {
        "en":    "Link",
        "hi-IN": "लिंक",
        "kn-IN": "ಲಿಂಕ್",
    },
    "label_evidence": {
        "en":    "Evidence level",
        "hi-IN": "साक्ष्य स्तर",
        "kn-IN": "ಸಾಕ್ಷ್ಯ ಮಟ್ಟ",
    },
    "label_ref": {
        "en":    "Ref",
        "hi-IN": "संदर्भ",
        "kn-IN": "ಉಲ್ಲೇಖ",
    },
    # ── Footer ────────────────────────────────────────────────────────────── #
    "footer_note": {
        "en":    "Screenshot filed. Your coordinator has been notified.",
        "hi-IN": "स्क्रीनशॉट दर्ज। आपके समन्वयक को सूचित किया गया।",
        "kn-IN": "ಸ್ಕ್ರೀನ್‌ಶಾಟ್ ದಾಖಲಿಸಲಾಗಿದೆ. ನಿಮ್ಮ ಸಮನ್ವಯಕರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ.",
    },
    "footer_caution": {
        "en":    "This is a record, not a guarantee of reimbursement.",
        "hi-IN": "यह एक रिकॉर्ड है, प्रतिपूर्ति की गारंटी नहीं।",
        "kn-IN": "ಇದು ದಾಖಲೆ, ಮರುಪಾವತಿಯ ಖಾತರಿ ಅಲ್ಲ.",
    },
}


def get_string(key: str, lang: str = "en") -> str:
    """Return a translated card string, falling back to English."""
    strings = CARD_STRINGS.get(key, {})
    return strings.get(lang) or strings.get("en") or key
