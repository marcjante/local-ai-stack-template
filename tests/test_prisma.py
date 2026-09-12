from dashboard.prisma import calculate_prisma


def test_calculate_prisma_basic_flow():
    searches = [
        {
            "database_name": "PubMed",
            "total_found": 120,
            "imported_count": 50,
        },
        {
            "database_name": "Scopus",
            "total_found": 80,
            "imported_count": 30,
        },
    ]

    articles = [
        {
            "id": "a1",
            "is_duplicate": False,
            "title_abstract_status": "include",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "include",
            "final_decision": "include",
        },
        {
            "id": "a2",
            "is_duplicate": False,
            "title_abstract_status": "exclude",
            "full_text_retrieval_status": "not_sought",
            "full_text_status": "not_started",
            "final_decision": None,
        },
        {
            "id": "a3",
            "is_duplicate": False,
            "title_abstract_status": "include",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "exclude",
            "final_decision": "exclude",
            "exclusion_reason_code": "WRONG_POPULATION",
            "exclusion_reason": "Población incorrecta",
        },
        {
            "id": "a4",
            "is_duplicate": True,
            "title_abstract_status": "pending",
            "full_text_retrieval_status": "not_sought",
            "full_text_status": "not_started",
            "final_decision": None,
        },
        {
            "id": "a5",
            "is_duplicate": False,
            "title_abstract_status": "pending",
            "full_text_retrieval_status": "not_sought",
            "full_text_status": "not_started",
            "final_decision": None,
        },
    ]

    prisma = calculate_prisma(searches, articles)

    assert prisma["records_identified"] == 200
    assert prisma["records_imported"] == 80
    assert prisma["duplicates_removed"] == 1
    assert prisma["records_screened"] == 3
    assert prisma["records_excluded"] == 1
    assert prisma["reports_sought"] == 2
    assert prisma["reports_not_retrieved"] == 0
    assert prisma["reports_assessed"] == 2
    assert prisma["reports_excluded"] == 1
    assert prisma["studies_included"] == 1
    assert prisma["exclusion_reasons"] == {
        "WRONG_POPULATION": 1
    }


def test_calculate_prisma_groups_databases():
    searches = [
        {
            "database_name": "PubMed",
            "total_found": 100,
            "imported_count": 40,
        },
        {
            "database_name": "PubMed",
            "total_found": 50,
            "imported_count": 10,
        },
        {
            "database_name": "Embase",
            "total_found": 70,
            "imported_count": 20,
        },
    ]

    prisma = calculate_prisma(searches, [])

    assert prisma["databases"]["PubMed"] == {
        "records_identified": 150,
        "records_imported": 50,
    }

    assert prisma["databases"]["Embase"] == {
        "records_identified": 70,
        "records_imported": 20,
    }


def test_calculate_prisma_counts_exclusion_reasons():
    articles = [
        {
            "is_duplicate": False,
            "title_abstract_status": "include",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "exclude",
            "final_decision": "exclude",
            "exclusion_reason_code": "WRONG_OUTCOME",
        },
        {
            "is_duplicate": False,
            "title_abstract_status": "include",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "exclude",
            "final_decision": "exclude",
            "exclusion_reason_code": "WRONG_OUTCOME",
        },
        {
            "is_duplicate": False,
            "title_abstract_status": "include",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "exclude",
            "final_decision": "exclude",
            "exclusion_reason": "Diseño no elegible",
        },
    ]

    prisma = calculate_prisma([], articles)

    assert prisma["reports_excluded"] == 3
    assert prisma["exclusion_reasons"] == {
        "Diseño no elegible": 1,
        "WRONG_OUTCOME": 2,
    }


def test_calculate_prisma_ignores_duplicates_in_screening_counts():
    articles = [
        {
            "is_duplicate": True,
            "title_abstract_status": "exclude",
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "exclude",
            "final_decision": "exclude",
        }
    ]

    prisma = calculate_prisma([], articles)

    assert prisma["duplicates_removed"] == 1
    assert prisma["records_screened"] == 0
    assert prisma["records_excluded"] == 0
    assert prisma["reports_sought"] == 0
    assert prisma["reports_not_retrieved"] == 0
    assert prisma["reports_assessed"] == 0
    assert prisma["reports_excluded"] == 0
    assert prisma["studies_included"] == 0


def test_calculate_prisma_full_text_retrieval_flow():
    articles = [
        {
            "id": "not-sought",
            "is_duplicate": False,
            "full_text_retrieval_status": "not_sought",
            "full_text_status": "not_started",
        },
        {
            "id": "sought",
            "is_duplicate": False,
            "full_text_retrieval_status": "sought",
            "full_text_status": "pending",
        },
        {
            "id": "retrieved",
            "is_duplicate": False,
            "full_text_retrieval_status": "retrieved",
            "full_text_status": "include",
            "final_decision": "include",
        },
        {
            "id": "not-retrieved",
            "is_duplicate": False,
            "full_text_retrieval_status": "not_retrieved",
            "full_text_status": "pending",
        },
    ]

    prisma = calculate_prisma([], articles)

    assert prisma["reports_sought"] == 3
    assert prisma["reports_not_retrieved"] == 1
    assert prisma["reports_assessed"] == 1
    assert prisma["studies_included"] == 1


def test_calculate_prisma_legacy_full_text_state_fallback():
    articles = [
        {
            "is_duplicate": False,
            "full_text_status": "include",
            "final_decision": "include",
        },
        {
            "is_duplicate": False,
            "full_text_status": "exclude",
            "final_decision": "exclude",
        },
    ]

    prisma = calculate_prisma([], articles)

    assert prisma["reports_sought"] == 2
    assert prisma["reports_not_retrieved"] == 0
    assert prisma["reports_assessed"] == 2
