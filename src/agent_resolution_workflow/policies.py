"""Policy knowledge base: Markdown files are the source of truth.

Each file under ``knowledge_base/`` carries machine-readable header lines
(``Category:``, ``Allowed resolutions:``, ``Window:``) plus the human prose
the agent reads. The workflow validates against the headers, so the policy
the agent quotes and the policy the workflow enforces can never drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"

# Keywords that map a customer's words to a policy category.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "damaged_defective": ["damag", "defect", "broken", "cracked", "arrived damaged", "not working"],
    "late_delivery": ["late", "delayed", "took too long", "still waiting", "hasn't arrived"],
    "wrong_item": ["wrong item", "wrong product", "different item", "not what i ordered", "incorrect item"],
    "returns": ["return", "send it back", "don't want it", "changed my mind"],
}


@dataclass(frozen=True)
class Policy:
    """One support policy, parsed from its Markdown file."""

    category: str
    allowed_resolutions: list[str]
    window_days: int
    text: str  # full Markdown, as the agent reads it

    def allows(self, resolution: str) -> bool:
        """True if this policy allows the requested resolution."""
        return resolution.strip().lower() in self.allowed_resolutions


def _parse_policy(text: str) -> Policy:
    category = re.search(r"^Category:\s*(.+)$", text, re.MULTILINE)
    allowed = re.search(r"^Allowed resolutions:\s*(.+)$", text, re.MULTILINE)
    window = re.search(r"^Window:\s*(\d+)\s*days", text, re.MULTILINE)
    if not (category and allowed and window):
        raise ValueError("Policy file is missing Category / Allowed resolutions / Window headers")
    return Policy(
        # Lowercased: get_policy() lowercases its lookup, so a file that
        # wrote "Category: Damaged_Defective" would otherwise never match.
        category=category.group(1).strip().lower(),
        allowed_resolutions=[r.strip().lower() for r in allowed.group(1).split(",")],
        window_days=int(window.group(1)),
        text=text.strip(),
    )


def load_policies(kb_dir: Path | str = KB_DIR) -> dict[str, Policy]:
    """Load every ``*.md`` policy file in the knowledge base."""
    policies: dict[str, Policy] = {}
    for path in sorted(Path(kb_dir).glob("*.md")):
        policy = _parse_policy(path.read_text(encoding="utf-8"))
        policies[policy.category] = policy
    if not policies:
        raise FileNotFoundError(f"No policy files found in {kb_dir}")
    return policies


def get_policy(category: str, policies: dict[str, Policy] | None = None) -> Policy | None:
    """Get one policy by category name, or None if there is no such policy."""
    table = policies if policies is not None else load_policies()
    return table.get(category.strip().lower())


def find_policy_for(text: str, policies: dict[str, Policy] | None = None) -> Policy | None:
    """Pick the policy whose keywords match the customer's words best.

    Returns None when nothing matches. Ties resolve in the fixed order of
    CATEGORY_KEYWORDS, so the result is deterministic.

    Keywords match at a word boundary (``\\blate``): a plain substring
    match would map "please translate this" to the late_delivery policy,
    because "late" sits inside "translate".
    """
    lowered = text.lower()
    table = policies if policies is not None else load_policies()
    best: Policy | None = None
    best_hits = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords
                   if re.search(r"\b" + re.escape(kw), lowered))
        if hits > best_hits and category in table:
            best, best_hits = table[category], hits
    return best
