"""Compiler error type."""

from collections.abc import Sequence

from open_mapping.model.issues import Issue, sort_issues


class OpenMappingError(Exception):
    """Raised when one or more stable issues describe a domain failure."""

    def __init__(self, issues: Sequence[Issue]) -> None:
        ordered = sort_issues(issues)
        self.issues = ordered
        super().__init__("; ".join(f"{issue.code.value}: {issue.message}" for issue in ordered))
