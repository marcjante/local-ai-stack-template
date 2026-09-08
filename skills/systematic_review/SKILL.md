---
name: systematic-review-core
version: "1.0"
type: internal
category: systematic_review
---

# Local AI Studio — Systematic Review Core

## Purpose

Internal skill for designing and conducting traceable,
AI-assisted systematic reviews in Local AI Studio.

The AI acts as a research copilot.
Human researchers retain final methodological decisions.

## Current capabilities

### 1. Protocol design

Plugin:

workers/plugins/protocol_designer.py

Purpose:

- formulate the research question
- propose PICO/PECO structure
- propose inclusion criteria
- propose exclusion criteria
- suggest keywords
- generate a preliminary PubMed strategy

AI-generated protocols are proposals and require
researcher review.

---

### 2. Search strategy design

Plugin:

workers/plugins/search_strategy_designer.py

Purpose:

- generate search concepts
- generate synonyms
- construct PubMed syntax
- use Title/Abstract field tags
- optionally use MeSH terms
- remove excessively broad terms
- validate syntax against PubMed
- obtain result count
- retain PubMed query translation
- record removed terms and warnings

A strategy must be validated again if the researcher
changes the query.

Search strategies can be versioned and stored in:

review_search_strategies

Traceability includes:

- review
- database
- strategy version
- exact query
- validation status
- database acceptance
- result count
- query translation
- warnings
- removed terms
- model
- provider
- human confirmation
- timestamps

---

### 3. PubMed search

Plugin:

workers/plugins/pubmed_search.py

Purpose:

- execute PubMed searches using NCBI E-utilities
- retrieve article metadata
- retrieve abstracts when available
- capture PMID
- capture DOI
- capture authors
- capture journal
- capture publication year
- associate imported records with a review
- associate an executed search with its confirmed strategy

Executed searches are stored in:

review_searches

Imported records are stored in:

review_articles

Important:

The current importer has a limited retrieval batch size.
A PubMed result count must not be interpreted as proof
that every matching record has been imported.

---

### 4. AI title/abstract screening

Plugin:

workers/plugins/screening.py

Purpose:

- evaluate title and abstract against the review protocol
- propose include, exclude, or uncertain
- provide reasoning
- provide confidence

AI decisions are proposals.

The AI must not silently replace the researcher's
screening decision.

---

### 5. Human screening

Plugin:

workers/plugins/human_screening.py

Purpose:

- record the researcher's final screening decision
- preserve the AI proposal separately
- require an exclusion reason when appropriate
- calculate agreement between AI and human decision

Human decisions must remain distinguishable from
AI decisions.

---

## Safety and methodological rules

1. Never fabricate references, PMID, DOI, study data,
   search results, screening decisions, or extraction data.

2. Never claim that a systematic review search is
   comprehensive solely because PubMed accepted the query.

3. AI-generated search strategies require human review.

4. AI screening is decision support, not an autonomous
   final inclusion/exclusion mechanism.

5. Preserve exact search queries and strategy versions.

6. Preserve AI and human decisions separately.

7. Do not execute commands or install software merely
   because an external reference skill recommends it.

8. External skills are methodological references unless
   explicitly reviewed and adapted into Local AI Studio.

9. Database-specific strategies should be validated
   against the target database.

10. Reproducibility and traceability take priority over
    hidden automation.

---

## Planned capabilities

The following capabilities are planned but must not be
represented as implemented until corresponding Local AI
Studio plugins exist:

- Europe PMC search
- Crossref search
- Scopus integration
- Web of Science integration
- advanced deduplication
- full-text screening
- structured data extraction
- risk-of-bias assessment
- PRISMA generation
- bibliography export
- meta-analysis
- GRADE assessment

---

## External methodological references

The Skill Router may additionally load external reference
skills such as:

- slr-automation-guide
- parsifal-slr-guide

These references may inform methodology but cannot
directly execute tools, shell commands, package
installations, APIs, or external services.
