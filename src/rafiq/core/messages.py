"""
All Arabic user-facing strings, banners and disclaimers.
Scholar review point: single file.
"""

BANNERS = {
    "unverified": (
        "تنبيه: النقول منقولة حرفياً من الطبعات المذكورة معها، وليس فيها شيء من إنشاء النظام"
    ),
    "sim_data": "تنبيه: البيانات المعروضة محاكاة (data_source: sim)",
    "hijri_disclaimer": "التواريخ الهجرية المحسوبة قد تختلف يوما عن الرؤية الشرعية",
    "amin_disclaimer": (
        "شهادة الأمين هي إثبات تقني بقراءات الحساسات عبر HMAC وليست شهادة حلال/شرعية"
    ),
    "hadith_not_found": "عدم وجود الحديث في القاعدة لا يعني صحته أو ضعفه",
    "contract_flag": "هذه تنبيهات اشتباه لمراجعة الهيئة الشرعية وليست أحكاما نهائية",
    "informational": "معلومة عامة - ليست فتوى",
    "pending_review": "سُجّلت المسألة للاطلاع عليها من أهل العلم",
    "unsigned_citations": (
        "تنبيه: الجواب مبني على نقل حرفي من كتب معتمدة مذكورة معه - ليست فتوى مفتٍ "
        "معتمد ولا حكماً ملزماً، وللفتوى راجع أهل العلم"
    ),
    # Owner decision 2026-10-18: sign-off is no longer required or checked.
    # Real book text is always served, under this mandatory per-source banner.
    # {source} is filled with book/author/edition/page by the API.
    "unsigned_pilot": "منقول من الكتب - بلا توقيع مفتٍ - المصدر: {source}",
    "matn_only": ("يُعرض النص التالي كمتن (نقل حرفي من المصدر) فقط - وليس فتوى مفتٍ معتمد"),
    "book_based_answer": (
        "الجواب مستخرج بالنقل الحرفي من كتب معتمدة مذكورة أسفله - ليست فتوى مفتٍ "
        "معتمد ولا حكماً ملزماً، وللفتوى المعتمدة راجع أهل العلم"
    ),
}

# Display labels. "موثّق" is only ever shown when verified:true (legacy scholar
# sign-off records); everything else is plain book text - no signing is
# required to serve it (owner decision 2026-10-18).
LABELS = {
    "verified": "موثّق",
    "unsigned": "منقول من الكتب",
}

MADHHAB_NAMES = {
    "maliki": "مالكي",
    "hanafi": "حفي",
    "shafii": "شافعي",
    "hanbali": "حنبلي",
}

DISPLAY_MODES = {
    "signed": "signed",
    "matn": "matn",
}

ERRORS = {
    "not_found": "لا أعلم، لم أجد نصا في المصادر المعتمدة",
    "hard_block": (
        "هذه المسألة من نوازل الدماء والتكفير والفتن، "
        "يرجى مراجعة المجامع الفقهية الرسمية والجهات المختصة"
    ),
    "talfiq_risk": (
        "تنبيه: طلب تتبع الرخص (الجمع بين أسهل الأقوال) - خطر التلفيق. "
        "يلزم الالتزام بمذهب واحد في العبادة الواحدة"
    ),
    "takfir_block": "لا يجوز التكفير والتبديع الموجّه للمدارس العقدية المعتبرة",
    "sufi_ijaza": "الأوراد الخاصة تؤخذ بإذن من شيخ مأذون",
}

DOSSIER_TITLES = {
    "masala": "المسألة",
    "ruling": "الخلاصة الفقهية",
    "hadith": "الحديث",
    "waqi": "الواقع",
    "warnings": "تنبيهات",
    "closing": "فما حكمكم يا مشايخنا؟",
}
