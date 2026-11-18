"""Evidence validation tests (pure functions, no LLM)."""

import pytest

from app.agent.evidence import check_claims, check_plan_evidence, extract_numbers, extract_urls
from app.agent.schemas import TaskStatus
from tests.test_executor import make_plan

EVIDENCE = """Search results: 393 Ai Ml Engineer Fresher jobs in Hyderabad
URL: https://in.indeed.com/q-ai-ml-engineer-fresher-l-hyderabad,-telangana-jobs.html?vjk=11bb
Salary range: 6-9 LPA. Stipend: 40,000 INR per month.
Python output: Total amount: 146932.80768000004
calculator: 40000 * 12 / 100000 = 4.8"""


def test_extract_numbers_handles_grouping_and_skips_small_whole_numbers() -> None:
    found = {raw: value for raw, value, _ in extract_numbers("1,46,932.81 rupees, 393 jobs, 5 years, 3 days, 7.5 LPA")}

    assert found == {"1,46,932.81": 146932.81, "393": 393.0, "7.5": 7.5}


def test_digits_inside_urls_are_not_numbers() -> None:
    assert extract_numbers("see https://jobs.example/12345/list") == []


def test_extract_urls_normalizes() -> None:
    assert extract_urls("Visit https://A.example/path/. Or (https://b.example)") == [
        "https://a.example/path", "https://b.example",
    ]


@pytest.mark.parametrize(
    "claim",
    [
        "393 openings",  # exact
        "40,000 INR",  # grouping removed
        "1,46,932.81 rupees",  # Indian grouping + rounding of 146932.80768
        "4.8 LPA",  # decimal from the calculator
        "https://in.indeed.com/q-ai-ml-engineer-fresher-l-hyderabad,-telangana-jobs.html",  # shortened link
    ],
)
def test_supported_facts(claim: str) -> None:
    assert check_claims(claim, EVIDENCE).unsupported == []


@pytest.mark.parametrize(
    ("claim", "flagged"),
    [
        ("2,500 openings in Bengaluru", "2,500"),
        ("average salary is 7.5 LPA", "7.5"),
        ("source: https://fake-jobs.example/list", "https://fake-jobs.example/list"),
        ("total 146,999.00", "146,999.00"),  # close but not a rounding of the source
    ],
)
def test_unsupported_facts_are_flagged(claim: str, flagged: str) -> None:
    assert check_claims(claim, EVIDENCE).unsupported == [flagged]


def test_support_ratio() -> None:
    result = check_claims("393 jobs, 2,500 jobs, https://fake.example", EVIDENCE)

    assert result.checked_numbers == 2 and result.checked_urls == 1
    assert result.support_ratio == pytest.approx(1 / 3)


def test_plan_evidence_checks_only_claim_tasks_against_primary_sources() -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "generate_report", ["t2"]))
    outputs = {"t1": "393 jobs found", "t2": "There are 393 jobs and 999 internships", "t3": "393 jobs; 999 internships"}
    for task in plan.tasks:
        task.status, task.result = TaskStatus.COMPLETED, outputs[task.id]

    results = check_plan_evidence(plan)

    # 999 came from the ANALYSIS, not a source: the report repeating it doesn't make it true.
    assert {tid: r.unsupported for tid, r in results.items()} == {"t2": ["999"], "t3": ["999"]}


def test_no_primary_sources_means_nothing_to_check() -> None:
    plan = make_plan(("t1", "llm_analysis", []))
    plan.get_task("t1").status, plan.get_task("t1").result = TaskStatus.COMPLETED, "Answer: 42 ideas"

    assert check_plan_evidence(plan) == {}
