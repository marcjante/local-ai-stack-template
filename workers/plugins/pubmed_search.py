"""
Plugin PubMed Search

Busca artículos científicos en PubMed usando la API pública de NCBI.
Devuelve PMID, título, autores, revista, año, DOI y abstract cuando están disponibles.
"""

import os
import sys
import requests
import xml.etree.ElementTree as ET

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from db.db import set_status, get_conn  # noqa: E402
from common.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)

QUEUE_NAME = "pubmed_search"
QUEUE_TIMEOUT = 180

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _save_review_search(review_id, query, total_found, articles, strategy_id=None):
    """
    Guarda la búsqueda y los artículos en la revisión sistemática.
    Evita duplicados por PMID y DOI dentro de la misma revisión.
    """
    import json
    import uuid

    search_id = str(uuid.uuid4())

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO review_searches
                (
                    id,
                    review_id,
                    database_name,
                    query,
                    total_found,
                    imported_count,
                    strategy_id
                )
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                search_id,
                review_id,
                "PubMed",
                query,
                total_found,
                0,
                strategy_id,
            ),
        )

        imported = 0

        for article in articles:
            pmid = article.get("pmid") or None
            doi = article.get("doi") or None
            title = article.get("title") or ""

            cur.execute(
                """
                SELECT id
                FROM review_articles
                WHERE review_id = %s
                  AND (
                        (%s IS NOT NULL AND pmid = %s)
                        OR
                        (%s IS NOT NULL AND doi = %s)
                      )
                LIMIT 1
                """,
                (
                    review_id,
                    pmid,
                    pmid,
                    doi,
                    doi,
                ),
            )

            if cur.fetchone():
                continue

            article_id = str(uuid.uuid4())

            cur.execute(
                """
                INSERT INTO review_articles (
                    id,
                    review_id,
                    search_id,
                    pmid,
                    doi,
                    title,
                    abstract,
                    authors,
                    journal,
                    year,
                    screening_status,
                    screening_stage
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    'pending', 'title_abstract'
                )
                """,
                (
                    article_id,
                    review_id,
                    search_id,
                    pmid,
                    doi,
                    title,
                    article.get("abstract") or None,
                    json.dumps(article.get("authors") or []),
                    article.get("journal") or None,
                    article.get("year") or None,
                ),
            )

            imported += 1

        cur.execute(
            """
            UPDATE review_searches
            SET imported_count = %s
            WHERE id = %s
            """,
            (imported, search_id),
        )

    return {
        "search_id": search_id,
        "imported": imported,
    }



def _text(element):
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _parse_article(article_node):
    medline = article_node.find("MedlineCitation")
    pubmed_data = article_node.find("PubmedData")

    if medline is None:
        return {}

    citation = medline.find("Article")
    if citation is None:
        return {}

    pmid = _text(medline.find("PMID"))
    title = _text(citation.find("ArticleTitle"))

    abstract_parts = []
    abstract = citation.find("Abstract")
    if abstract is not None:
        for node in abstract.findall("AbstractText"):
            label = node.attrib.get("Label")
            text = _text(node)
            if text:
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)

    abstract_text = "\n".join(abstract_parts)

    authors = []
    author_list = citation.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            collective = _text(author.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue

            last = _text(author.find("LastName"))
            fore = _text(author.find("ForeName"))
            name = " ".join(x for x in [fore, last] if x)
            if name:
                authors.append(name)

    journal = ""
    journal_node = citation.find("Journal")
    if journal_node is not None:
        journal = _text(journal_node.find("Title"))

    year = ""
    pub_date = citation.find("./Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year = _text(pub_date.find("Year"))
        if not year:
            medline_date = _text(pub_date.find("MedlineDate"))
            if medline_date:
                year = medline_date[:4]

    doi = ""
    if pubmed_data is not None:
        article_id_list = pubmed_data.find("ArticleIdList")
        if article_id_list is not None:
            for article_id in article_id_list.findall("ArticleId"):
                if article_id.attrib.get("IdType") == "doi":
                    doi = _text(article_id)
                    break

    return {
        "pmid": pmid,
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "abstract": abstract_text,
    }


def handle(task_id: str, payload: dict) -> dict:
    query = payload.get("query", "").strip()
    max_results = int(payload.get("max_results", 20))
    review_id = payload.get("review_id")
    strategy_id = payload.get("strategy_id")

    if not query:
        raise ValueError("Falta el campo 'query'")

    max_results = max(1, min(max_results, 100))

    log.info(
        f"Buscando PubMed: query={query}, max_results={max_results}",
        extra={"task_id": task_id},
    )

    set_status(task_id, "running", increment_attempts=True)

    try:
        search_response = requests.get(
            PUBMED_SEARCH_URL,
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": max_results,
            },
            timeout=30,
        )
        search_response.raise_for_status()

        search_data = search_response.json()
        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_found = int(
            search_data.get("esearchresult", {}).get("count", 0)
        )

        if not id_list:
            result = {
                "query": query,
                "total_found": total_found,
                "returned": 0,
                "articles": [],
            }

            set_status(task_id, "completed", result=result)
            return result

        fetch_response = requests.get(
            PUBMED_FETCH_URL,
            params={
                "db": "pubmed",
                "id": ",".join(id_list),
                "retmode": "xml",
            },
            timeout=60,
        )
        fetch_response.raise_for_status()

        root = ET.fromstring(fetch_response.content)

        articles = []
        for node in root.findall("PubmedArticle"):
            article = _parse_article(node)
            if article:
                articles.append(article)

        result = {
            "query": query,
            "total_found": total_found,
            "returned": len(articles),
            "articles": articles,
        }

        if review_id:
            saved = _save_review_search(
                review_id,
                query,
                total_found,
                articles,
                strategy_id=strategy_id,
            )
            result["review_id"] = review_id
            result["search_id"] = saved["search_id"]
            result["imported"] = saved["imported"]

        set_status(task_id, "completed", result=result)

        log.info(
            f"PubMed completado: {len(articles)} artículos",
            extra={"task_id": task_id},
        )

        return result

    except Exception as exc:
        set_status(task_id, "failed", error=str(exc))
        log.error(
            f"PubMed falló: {exc}",
            extra={"task_id": task_id},
        )
        raise
