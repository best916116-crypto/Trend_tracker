from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Config
from app.keywords import DEFAULT_JOURNAL_PRESET, WATCHED_AUTHOR_ALIASES, resolve_journal_preset
from app.models import PipelineRun, ReviewedArticle
from app.normalize import dedupe_articles
from app.notion import NotionClient
from app.prescore import prescore_article, sort_review_candidates
from app.sources.crossref import CrossrefClient
from app.sources.pubmed import PubMedClient

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_pipeline(
    config: Config,
    days_back: int | None = None,
    journals: list[str] | None = None,
    journal_preset: str | None = None,
    llm_limit: int | None = None,
    push_to_notion: bool = True,
    use_pubmed_enrichment: bool | None = None,
    min_gated_papers: int | None = None,
    max_days_back: int | None = None,
    expand_step_days: int | None = None,
) -> PipelineRun:
    requested_days_back = days_back if days_back is not None else config.days_back
    llm_limit = llm_limit if llm_limit is not None else config.llm_review_limit
    min_gated_papers = min_gated_papers if min_gated_papers is not None else config.min_gated_papers
    max_days_back = max_days_back if max_days_back is not None else config.max_days_back
    expand_step_days = expand_step_days if expand_step_days is not None else config.expand_step_days
    use_pubmed_enrichment = config.enable_pubmed_enrichment if use_pubmed_enrichment is None else use_pubmed_enrichment
    resolved_journals = journals or resolve_journal_preset(journal_preset or config.journal_preset or DEFAULT_JOURNAL_PRESET)

    run = PipelineRun(
        run_started_at=datetime.now(timezone.utc),
        journals=resolved_journals,
        requested_days_back=requested_days_back,
        actual_days_back=requested_days_back,
        min_gated_papers=min_gated_papers,
    )

    crossref = CrossrefClient(mailto=config.crossref_mailto)
    pubmed = PubMedClient(
        email=config.ncbi_email,
        api_key=config.ncbi_api_key,
        tool=config.ncbi_tool,
        max_retries=config.pubmed_max_retries,
        backoff_factor=config.pubmed_backoff_factor,
    )
    from app.review_llm import LLMReviewer

    reviewer = LLMReviewer(config)

    current_days_back = max(1, requested_days_back)
    final_scored: list[tuple] = []
    final_dropped: list[dict] = []
    final_collected = 0
    final_deduped = 0
    final_enriched_count = 0
    final_pubmed_failed = 0

    while True:
        journal_articles = crossref.fetch_recent_cns_articles(
            days_back=current_days_back,
            rows_per_journal=config.crossref_rows_per_journal,
            journals=resolved_journals,
            journal_preset=journal_preset or config.journal_preset,
        )
        author_articles = crossref.fetch_recent_author_articles(
            days_back=current_days_back,
            author_names=list(WATCHED_AUTHOR_ALIASES.keys()),
            rows_per_author=config.crossref_rows_per_author,
        )

        articles = journal_articles + author_articles
        deduped = dedupe_articles(articles)

        enriched = []
        enriched_count = 0
        pubmed_failed_count = 0
        for article in deduped:
            before_abstract = bool(article.abstract)
            if use_pubmed_enrichment:
                before_warnings = len(article.raw.get("warnings", []))
                article = pubmed.enrich_article(article)
                after_warnings = len(article.raw.get("warnings", []))
                if after_warnings > before_warnings:
                    pubmed_failed_count += 1
            if bool(article.abstract) and not before_abstract:
                enriched_count += 1
            enriched.append(article)

        scored = []
        dropped_articles = []
        for article in enriched:
            prescore = prescore_article(article)
            if prescore.drop_reason and not prescore.gate_passed:
                dropped_articles.append(
                    {
                        "title": article.title,
                        "journal": article.journal,
                        "drop_reason": prescore.drop_reason,
                        "gate_matches": prescore.gate_matches,
                        "bucket_scores": prescore.bucket_scores,
                        "watch_author_matches": article.watch_author_matches,
                    }
                )
                continue
            if prescore.gate_passed:
                scored.append((article, prescore))
            else:
                dropped_articles.append(
                    {
                        "title": article.title,
                        "journal": article.journal,
                        "drop_reason": prescore.drop_reason or "no_gate_match:title_or_keywords_or_watch_author",
                        "gate_matches": prescore.gate_matches,
                        "bucket_scores": prescore.bucket_scores,
                        "watch_author_matches": article.watch_author_matches,
                    }
                )

        run.expansion_history.append(
            {
                "days_back": current_days_back,
                "collected": len(articles),
                "deduped": len(deduped),
                "gated": len(scored),
                "abstracts_enriched": enriched_count,
                "pubmed_failures": pubmed_failed_count,
            }
        )

        final_scored = scored
        final_dropped = dropped_articles
        final_collected = len(articles)
        final_deduped = len(deduped)
        final_enriched_count = enriched_count
        final_pubmed_failed = pubmed_failed_count
        run.actual_days_back = current_days_back

        if min_gated_papers <= 0 or len(scored) >= min_gated_papers or current_days_back >= max_days_back:
            break

        next_days_back = min(max_days_back, current_days_back + max(1, expand_step_days))
        if next_days_back == current_days_back:
            break
        current_days_back = next_days_back

    run.collected_count = final_collected
    run.deduped_count = final_deduped
    run.enriched_count = final_enriched_count
    run.pubmed_failed_count = final_pubmed_failed
    run.watchlist_count = len(final_scored)
    run.dropped_articles = final_dropped

    if use_pubmed_enrichment and run.pubmed_failed_count:
        run.warnings.append(
            f"PubMed enrichment failed for {run.pubmed_failed_count} article(s); pipeline continued with Crossref metadata."
        )
    if run.actual_days_back > run.requested_days_back:
        run.warnings.append(
            f"Window expanded from {run.requested_days_back} to {run.actual_days_back} days to reach at least {run.min_gated_papers} gated papers."
        )
    if min_gated_papers > 0 and run.watchlist_count < min_gated_papers:
        run.warnings.append(
            f"Reached max_days_back={max_days_back} but only found {run.watchlist_count} gated papers."
        )

    review_candidates = sort_review_candidates(final_scored)[:llm_limit]

    reviewed_items: list[ReviewedArticle] = []
    for article, prescore in review_candidates:
        review = reviewer.review(article, prescore)
        reviewed_items.append(ReviewedArticle(article=article, prescore=prescore, review=review))

    run.reviewed_articles = reviewed_items
    run.reviewed_count = len(reviewed_items)

    if push_to_notion and config.notion_enabled:
        notion = NotionClient(
            api_key=config.notion_api_key,
            database_id=config.notion_database_id,
            notion_version=config.notion_version,
            reader_language=config.reader_language,
        )
        data_source_id = notion.get_primary_data_source_id()
        data_source = notion.ensure_schema(data_source_id)
        title_property = notion.detect_title_property_name(data_source)
        existing_index = notion.build_existing_index(data_source_id, title_property)

        for reviewed in reviewed_items:
            article = reviewed.article
            doi_key = (article.url or (f"https://doi.org/{article.doi}" if article.doi else "")).lower().strip()
            normalized_title = article.canonical_id()
            if (doi_key and doi_key in existing_index) or normalized_title in existing_index:
                run.notion_skipped_duplicates += 1
                continue
            notion.create_review_page(data_source_id, title_property, reviewed)
            run.notion_created_count += 1
            if doi_key:
                existing_index.add(doi_key)
            existing_index.add(normalized_title)

    run.run_finished_at = datetime.now(timezone.utc)
    write_outputs(run)
    return run


