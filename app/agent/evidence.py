"""Evidence validation: are the facts in a report actually backed by the sources?

LLMs can "hallucinate": write a plausible number or URL that no source contains. This
module checks two kinds of facts with plain code (no LLM, so it's free and exact):

  - URLs:    every link in the report must appear in a primary source.
  - Numbers: every number in the report (salaries, counts, results) must match a number
             in a primary source, allowing for rounding (46932.8077 ~ 46932.81) and
             digit grouping (1,46,932.81 = 146932.81). Small WHOLE numbers (< 10) are
             skipped ("3 days a week", "5 years" cause false alarms); decimals such as
             "7.5 LPA" are always checked.

PRIMARY sources are raw tool outputs (search results, files, the knowledge base,
calculator/Python results). The outputs of llm_analysis and generate_report are NOT
evidence: they are the claims being checked.

A flagged fact is "unverified", not proven false: a derived number (e.g. a difference
the LLM computed itself) is also flagged. The LLM judge and the user see these flags.
"""

import re
from dataclasses import dataclass, field

from app.agent.schemas import Plan, TaskStatus

PRIMARY_TOOLS = frozenset(
    {"web_search", "read_file", "search_knowledge_base", "calculator", "python_exec", "database_query"}
)
CLAIM_TOOLS = frozenset({"llm_analysis", "generate_report"})

URL_PATTERN = re.compile(r"https?://[^\s<>\"'\])]+")
# A number: digits, optional thousands separators (1,46,932 or 146,932), optional decimals.
NUMBER_PATTERN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
MIN_CHECKED_NUMBER = 10


@dataclass
class EvidenceResult:
    checked_urls: int = 0
    checked_numbers: int = 0
    unsupported_urls: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)

    @property
    def unsupported(self) -> list[str]:
        return self.unsupported_urls + self.unsupported_numbers

    @property
    def support_ratio(self) -> float:
        checked = self.checked_urls + self.checked_numbers
        return 1.0 if checked == 0 else 1 - len(self.unsupported) / checked


def normalize_url(url: str) -> str:
    return url.rstrip(".,;:!?*_`").rstrip("/").lower()


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(normalize_url(u) for u in URL_PATTERN.findall(text)))


def extract_numbers(text: str) -> list[tuple[str, float, int]]:
    """(original text, value, number of decimals) for every number >= MIN_CHECKED_NUMBER.
    URLs are removed first, so digits inside links are not treated as facts."""
    text = URL_PATTERN.sub(" ", text)
    found: dict[str, tuple[str, float, int]] = {}
    for raw in NUMBER_PATTERN.findall(text):
        cleaned = raw.replace(",", "").rstrip(".")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
        # Small WHOLE numbers ("5 years", "3 days") cause false alarms and are skipped.
        # Decimals ("4.8 LPA", "7.5 LPA") are specific claims, so they are always checked.
        if value >= MIN_CHECKED_NUMBER or decimals > 0:
            found.setdefault(cleaned, (raw, value, decimals))
    return list(found.values())


def number_is_supported(value: float, decimals: int, evidence_numbers: list[float]) -> bool:
    """True if some source number equals `value` once rounded to the same precision.
    Example: report "46932.81" (2 decimals) matches source 46932.8077."""
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(source - value) <= tolerance for source in evidence_numbers)


def check_claims(claims: str, evidence: str) -> EvidenceResult:
    """Check the URLs and numbers in `claims` against the `evidence` text."""
    evidence_urls = extract_urls(evidence)
    evidence_numbers = [value for _, value, _ in extract_numbers(evidence)]
    result = EvidenceResult()

    for url in extract_urls(claims):
        result.checked_urls += 1
        # Prefix match both ways: a report may shorten a long link, or add a trailing path.
        if not any(src.startswith(url) or url.startswith(src) for src in evidence_urls):
            result.unsupported_urls.append(url)

    for raw, value, decimals in extract_numbers(claims):
        result.checked_numbers += 1
        if not number_is_supported(value, decimals, evidence_numbers):
            result.unsupported_numbers.append(raw)
    return result


def check_plan_evidence(plan: Plan) -> dict[str, EvidenceResult]:
    """Evidence check for every completed claim task (analysis / report) in the plan.
    Returns task_id -> result. Empty if the plan has no primary sources to check against."""
    completed = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED and t.result]
    evidence = "\n".join(t.result for t in completed if t.tool in PRIMARY_TOOLS)
    if not evidence:
        return {}  # a pure reasoning goal: nothing to check against
    return {t.id: check_claims(t.result, evidence) for t in completed if t.tool in CLAIM_TOOLS}
