#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate general-fiqh chapter candidate files from the verified OpenITI editions.

Same works, editions and provenance as the Hajj pilot files; every passage
stays verified:false with page/volume null until a sheikh signs it at /review.

Sources (raw mARkdown, download into one dir, default /tmp/opencode/openiti
or override with $RAFIQ_OPENITI_SRC):

  https://raw.githubusercontent.com/OpenITI/0775AH/master/data/0767KhalilIbnIshaq/0767KhalilIbnIshaq.MukhtasarKhalil/0767KhalilIbnIshaq.MukhtasarKhalil.Shamela0011355-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/0600AH/master/data/0593BurhanDinFarghaniMarghinani/0593BurhanDinFarghaniMarghinani.HidayaFiSharhBidaya/0593BurhanDinFarghaniMarghinani.HidayaFiSharhBidaya.Shamela0011820-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/0700AH/master/data/0676Nawawi/0676Nawawi.MinhajTalibin/0676Nawawi.MinhajTalibin.Shamela0012096-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/0275AH/master/data/0264IbnYahyaMuzani/0264IbnYahyaMuzani.Mukhtasar/0264IbnYahyaMuzani.Mukhtasar.Shamela0001661-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/0625AH/master/data/0620IbnQudamaMaqdisi/0620IbnQudamaMaqdisi.CumdatFiqh/0620IbnQudamaMaqdisi.CumdatFiqh.Shamela0011315-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/1225AH/master/data/1201AhmadDardirAbuBarakat/1201AhmadDardirAbuBarakat.SharhKabir/1201AhmadDardirAbuBarakat.SharhKabir.JK000193-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/1000AH/master/data/1000CabdBariAshmawi/1000CabdBariAshmawi.MatnCashmawiyya/1000CabdBariAshmawi.MatnCashmawiyya.Shamela0037326-ara1  # noqa: E501
  https://raw.githubusercontent.com/OpenITI/0400AH/master/data/0386IbnAbiZaydQayrawani/0386IbnAbiZaydQayrawani.Risala/0386IbnAbiZaydQayrawani.Risala.Shamela0011373-ara1  # noqa: E501

