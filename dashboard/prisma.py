"""PRISMA flow calculations for systematic reviews.

This module contains no database access. It receives search/article records
and derives the PRISMA counts from the current review state.
"""

from collections import Counter


def _value(row, key, default=None):
    """Support both dictionaries and mapping-like database rows."""
    try:
        value = row.get(key, default)
    except AttributeError:
        try:
            value = row[key]
        except (KeyError, TypeError):
            return default
    return default if value is None else value


def calculate_prisma(searches, articles):
    """Calculate PRISMA-style flow counts.

    Notes
    -----
    ``reports_not_retrieved`` is intentionally ``None`` because the current
    schema cannot distinguish between a report that has not yet been sought
    and one that was sought but could not be retrieved.
    """

    searches = list(searches or [])
    articles = list(articles or [])

    records_identified = sum(
        int(_value(search, "total_found", 0) or 0)
        for search in searches
    )

    records_imported = sum(
        int(_value(search, "imported_count", 0) or 0)
        for search in searches
    )

    duplicates = [
        article
        for article in articles
        if bool(_value(article, "is_duplicate", False))
    ]

    non_duplicates = [
        article
        for article in articles
        if not bool(_value(article, "is_duplicate", False))
    ]

    records_screened = sum(
        1
        for article in non_duplicates
        if _value(article, "title_abstract_status", "pending")
        != "pending"
    )

    records_excluded = sum(
        1
        for article in non_duplicates
        if _value(article, "title_abstract_status") == "exclude"
    )

    reports_sought = sum(
        1
        for article in non_duplicates
        if _value(article, "full_text_status", "not_started")
        != "not_started"
    )

    reports_assessed = sum(
        1
        for article in non_duplicates
        if _value(article, "full_text_status")
        in {"include", "exclude", "conflict"}
    )

    full_text_excluded = [
        article
        for article in non_duplicates
        if _value(article, "full_text_status") == "exclude"
        and _value(article, "final_decision") == "exclude"
    ]

    studies_included = sum(
        1
        for article in non_duplicates
        if _value(article, "final_decision") == "include"
    )

    exclusion_reasons = Counter()

    for article in full_text_excluded:
        reason = (
            _value(article, "exclusion_reason_code")
            or _value(article, "exclusion_reason")
            or "UNSPECIFIED"
        )
        exclusion_reasons[str(reason)] += 1

    databases = {}

    for search in searches:
        database_name = str(
            _value(search, "database_name", "Unknown")
        )
        entry = databases.setdefault(
            database_name,
            {
                "records_identified": 0,
                "records_imported": 0,
            },
        )
        entry["records_identified"] += int(
            _value(search, "total_found", 0) or 0
        )
        entry["records_imported"] += int(
            _value(search, "imported_count", 0) or 0
        )

    return {
        "records_identified": records_identified,
        "records_imported": records_imported,
        "duplicates_removed": len(duplicates),
        "records_screened": records_screened,
        "records_excluded": records_excluded,
        "reports_sought": reports_sought,
        "reports_not_retrieved": None,
        "reports_assessed": reports_assessed,
        "reports_excluded": len(full_text_excluded),
        "studies_included": studies_included,
        "exclusion_reasons": dict(
            sorted(exclusion_reasons.items())
        ),
        "databases": databases,
    }