def write_outputs(run: PipelineRun) -> None:
    stamp = run.run_started_at.strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"run_{stamp}.json"
    md_path = OUTPUT_DIR / f"summary_{stamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(run.to_dict(), f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown_summary(run))


def render_markdown_summary(run: PipelineRun) -> str:
    lines = [
        f"# High-Impact Genome Editing Literature Tracker Summary ({run.run_started_at.isoformat()} UTC)",
        "",
        f"- Journals in run: {len(run.journals)}",
        f"- Requested days back: {run.requested_days_back}",
        f"- Actual days back used: {run.actual_days_back}",
        f"- Minimum gated papers target: {run.min_gated_papers}",
        f"- Collected: {run.collected_count}",
        f"- Deduped: {run.deduped_count}",
        f"- Abstracts enriched from PubMed: {run.enriched_count}",
        f"- PubMed enrichment failures: {run.pubmed_failed_count}",
        f"- Gated / watchlist: {run.watchlist_count}",
        f"- Reviewed: {run.reviewed_count}",
        f"- Notion created: {run.notion_created_count}",
        f"- Notion duplicates skipped: {run.notion_skipped_duplicates}",
        "",
    ]

    if run.expansion_history:
        lines.extend(["## Window expansion history", ""])
        for step in run.expansion_history:
            lines.append(
                f"- days_back={step['days_back']} | collected={step['collected']} | deduped={step['deduped']} | gated={step['gated']} | abstracts_enriched={step['abstracts_enriched']} | pubmed_failures={step['pubmed_failures']}"
            )
        lines.append("")

    if run.warnings:
        lines.extend(["## Warnings", ""])
        for warning in run.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    for idx, reviewed in enumerate(run.reviewed_articles, start=1):
        article = reviewed.article
        prescore = reviewed.prescore
        review = reviewed.review
        lines.extend(
            [
                f"## [{idx}] {article.title}",
                "",
                f"- Journal: {article.journal}",
                f"- Lane: {review.lane}",
                f"- Gate matches: {', '.join(prescore.gate_matches) if prescore.gate_matches else 'N/A'}",
                f"- Watch authors: {', '.join(article.watch_author_matches) if article.watch_author_matches else 'N/A'}",
                f"- Rank / LLM: {prescore.score} / {review.llm_priority}",
                f"- FF Score / Rank: {review.ff_score} / {review.ff_rank}",
                f"- Best Fast-Follower: {review.best_fast_follower_title}",
                "",
                "### 5-line Review",
                "",
            ]
        )
        for line in review.paper_tldr_5_lines:
            lines.append(f"- {line}")
        lines.extend(
            [
                "",
                "### Why It Matters",
                "",
                review.why_it_matters_to_our_lab,
                "",
                "### Technical Takeaway",
                "",
                review.technical_takeaway,
                "",
                "### First Experiment",
                "",
                review.first_experiment,
                "",
            ]
        )

    return "\n".join(lines)