Usage: uv run python scripts/gen_chapters.py
Writes data/corpus/<madhhab>/candidates/<work>_chapters.jsonl (additive;
`rafiq.cli corpus sync-candidates` then loads them into the stores).
"""

import importlib.util
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = pathlib.Path(os.environ.get("RAFIQ_OPENITI_SRC", "/tmp/opencode/openiti"))

spec = importlib.util.spec_from_file_location("conv", ROOT / "scripts/openiti_to_candidates.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

L = "CC BY-NC-SA 4.0 (OpenITI corpus)"

_DARDIR_PLAIN_HEADER_RE = re.compile(r"^# (?:باب|كتاب|فصل) .+$")


def preprocess_dardir(text: str) -> str:
    """Promote Dardir's shallow `#`-level markers to `###` headers.

    The JK digitization marks its chapters as `# | باب ...` / `# باب ...`
    (all other works use `### |`). Promoting the marker lines to `### |`
    lets the shared parser treat them as headings; text is not altered
    otherwise.
    """
    out = []
    for line in text.splitlines():
        if line.startswith("# | "):
            out.append("### | " + line[4:].strip())
        elif _DARDIR_PLAIN_HEADER_RE.match(line):
            out.append("### | " + line[2:].strip())
        else:
            out.append(line)
    return "\n".join(out)


WORKS = [
    dict(
        key="khalil",
        input=SRC / "khalil.txt",
        output=ROOT / "data/corpus/maliki/candidates/khalil_chapters.jsonl",
        madhhab="maliki",
        top_re=r"^### \| (باب|القسم)",
        provenance="OpenITI:0775AH/0767KhalilIbnIshaq.MukhtasarKhalil.Shamela0011355-ara1 sha256:24ef55f36f25e40e26464ff9a3a05cd2a77c0da048a56d23fe07c92ef3724838",
        work="مختصر خليل",
        author="خليل بن إسحاق الجندي المالكي (ت 776هـ)",
        edition="دار الحديث، القاهرة، ط1 1426هـ/2005م، تحقيق أحمد جاد",
        chapters=[
            (
                "باب في أحكام الطهارة وما يناسبهما",
                "khalil_tahara",
                ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض", "مسح"],
            ),
            (
                "باب في احكام الصلاة",
                "khalil_salat",
                [
                    "صلاة",
                    "جماعة",
                    "جمعة",
                    "قصر",
                    "جمع",
                    "عيد",
                    "خوف",
                    "استسقاء",
                    "كسوف",
                    "جنازة",
                    "نافلة",
                    "وتر",
                    "سجود",
                ],
            ),
            (
                "باب أحكام الزكاة",
                "khalil_zakat",
                ["زكاة", "صدقة", "فطر", "زروع", "ثمار", "ركاز", "معادن", "ماشية"],
            ),
            ("باب أحكام الصيام", "khalil_siyam", ["صوم", "رمضان", "اعتكاف", "قضاء", "كفارة"]),
            ("باب في الذكاة", "khalil_dhakat", ["ذكاة", "ذبح", "أضحية", "عقيقة"]),
            ("باب في حكم الاضحية والعقيقة", "khalil_udhiya", ["أضحية", "عقيقة", "ذبح"]),
            ("باب في اليمين", "khalil_yamin", ["يمين", "نذر", "كفارة"]),
            (
                "باب في أحكام النكاح وما يتبعه",
                "khalil_nikah",
                ["نكاح", "زواج", "مهر", "صداق", "ولي", "طلاق", "عدة"],
            ),
            ("باب في الخلع وما يتعلق به", "khalil_khul", ["خلع", "طلاق"]),
            ("باب في العدة", "khalil_idda", ["عدة", "طلاق", "وفاة"]),
            ("باب في أحكام الرضاع", "khalil_rida", ["رضاع", "حضانة"]),
            ("باب في النفقة بالنكاح والملك والقرابة", "khalil_nafaqa", ["نفقة", "قرابة"]),
            (
                "باب في أحكام: البيع شروط الصحة واللزوم",
                "khalil_buyu",
                ["بيع", "شراء", "ربا", "خيار", "ثمن"],
            ),
            ("باب في أحكام الإجارة والكراء", "khalil_ijara", ["إجارة", "كراء", "أجرة"]),
            ("باب في بيان أحكام الوقف", "khalil_waqf", ["وقف", "حبس"]),
            ("باب في أحكام الهبة ومتعلقاتها", "khalil_hiba", ["هبة", "هدية", "صدقة"]),
        ],
    ),
    dict(
        key="dardir",
        input=SRC / "dardir_sharh_kabir.txt",
        output=ROOT / "data/corpus/maliki/candidates/dardir_chapters.jsonl",
        madhhab="maliki",
        top_re=r"^### \| (باب|كتاب)",
        preprocess=preprocess_dardir,
        provenance="OpenITI:1225AH/1201AhmadDardirAbuBarakat.SharhKabir.JK000193-ara1 sha256:61510e7706156bf21e08f46acb96629d6a3631aa4d8e8b6402c8fc048af5106b",
        work="الشرح الكبير على مختصر خليل",
        author="أحمد بن محمد العدوي الدردير أبو البركات (ت 1201هـ)",
        edition="دار الفكر، بيروت، 4 مجلدات، تح: محمد عليش",
        chapters=[
            (
                "باب هذا باب يذكر فيه",
                "dardir_tahara",
                ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض", "مسح"],
            ),
            (
                "باب في بيان أوقات الصلاة والأذان",
                "dardir_salat",
                [
                    "صلاة",
                    "جماعة",
                    "جمعة",
                    "قصر",
                    "جمع",
                    "عيد",
                    "خوف",
                    "استسقاء",
                    "كسوف",
                    "جنازة",
                    "نافلة",
                    "وتر",
                    "سجود",
                    "أذان",
                    "أوقات",
                ],
            ),
            (
                "باب الزكاة",
                "dardir_zakat",
                ["زكاة", "صدقة", "فطر", "زروع", "ثمار", "ركاز", "معادن", "ماشية"],
            ),
            ("باب ذكر فيه حكم الصيام", "dardir_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
            ("باب في الاعتكاف", "dardir_itikaf", ["اعتكاف", "مسجد", "صوم", "رمضان"]),
            (
                "باب في بيان أحكام الحج والعمرة",
                "dardir_hajj",
                ["حج", "عمرة", "إحرام", "طواف", "سعي", "وقوف", "عرفة", "مناسك", "هدي", "فدية"],
            ),
            ("باب الذكاة", "dardir_dhakat", ["ذكاة", "ذبح", "صيد", "لحم"]),
            ("باب المباح حال الاختيار", "dardir_atima", ["طعام", "أطعمة", "لحم", "مباح"]),
            ("باب ( سن ) عينا", "dardir_udhiya", ["أضحية", "عقيقة", "ذبح"]),
            ("باب ( اليمين تحقيق )", "dardir_yamin", ["يمين", "نذر", "كفارة", "أيمان"]),
            (
                "باب في النكاح وما يتعلق به",
                "dardir_nikah",
                ["نكاح", "زواج", "مهر", "صداق", "ولي", "خلع", "قسم", "عيب"],
            ),
            ("باب الإيلاء يمين زوج", "dardir_ila", ["إيلاء", "طلاق", "كفارة"]),
            ("باب ذكر فيه الظهار", "dardir_zihar", ["ظهار", "طلاق", "كفارة"]),
            ("باب ذكر فيه اللعان", "dardir_lian", ["لعان", "طلاق"]),
            (
                "باب في بيان ذلك وأسبابها",
                "dardir_idda",
                ["عدة", "طلاق", "قرء", "حيض", "وفاة"],
            ),
            ("باب حصول", "dardir_rida", ["رضاع", "حضانة", "لبن"]),
            ("باب ذكر فيه أسباب النفقة", "dardir_nafaqa", ["نفقة", "قرابة"]),
            (
                "باب ذكر فيه البيع",
                "dardir_buyu",
                ["بيع", "شراء", "ربا", "خيار", "ثمن", "عينة", "مرابحة"],
            ),
            ("باب ذكر فيه السلم", "dardir_salam", ["سلم", "صرف", "قرض", "ثمن", "بيع"]),
            ("باب في أحكام الوقف", "dardir_waqf", ["وقف", "حبس", "تبرعات"]),
            ("باب في الهبة", "dardir_hiba", ["هبة", "هدية", "صدقة"]),
        ],
    ),
    dict(
        key="hidaya",
        input=SRC / "0593BurhanDinFarghaniMarghinani.HidayaFiSharhBidaya.Shamela0011820-ara1",
        output=ROOT / "data/corpus/hanafi/candidates/hidaya_chapters.jsonl",
        madhhab="hanafi",
        top_re=r"^### \| كتاب",
        provenance="OpenITI:0593BurhanDinFarghaniMarghinani.HidayaFiSharhBidaya.Shamela0011820-ara1 sha256:3905f6857e80f31b3cd027d328b3374e134afb6e37cd25da336c158ac4a89539",
        work="الهداية في شرح بداية المبتدي",
        author="برهان الدين المرغيناني (ت 593هـ)",
        edition="دار إحياء التراث العربي، بيروت، ط1 1425هـ/2004م، اعتنى بتصحيحه: طلال يوسف",
        chapters=[
            (
                "كتاب الطهارات",
                "hidaya_tahara",
                ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض", "مسح"],
            ),
            (
                "كتاب الصلاة",
                "hidaya_salat",
                [
                    "صلاة",
                    "جماعة",
                    "جمعة",
                    "قصر",
                    "عيد",
                    "جنازة",
                    "وتر",
                    "نوافل",
                    "سجود",
                    "خوف",
                    "كسوف",
                    "استسقاء",
                ],
            ),
            (
                "كتاب الزكاة",
                "hidaya_zakat",
                ["زكاة", "صدقة", "فطر", "ماشية", "زروع", "معادن", "ركاز"],
            ),
            ("كتاب الصوم", "hidaya_siyam", ["صوم", "رمضان", "اعتكاف", "قضاء", "كفارة"]),
            ("كتاب النكاح", "hidaya_nikah", ["نكاح", "زواج", "مهر", "ولي", "كفاءة"]),
            ("كتاب البيوع", "hidaya_buyu", ["بيع", "شراء", "ربا", "خيار", "سلم", "صرف"]),
            ("كتاب الإجارات", "hidaya_ijara", ["إجارة", "أجرة", "كراء"]),
            ("كتاب الوقف", "hidaya_waqf", ["وقف", "حبس"]),
            ("كتاب الهبة", "hidaya_hiba", ["هبة", "هدية", "صدقة"]),
        ],
    ),
    dict(
        key="minhaj",
        input=SRC / "0676Nawawi.MinhajTalibin.Shamela0012096-ara1",
        output=ROOT / "data/corpus/shafii/candidates/minhaj_chapters.jsonl",
        madhhab="shafii",
        top_re=r"^### \| كتاب",
        provenance="OpenITI:0676Nawawi.MinhajTalibin.Shamela0012096-ara1 sha256:cc3f7c36724bd8eea64efb2af1a20dbe5013b4caa7a965fe3be652d2b02b16d2",
        work="منهاج الطالبين وعمدة المفتين",
        author="أبو زكريا يحيى بن شرف النووي (ت 676هـ)",
        edition="دار الفكر، ط1 1425هـ/2005م، تحقيق عوض قاسم أحمد عوض",
        chapters=[
            (
                "كتاب الطهارة",
                "minhaj_tahara",
                ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض", "مسح"],
            ),
            (
                "كتاب الصلاة",
                "minhaj_salat",
                [
                    "صلاة",
                    "جماعة",
                    "جمعة",
                    "قصر",
                    "عيد",
                    "وتر",
                    "نوافل",
                    "سجود",
                    "خوف",
                    "كسوف",
                    "استسقاء",
                ],
            ),
            ("كتاب صلاة الجماعة", "minhaj_jamaa", ["صلاة", "جماعة", "إمامة"]),
            ("كتاب الجنائز", "minhaj_janaiz", ["جنازة", "ميت", "دفن", "تعزية"]),
            (
                "كتاب الزكاة",
                "minhaj_zakat",
                ["زكاة", "صدقة", "فطر", "ماشية", "زروع", "معادن", "ركاز"],
            ),
            ("كتاب الصيام", "minhaj_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
            ("كتاب الاعتكاف", "minhaj_itikaf", ["اعتكاف", "مسجد"]),
            ("كتاب البيع", "minhaj_buyu", ["بيع", "شراء", "ربا", "خيار", "سلم", "صرف", "رهن"]),
            ("كتاب الإجارة", "minhaj_ijara", ["إجارة", "أجرة", "كراء"]),
            ("كتاب الوقف", "minhaj_waqf", ["وقف", "حبس"]),
            ("كتاب الهبة", "minhaj_hiba", ["هبة", "هدية", "صدقة"]),
            ("كتاب النكاح", "minhaj_nikah", ["نكاح", "زواج", "مهر", "صداق", "ولي"]),
            ("كتاب الطلاق", "minhaj_talaq", ["طلاق", "خلع", "ظهار", "إيلاء", "لعان", "عدة"]),
        ],
    ),
    dict(
        key="muzani",
        input=SRC / "0264IbnYahyaMuzani.Mukhtasar.Shamela0001661-ara1",
        output=ROOT / "data/corpus/shafii/candidates/muzani_chapters.jsonl",
        madhhab="shafii",
        top_re=r"^### \| \[كتاب",
        provenance="OpenITI:0264IbnYahyaMuzani.Mukhtasar.Shamela0001661-ara1 sha256:29b008a05703da55a7bbbbe49069be905aafa90d7e0be6073d4cdb7fb0171054",
        work="مختصر المزني",
        author="إسماعيل بن يحيى المزني (ت 264هـ)",
        edition="دار الفكر، بيروت، ط2 1403هـ/1983م (مطبوع بآخر كتاب الأم، الجزء 8)",
        chapters=[
            ("[باب الطهارة]", "muzani_tahara", ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض"]),
            (
                "[كتاب الصلاة]",
                "muzani_salat",
                ["صلاة", "جماعة", "جمعة", "قصر", "عيد", "وتر", "نوافل", "سجود", "خوف"],
            ),
            ("[كتاب الجنائز]", "muzani_janaiz", ["جنازة", "ميت", "دفن"]),
            ("[كتاب الزكاة]", "muzani_zakat", ["زكاة", "صدقة", "فطر", "ماشية", "زروع"]),
            ("[كتاب الصيام]", "muzani_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
            ("[كتاب البيع]", "muzani_buyu", ["بيع", "شراء", "ربا", "خيار", "سلم"]),
            ("[كتاب الخلع]", "muzani_khul", ["خلع", "طلاق"]),
            ("[كتاب الطلاق]", "muzani_talaq", ["طلاق", "ظهار", "لعان", "إيلاء", "عدة"]),
            ("[كتاب العدد]", "muzani_idda", ["عدة", "طلاق", "وفاة"]),
            ("[كتاب الرضاع]", "muzani_rida", ["رضاع", "حضانة"]),
            ("[كتاب النفقة]", "muzani_nafaqa", ["نفقة", "قرابة"]),
            ("[كتاب الصيد والذبائح]", "muzani_sayd", ["صيد", "ذبح", "ذكاة"]),
            ("[كتاب الضحايا]", "muzani_dahaya", ["أضحية", "ذبح"]),
            ("[كتاب العطايا والصدقات والحبس]", "muzani_ataya", ["هبة", "صدقة", "وقف", "حبس"]),
            ("[كتاب الوكالة]", "muzani_wakala", ["وكالة", "توكيل"]),
        ],
    ),
    dict(
        key="cumda",
        input=SRC / "0620IbnQudamaMaqdisi.CumdatFiqh.Shamela0011315-ara1",
        output=ROOT / "data/corpus/hanbali/candidates/cumda_chapters.jsonl",
        madhhab="hanbali",
        top_re=r"^### \| كتاب",
        provenance="OpenITI:0620IbnQudamaMaqdisi.CumdatFiqh.Shamela0011315-ara1 sha256:46a47285cf2cf1796a675853df7c5d6d69de7084666064dba6b596cf4863cd84",
        work="عمدة الفقه",
        author="موفق الدين عبد الله بن قدامة المقدسي (ت 620هـ)",
        edition="المكتبة العصرية، 1425هـ/2004م، تحقيق أحمد محمد عزوز",
        chapters=[
            ("كتاب الطهارة", "cumda_tahara", ["طهارة", "وضوء", "غسل", "تيمم", "نجاسة", "حيض"]),
            (
                "كتاب الصلاة",
                "cumda_salat",
                [
                    "صلاة",
                    "جماعة",
                    "جمعة",
                    "قصر",
                    "عيد",
                    "وتر",
                    "نوافل",
                    "سجود",
                    "خوف",
                    "كسوف",
                    "استسقاء",
                ],
            ),
            ("كتاب الجنائز", "cumda_janaiz", ["جنازة", "ميت", "دفن"]),
            ("كتاب الزكاة", "cumda_zakat", ["زكاة", "صدقة", "فطر", "ماشية", "زروع"]),
            ("كتاب الصيام", "cumda_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
            ("كتاب البيوع", "cumda_buyu", ["بيع", "شراء", "ربا", "خيار", "سلم", "رهن"]),
            ("كتاب الإجارة", "cumda_ijara", ["إجارة", "أجرة", "كراء"]),
            ("كتاب الوقف", "cumda_waqf", ["وقف", "حبس"]),
            ("كتاب الوصايا", "cumda_wasaya", ["وصية", "وصايا"]),
            ("كتاب الفرائض", "cumda_faraid", ["فرائض", "ميراث", "إرث"]),
            ("كتاب النكاح", "cumda_nikah", ["نكاح", "زواج", "مهر", "ولي"]),
            ("كتاب الرضاع", "cumda_rida", ["رضاع", "حضانة"]),
            ("كتاب الصداق", "cumda_sidaq", ["صداق", "مهر"]),
            ("كتاب الطلاق", "cumda_talaq", ["طلاق", "خلع", "عدة"]),
            ("كتاب الظهار", "cumda_zihar", ["ظهار", "كفارة"]),
            ("كتاب اللعان", "cumda_lian", ["لعان", "طلاق"]),
            ("كتاب الأطعمة", "cumda_atima", ["طعام", "أطعمة", "ذكاة", "لحم"]),
            ("كتاب الصيد", "cumda_sayd", ["صيد", "ذبح", "ذكاة"]),
            ("كتاب الأيمان", "cumda_ayman", ["يمين", "أيمان", "نذر", "كفارة"]),
        ],
    ),
    # Beginner layer (M22): short readable Maliki matn. ابن عاشر «المرشد المعين»
    # has no OpenITI digitization (checked the release index), so the second
    # easy text is ابن أبي زيد «متن الرسالة» - the classic beginner matn.
    # Files live under data/corpus/easy/ but rows are maliki, so
    # sync_candidates routes them into the maliki store.
    dict(
        key="ashmawiya",
        input=SRC / "ashmawiyya.txt",
        output=ROOT / "data/corpus/easy/candidates/ashmawiya_chapters.jsonl",
        madhhab="maliki",
        top_re=r"^### \| (باب|فصل|مقدمة)",
        provenance="OpenITI:1000AH/1000CabdBariAshmawi.MatnCashmawiyya.Shamela0037326-ara1 sha256:dfc72bc3e962ef8b425242ce279fa7c0c5dc5956faf51d1aea3f6f6e648b0bb5",
        work="متن العشماوية في مذهب الإمام مالك",
        author="عبد الباري بن أحمد العشماوي القاهري المالكي (المتوفى: ق 10هـ)",
        edition="شركة الشمرلي للطبع والنشر، مصر (بلا تاريخ)",
        chapters=[
            ("باب نواقض الوضوء", "ashmawiya_nawaqid", ["طهارة", "وضوء", "نواقض"]),
            (
                "باب أقسام المياه التي يجوز منها الوضوء",
                "ashmawiya_miyah",
                ["طهارة", "ماء", "وضوء"],
            ),
            ("باب فرائض الغسل وسننه وفضائله", "ashmawiya_ghusl", ["طهارة", "غسل", "جنابة"]),
            ("باب التيمم", "ashmawiya_tayammum", ["طهارة", "تيمم"]),
            ("باب شروط الصلاة", "ashmawiya_salat", ["صلاة", "أوقات", "قبلة"]),
            ("باب مندوبات الصلاة", "ashmawiya_mandubat", ["صلاة", "سنن", "مندوبات"]),
            ("باب مفسدات الصلاة", "ashmawiya_mufsidat", ["صلاة", "مفسدات"]),
            ("باب سجود السهو", "ashmawiya_sahw", ["صلاة", "سهو", "سجود"]),
            (
                "باب في الإمامة",
                "ashmawiya_imama",
                ["صلاة", "إمامة", "جماعة", "اقتداء", "مأموم"],
            ),
            ("باب صلاة الجمعة", "ashmawiya_jumua", ["صلاة", "جمعة", "جماعة", "خطبة"]),
            ("باب صلاة الجنازة", "ashmawiya_janaza", ["صلاة", "جنازة", "ميت"]),
            ("باب الصيام", "ashmawiya_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
        ],
    ),
    dict(
        key="risala",
        input=SRC / "risala.txt",
        output=ROOT / "data/corpus/easy/candidates/risala_chapters.jsonl",
        madhhab="maliki",
        top_re=r"^### \| باب",
        provenance="OpenITI:0400AH/0386IbnAbiZaydQayrawani.Risala.Shamela0011373-ara1 sha256:f20a50969199e69238e87f1949a5c9a0a725d586a4ad409151363702043258ab",
        work="متن الرسالة",
        author="أبو محمد عبد الله بن أبي زيد القيرواني المالكي (ت 386هـ)",
        edition="بيانات الطبعة غير مذكورة في الرقمنة",
        chapters=[
            (
                "باب ما يجب منه الوضوء والغسل",
                "risala_nawaqid",
                ["طهارة", "وضوء", "نواقض"],
            ),
            (
                "باب طهارة الماء والثوب والبقعة",
                "risala_miyah",
                ["طهارة", "ماء", "نجاسة", "لباس"],
            ),
            (
                "باب صفة الوضوء ومسنونه ومفروضه",
                "risala_wudu",
                ["طهارة", "وضوء", "استنجاء"],
            ),
            ("باب في الغسل", "risala_ghusl", ["طهارة", "غسل", "جنابة"]),
            ("باب فيمن لم يجد الماء وصفة التيمم", "risala_tayammum", ["طهارة", "تيمم"]),
            ("باب في المسح على الخفين", "risala_mash", ["طهارة", "مسح", "خف"]),
            ("باب في أوقات الصلاة وأسمائها", "risala_awqat", ["صلاة", "أوقات"]),
            ("باب في الأذان والإقامة", "risala_adhan", ["صلاة", "أذان", "إقامة"]),
            ("باب صفة العمل في الصلوات المفروضة", "risala_salat", ["صلاة", "نوافل", "سنن", "سجود"]),
            (
                "باب في الإمامة وحكم الإمام والماموم",
                "risala_imama",
                ["صلاة", "إمامة", "جماعة", "مأموم"],
            ),
            ("باب جامع في الصلاة", "risala_jami", ["صلاة", "جماعة"]),
            ("باب في سجود القرآن", "risala_sujud", ["صلاة", "سجود", "قرآن"]),
            ("باب في صلاة السفر", "risala_safar", ["صلاة", "سفر", "قصر"]),
            ("باب في صلاة الجمعة", "risala_jumua", ["صلاة", "جمعة", "جماعة", "خطبة"]),
            ("باب في صلاة الخوف", "risala_khawf", ["صلاة", "خوف"]),
            ("باب في صلاة العيدين والتكبير أيام منى", "risala_eidayn", ["صلاة", "عيد", "تكبير"]),
            ("باب في صلاة الخسوف", "risala_khusuf", ["صلاة", "خسوف", "كسوف"]),
            ("باب في صلاة الاستسقاء", "risala_istisqa", ["صلاة", "استسقاء", "مطر"]),
            ("باب ما يفعل بالمحتضر وفي غسل الميت", "risala_mawt", ["جنازة", "ميت", "غسل"]),
            ("باب في الصلاة على الجنائز والدعاء للميت", "risala_janaza", ["صلاة", "جنازة", "ميت"]),
            ("باب في الصيام", "risala_siyam", ["صوم", "رمضان", "قضاء", "كفارة"]),
            ("باب في الاعتكاف", "risala_itikaf", ["صوم", "اعتكاف"]),
            ("باب في زكاة العين والحرث والماشية", "risala_zakat", ["زكاة", "نصاب", "معدن"]),
            ("باب في زكاة الماشية", "risala_zakat_mal", ["زكاة", "ماشية", "أنعام"]),
            ("باب في زكاة الفطر", "risala_zakat_fitr", ["زكاة", "فطر"]),
            ("باب في الحج والعمرة", "risala_hajj", ["حج", "عمرة", "إحرام", "طواف", "سعي"]),
        ],
    ),
]


def stripped(line: str) -> str:
    return line.lstrip("#|~ ").strip()


for w in WORKS:
    text = w["input"].read_text(encoding="utf-8")
    if w.get("preprocess"):
        text = w["preprocess"](text)
    lines = text.splitlines()
    # OpenITI marker lines are usually standalone (`# PageV01P001`), but in
    # some digitizations the first markers sit inline on front-matter lines,
    # so fall back to the first line containing any PageV marker.
    first_page = next(
        (i for i, line in enumerate(lines) if re.match(r"^#+ *PageV\d+P", line.strip())),
        None,
    )
    first_any = next((i for i, line in enumerate(lines) if "PageV" in line), len(lines))
    if first_page is None or first_any < first_page:
        first_page = first_any
    top = [
        (i, stripped(line))
        for i, line in enumerate(lines)
        if re.match(w["top_re"], line) and not stripped(line).startswith("مدخل") and i >= first_page
    ]

    def find_start(title: str):
        for i, line in enumerate(lines):
            if i >= first_page and line.startswith("###") and title in stripped(line):
                return i, stripped(line)
        return None

    out_rows = []
    for title, slug, tags in w["chapters"]:
        hit = find_start(title)
        if hit is None:
            print(f"  !! NOT FOUND {w['key']}: {title}")
            continue
        idx, found = hit
        nxt = next((t for i, t in top if i > idx), None)
        pages = conv.parse_markdown_section(text, title, end_with=nxt)
        for p in pages:
            all_tags = list(dict.fromkeys([w["madhhab"], *tags, *p["headings"]]))
            vol = p.get("vol", "01")
            hint = f"PageV{vol}P{p['page']:03d} (page hint from digitization; confirm at sign-off)"
            sid = (
                f"{slug}_p{p['page']:03d}" if vol == "01" else f"{slug}_v{int(vol)}p{p['page']:03d}"
            )
            out_rows.append(
                {
                    "id": sid,
                    "madhhab": w["madhhab"],
                    "work": w["work"],
                    "author": w["author"],
                    "edition": w["edition"],
                    "volume": None,
                    "page": None,
                    "text": p["text"],
                    "topic_tags": all_tags,
                    "mutamad": None,
                    "verified": False,
                    "provenance": f"{w['provenance']} {hint}",
                    "license": L,
                    "verified_by": None,
                    "verified_at": None,
                }
            )
        print(f"  {w['key']}: {slug} {len(pages)} pages")
    ids = [r["id"] for r in out_rows]
    assert len(ids) == len(set(ids)), f"duplicate ids in {w['key']}"
    w["output"].parent.mkdir(parents=True, exist_ok=True)
    with open(w["output"], "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"== {w['key']}: wrote {len(out_rows)} passages -> {w['output'].name}")
