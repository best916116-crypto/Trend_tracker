# Notion fields

## Reader-facing fields
- **Paper**: paper title
- **Journal**: journal name
- **Published**: publication date
- **Paper Keywords**: paper-reported or extracted keywords
- **Gate Reason**: why the paper passed the initial filter
- **5-line Review**: fast skim summary
- **Why It Matters**: lab-specific relevance
- **Best Fast-Follower**: strongest follow-up idea
- **FF Rank**: fast-follower rank bucket
- **DOI/URL**: canonical paper link
- **Status**: reading / discussion status

## Operational fields
- **Lane**: Genome editing core / Editor engineering / Delivery & translation / Mitochondrial editing / Mitochondrial biology / General biology
- **Prescore**: internal ranking score among gated papers
- **LLM Priority**: LLM-assigned importance
- **Matched Keywords**: additional matched terms used in ranking
- **Watch Authors**: matched watchlist PI names
- **Watch Basis**: why the watch-author match happened
- **Corresponding Authors**: corresponding-author candidates inferred from PubMed affiliation emails
- **Source**: metadata source
- **PMID**: PubMed identifier
- **Discuss This Week**: checkbox for stronger candidates

## Reader-facing language

By default, reader-facing long-form text is written in Korean (`READER_LANGUAGE=ko`).
This applies to:
- `5-line Review`
- `Why It Matters`
- `Best Fast-Follower`
- `Share Blurb`
- Notion page body sections

Metadata fields such as `Journal`, `Lane`, `Topic`, `FF Rank`, and `PMID` stay structured so the database remains stable for filtering and sorting.
