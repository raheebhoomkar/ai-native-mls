"""Listing policy packs and the rule check of listing remarks.

A policy pack is a versioned set of rules for one jurisdiction. The India pack below is an
illustrative house policy written for the demo. It is not legal advice, has not been reviewed
by a lawyer and does not state what Indian law requires (INSTRUCTIONS.md §2.2, §14 question 4).
A finding is decision support for a reviewer, never a verdict.
"""

import re
from dataclasses import dataclass

SEVERITIES: tuple[str, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    severity: str
    # How likely a match is to be a real problem (0 to 1). A person still decides.
    confidence: float
    title: str
    explanation: str
    suggestion: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Policy:
    id: str
    version: str
    jurisdiction: str
    name: str
    notice: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class Finding:
    rule_id: str
    category: str
    severity: str
    confidence: float
    # The exact text of the remarks that matched, and where it is.
    evidence: str
    start: int
    end: int
    explanation: str
    suggestion: str


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"\b(?:{s})\b", re.IGNORECASE) for s in sources)


def _words(*words: str) -> str:
    return "|".join(words)


# People nouns that often follow a group name: "Jain families only".
_NOUNS = r"(?:families|family|people|tenants|tenant|buyers|buyer|owners|candidates)"
_PEOPLE = rf"(?:\s+{_NOUNS})?"
_RELIGION = _words(
    "hindu", "muslim", "christian", "sikh", "jain", "parsi", "buddhist", "brahmin", "dalit",
    "marwari",
)  # fmt: skip
_REGION = _words(
    "marathi", "gujarati", "punjabi", "bengali", "tamilian", "malayali", "bihari", "kashmiri",
    "south indian", "north indian", "northeasterner", "foreigner", "outsider", "nri", "local",
)  # fmt: skip


def _exclusion(groups: str) -> tuple[str, ...]:
    """Phrases that limit who may live or buy to, or exclude, members of `groups`."""
    group = rf"(?:{groups})s?{_PEOPLE}"
    # After "only" or "no", a group must be plural, followed by a people noun or end the
    # phrase, so "only Christian school nearby" and "no Jain temple nearby" pass.
    person = rf"(?:(?:{groups})s|(?:{groups})\s+{_NOUNS}|(?:{groups})(?=\s*(?:[.,;:!)]|$)))"
    return (
        rf"(?:only|strictly|exclusively)\s+(?:for\s+)?{person}",
        rf"{group}\s+only",
        rf"no\s+{person}",
        rf"{group}\s+(?:not\s+allowed|not\s+permitted|not\s+preferred|need\s+not\s+apply)",
    )


