import re
from typing import Any, Dict, List

from app.core.config import settings

_PROHIBITED_PATTERNS = (
    r"\bgender\b",
    r"\brace\b",
    r"\bsex\b",
    r"\bethnicity\b",
    r"\bzipcode\b",
    r"\bzip\s+code\b",
    r"\bcredit\s+score\b",
)

_VOWEL_GROUPS = re.compile(r"[aeiouy]+", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9']+")


def prohibited_term_leak_count(text: str) -> int:
    """Count restricted demographic and credit terms. The target is zero."""
    haystack = text.lower()
    return sum(len(re.findall(pattern, haystack)) for pattern in _PROHIBITED_PATTERNS)


def factor_coverage(explanation: str, risk_drivers: List[str]) -> float:
    """Matched explanation factors divided by drivers from the math engine."""
    if not risk_drivers:
        return 1.0
    text = explanation.lower()
    matched = 0
    for driver in risk_drivers:
        needle = driver.strip().lower().rstrip(".")
        if needle and needle in text:
            matched += 1
    return matched / len(risk_drivers)


def count_syllables(word: str) -> int:
    letters = re.sub(r"[^a-z]", "", word.lower())
    if not letters:
        return 1
    groups = _VOWEL_GROUPS.findall(letters)
    count = len(groups)
    if letters.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def flesch_kincaid(text: str) -> Dict[str, float]:
    sentences = [part for part in re.split(r"[.!?]+", text) if part.strip()]
    words = _WORD.findall(text)
    sentence_count = max(len(sentences), 1)
    word_count = max(len(words), 1)
    syllable_count = sum(count_syllables(word) for word in words)
    words_per_sentence = word_count / sentence_count
    syllables_per_word = syllable_count / word_count
    reading_ease = 206.835 - (1.015 * words_per_sentence) - (84.6 * syllables_per_word)
    grade_level = (0.39 * words_per_sentence) + (11.8 * syllables_per_word) - 15.59
    return {
        "flesch_reading_ease": reading_ease,
        "flesch_grade_level": grade_level,
    }


def policyholder_text(reasons: List[str]) -> str:
    if not reasons:
        return "No extra risk factors were found."
    parts = []
    for reason in reasons:
        sentence = reason.strip()
        if sentence and sentence[-1] not in ".!?":
            sentence += "."
        parts.append(sentence)
    return " ".join(parts)


def evaluate_explanation(text: str, risk_drivers: List[str]) -> Dict[str, Any]:
    leaks = prohibited_term_leak_count(text)
    coverage = factor_coverage(text, risk_drivers)
    readability = flesch_kincaid(text)
    ease = readability["flesch_reading_ease"]
    grade = readability["flesch_grade_level"]
    passed = (
        leaks == 0
        and coverage >= settings.FACTOR_COVERAGE_MIN
        and ease >= settings.FLESCH_READING_EASE_MIN
        and grade <= settings.FLESCH_GRADE_MAX
    )
    return {
        "prohibited_term_leaks": leaks,
        "factor_coverage": round(coverage, 4),
        "flesch_reading_ease": round(ease, 2),
        "flesch_grade_level": round(grade, 2),
        "passed": passed,
    }
