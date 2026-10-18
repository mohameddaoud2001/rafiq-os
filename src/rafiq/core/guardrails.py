"""
Guardrails - pure functions. Rules 3,6,7,8.
"""

import re
from typing import List, Tuple

from rafiq.core.messages import ERRORS

# Hard block patterns: bloodshed, takfir of individuals/rulers, rebellion
HARD_BLOCK_PATTERNS = [
    r"اقتلوا?",
    r"دم\s*ال",
    r"سفك.*دم",
    r"تكفير.*الحاكم",
    r"تكفير.*فلان",
    r"كافر.*الحاكم",
    r"الخروج.*على.*الحاكم",
    r"الثورة.*المسلحة",
    r"جهاد.*الحاكم",
    r"bloodshed",
    r"kill.*ruler",
    r"takfir.*ruler",
]

# Takfir/tabdi' aimed at Ash'ari, Maturidi, Athari schools - block
SCHOOL_TAKFIR_PATTERNS = [
    r"الأشاعرة.*كفار",
    r"الماتريدية.*كفار",
    r"الأثرية.*كفار",
    r"الأشعرية.*مبتدعة.*ضلال",
    r"تكفير.*الأشاعرة",
    r"تكفير.*الماتريدية",
    r"اشعري.*كافر",
    r"اشاعرة.*كفار",
]

# Allowed scholarly difference questions
ALLOWED_DIFF_PATTERNS = [
    r"ما الفرق بين الأشعرية والماتريدية",
    r"الفرق.*الأشعرية.*الماتريدية",
    r"ما الفرق.*الأشعري",
    r"اشرح.*الأشعرية",
]

# Talfiq request: combine easiest opinions
TALFIQ_PATTERNS = [
    r"اجمع.*أسهل.*الأقوال",
    r"خذ.*أيسر.*مذهب",
    r"تتبع.*الرخص",
    r"combine.*easiest.*opinions",
]


def contains_pattern(text: str, patterns: List[str]) -> bool:
    low = text.lower()
    for pat in patterns:
        if re.search(pat, low):
            return True
    return False


def is_allowed_diff_question(text: str) -> bool:
    return contains_pattern(text, ALLOWED_DIFF_PATTERNS)


def check_input_hard_block(text: str) -> Tuple[bool, str]:
    """Returns (blocked, reason)."""
    if contains_pattern(text, HARD_BLOCK_PATTERNS):
        return True, ERRORS["hard_block"]
    return False, ""


def check_input_adab(text: str) -> Tuple[bool, str]:
    """Block takfir aimed at schools, unless it's a neutral question."""
    if is_allowed_diff_question(text):
        return False, ""
    if contains_pattern(text, SCHOOL_TAKFIR_PATTERNS):
        return True, ERRORS["takfir_block"]
    return False, ""


def check_talfiq(text: str) -> Tuple[bool, str]:
    if contains_pattern(text, TALFIQ_PATTERNS):
        return True, ERRORS["talfiq_risk"]
    return False, ""


def check_all_input(text: str) -> Tuple[bool, List[str], List[str]]:
    """
    Returns (hard_blocked, warnings, flags)
    """
    hard_blocked, msg = check_input_hard_block(text)
    if hard_blocked:
        return True, [msg], ["HARD_BLOCK"]

    warnings = []
    flags = []

    blocked, msg = check_input_adab(text)
    if blocked:
        return True, [msg], ["ADAB_BLOCK"]

    is_talfiq, t_msg = check_talfiq(text)
    if is_talfiq:
        warnings.append(t_msg)
        flags.append("TALFIQ_RISK")

    return False, warnings, flags


def check_output_adab(text: str) -> Tuple[bool, str]:
    if contains_pattern(text, SCHOOL_TAKFIR_PATTERNS):
        return True, ERRORS["takfir_block"]
    return False, ""