INDIA_POLICY = Policy(
    id="in-house-illustrative",
    version="2026.11-1",
    jurisdiction="IN",
    name="Illustrative listing policy (India)",
    notice=(
        "An example house policy for this demo. It is not legal advice and was not reviewed "
        "by a lawyer. A check that finds nothing does not mean a listing is lawful."
    ),
    rules=(
        Rule(
            id="IN-HP-01",
            category="religion_caste_community",
            severity="high",
            confidence=0.9,
            title="Limits who may live or buy by religion, caste or community",
            explanation="The remarks limit who may rent or buy by religion, caste or community.",
            suggestion=(
                "Remove the restriction. Describe the property and the terms instead, for "
                'example "2 BHK, 5 minutes from the station, available from 1 June".'
            ),
            patterns=_patterns(*_exclusion(_RELIGION)),
        ),
        Rule(
            id="IN-HP-02",
            category="region_language_nationality",
            severity="high",
            confidence=0.85,
            title="Limits who may live or buy by region, language or nationality",
            explanation=(
                "The remarks limit who may rent or buy by home region, language or nationality."
            ),
            suggestion=(
                "Remove the restriction. If paperwork is needed (for example ID or a rental "
                'agreement), say so: "Valid ID and a registered rental agreement required."'
            ),
            patterns=_patterns(*_exclusion(_REGION)),
        ),
        Rule(
            id="IN-HP-03",
            category="food_habits",
            severity="medium",
            confidence=0.75,
            title="Limits who may live or buy by food habits",
            explanation=(
                "The remarks limit tenants or buyers by what they eat. Such limits often "
                "exclude communities indirectly."
            ),
            suggestion=(
                "Remove the restriction. If the society has rules for common areas, state the "
                'rule itself: "Society rules apply to common areas; copy available on request."'
            ),
            patterns=_patterns(
                r"(?:pure\s+)?veg(?:etarian)?s?\s+only",
                r"only\s+(?:for\s+)?(?:vegetarians|vegetarian\s+(?:families|tenants|people|buyers))",
                r"strictly\s+(?:pure\s+)?veg(?:etarian)?s?",
                r"no\s+non[-\s]?veg(?:etarian)?s?(?:\s+(?:food|cooking|people|families))?",
                r"non[-\s]?veg(?:etarian)?s?(?:\s+(?:food|cooking))?\s+not\s+allowed",
            ),
        ),
        Rule(
            id="IN-HP-04",
            category="marital_family_status",
            severity="medium",
            confidence=0.8,
            title="Limits who may live or buy by marital or family status",
            explanation="The remarks limit tenants or buyers by marital or family status.",
            suggestion=(
                "Remove the restriction. State the occupancy instead: "
                '"Suitable for up to 4 occupants."'
            ),
            patterns=_patterns(
                r"no\s+(?:bachelors?|singles|unmarried\s+couples?|live[-\s]in\s+couples?)",
                r"bachelors?\s+not\s+(?:allowed|permitted)",
                r"famil(?:y|ies)\s+only",
                # Not "the only family home in the lane".
                r"only\s+(?:for\s+famil(?:y|ies)|families)",
                r"married\s+couples?\s+only",
                r"only\s+(?:for\s+)?married\s+couples?",
            ),
        ),
        Rule(
            id="IN-HP-05",
            category="gender",
            severity="low",
            confidence=0.5,
            title="Limits who may live or buy by gender",
            explanation=(
                "The remarks limit tenants or buyers by gender. This can be acceptable for a "
                "shared room or a PG; the reviewer decides."
            ),
            suggestion=(
                "If the place is a shared room or a PG for one gender, say so plainly: "
                '"Shared PG accommodation for women." Otherwise remove the restriction.'
            ),
            patterns=_patterns(
                r"(?:girls|boys|ladies|gents|men|women|females?|males?)\s+only",
                r"only\s+(?:for\s+)?(?:girls|boys|ladies|gents|men|women|females|males)",
            ),
        ),
        Rule(
            id="IN-HP-06",
            category="misleading_claim",
            severity="medium",
            confidence=0.9,
            title="Promises guaranteed or assured returns",
            explanation=(
                "The remarks promise a financial return. Returns are not certain, and the "
                "claim can mislead buyers."
            ),
            suggestion=(
                "Remove the promise. State facts a buyer can check instead: "
                '"Currently let at ₹45,000 a month until March 2027."'
            ),
            patterns=_patterns(
                r"(?:guaranteed|assured)\s+(?:returns?|rental(?:\s+income)?|rent|appreciation|profits?)",
                r"\d{1,3}\s?%\s+(?:guaranteed|assured)(?:\s+(?:returns?|appreciation))?",
            ),
        ),
    ),
)


def check_remarks(text: str, policy: Policy = INDIA_POLICY) -> list[Finding]:
    """Every phrase in `text` that a rule of `policy` matches, in reading order."""
    findings: list[Finding] = []
    for rule in policy.rules:
        spans: list[tuple[int, int]] = []
        for pattern in rule.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                # Merge with an overlapping match of the same rule, keeping the wider span.
                for i, (s, e) in enumerate(spans):
                    if start < e and s < end:
                        spans[i] = (min(s, start), max(e, end))
                        break
                else:
                    spans.append((start, end))
        findings.extend(
            Finding(
                rule_id=rule.id,
                category=rule.category,
                severity=rule.severity,
                confidence=rule.confidence,
                evidence=text[start:end],
                start=start,
                end=end,
                explanation=rule.explanation,
                suggestion=rule.suggestion,
            )
            for start, end in spans
        )
    # "families only" inside "Jain families only" is one problem, reported by the wider rule.
    findings = [
        f
        for f in findings
        if not any(
            g.start <= f.start and f.end <= g.end and g.end - g.start > f.end - f.start
            for g in findings
        )
    ]
    return sorted(findings, key=lambda f: (f.start, f.rule_id))
