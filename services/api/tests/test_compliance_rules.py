"""The rule check of listing remarks, without a database."""

import pytest

from app.modules.compliance.policy import INDIA_POLICY, SEVERITIES, check_remarks

# Remarks that must be flagged, with the rule IDs expected (in reading order).
FLAGGED = [
    ("Spacious 2 BHK. Jain families only.", ["IN-HP-01"]),
    ("Available only for Hindus, near temple.", ["IN-HP-01"]),
    ("No Muslims. Call owner.", ["IN-HP-01"]),
    ("Brahmin tenants preferred, Muslims not allowed.", ["IN-HP-01"]),
    ("Flat for rent, Marathi people only.", ["IN-HP-02"]),
    ("No South Indians, no foreigners.", ["IN-HP-02", "IN-HP-02"]),
    ("Pure veg only. Society is quiet.", ["IN-HP-03"]),
    ("Strictly vegetarian, no non-veg cooking.", ["IN-HP-03", "IN-HP-03"]),
    ("Non veg not allowed in the flat.", ["IN-HP-03"]),
    ("No bachelors. Family only.", ["IN-HP-04", "IN-HP-04"]),
    ("Married couples only, close to the IT park.", ["IN-HP-04"]),
    ("Girls only PG with meals.", ["IN-HP-05"]),
    ("Guaranteed returns of 12% in 3 years.", ["IN-HP-06"]),
    ("Investment with 100% assured appreciation.", ["IN-HP-06"]),
    ("Veg only. Jain families only, no bachelors.", ["IN-HP-03", "IN-HP-01", "IN-HP-04"]),
]

# Remarks that mention communities, food or families without excluding anyone.
CLEAN = [
    "Well-lit 3 BHK in Powai, 5 minutes from the lake.",
    "Jain temple and a Christian school nearby.",
    "Pure vegetarian restaurant at the gate.",
    "Only vegetarian restaurants in the food court.",
    "The only family home in the lane with a garden.",
    "No Jain temple nearby, but a park is close.",
    "Ideal for families; suitable for up to 4 occupants.",
    "Currently let at ₹45,000 a month until March 2027.",
    "",
]


@pytest.mark.parametrize(("remarks", "rule_ids"), FLAGGED)
def test_flagged_remarks(remarks: str, rule_ids: list[str]) -> None:
    findings = check_remarks(remarks)
    assert [f.rule_id for f in findings] == rule_ids
    for finding in findings:
        # The evidence is the exact text at the reported place, and every flag explains itself.
        assert remarks[finding.start : finding.end] == finding.evidence
        assert finding.evidence.strip() == finding.evidence and finding.evidence
        assert finding.explanation and finding.suggestion
        assert finding.severity in SEVERITIES and 0 < finding.confidence <= 1


@pytest.mark.parametrize("remarks", CLEAN)
def test_clean_remarks(remarks: str) -> None:
    assert check_remarks(remarks) == []


def test_overlapping_matches_of_one_rule_are_merged() -> None:
    # "only for Jain families" and "Jain families only" overlap; one finding covers both.
    (finding,) = check_remarks("Only for Jain families only.")
    assert finding.evidence == "Only for Jain families only"


def test_phrase_inside_a_wider_finding_is_not_reported_twice() -> None:
    # "families only" (marital rule) sits inside "Jain families only" (community rule).
    assert [f.rule_id for f in check_remarks("Jain families only.")] == ["IN-HP-01"]


def test_matching_ignores_case() -> None:
    assert [f.evidence for f in check_remarks("NO BACHELORS")] == ["NO BACHELORS"]


def test_policy_pack_is_well_formed() -> None:
    ids = [rule.id for rule in INDIA_POLICY.rules]
    assert len(ids) == len(set(ids))
    assert INDIA_POLICY.jurisdiction == "IN" and INDIA_POLICY.version
    assert "not legal advice" in INDIA_POLICY.notice
    for rule in INDIA_POLICY.rules:
        assert rule.severity in SEVERITIES and 0 < rule.confidence <= 1
        assert rule.patterns and rule.title and rule.explanation and rule.suggestion
