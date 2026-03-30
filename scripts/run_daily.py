from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config
from app.keywords import JOURNAL_PRESETS
from app.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the high-impact genome editing literature tracker")
    parser.add_argument("--days-back", type=int, default=None, help="How many days back to fetch initially")
    parser.add_argument("--llm-limit", type=int, default=None, help="Maximum number of papers to send to the LLM")
    parser.add_argument(
        "--min-gated",
        type=int,
        default=None,
        help="Minimum number of gated papers to target before stopping window expansion",
    )
    parser.add_argument(
        "--max-days-back",
        type=int,
        default=None,
        help="Maximum days-back limit for adaptive window expansion",
    )
    parser.add_argument(
        "--expand-step-days",
        type=int,
        default=None,
        help="How many days to add each time the window expands",
    )
    parser.add_argument(
        "--journal-preset",
        choices=sorted(JOURNAL_PRESETS.keys()),
        default=None,
        help="Journal pool preset. Default comes from JOURNAL_PRESET in .env.",
    )
    parser.add_argument(
        "--journals",
        nargs="*",
        default=None,
        help="Override journals directly, e.g. --journals Nature Science Cell",
    )
    parser.add_argument("--skip-notion", action="store_true", help="Do not push reviewed papers to Notion")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --skip-notion")
    parser.add_argument("--skip-pubmed", action="store_true", help="Skip PubMed enrichment and use Crossref metadata only")
    args = parser.parse_args()

    config = load_config()
    run = run_pipeline(
        config=config,
        days_back=args.days_back,
        journals=args.journals,
        journal_preset=args.journal_preset,
        llm_limit=args.llm_limit,
        push_to_notion=not (args.skip_notion or args.dry_run),
        use_pubmed_enrichment=not args.skip_pubmed,
        min_gated_papers=args.min_gated,
        max_days_back=args.max_days_back,
        expand_step_days=args.expand_step_days,
    )

    print("=== Run completed ===")
    print(f"Journal preset / count   : {(args.journal_preset or config.journal_preset)} / {len(run.journals)}")
    print(f"Requested days back      : {run.requested_days_back}")
    print(f"Actual days back used    : {run.actual_days_back}")
    print(f"Minimum gated target     : {run.min_gated_papers}")
    print(f"Collected                : {run.collected_count}")
    print(f"Deduped                  : {run.deduped_count}")
    print(f"Abstracts enriched       : {run.enriched_count}")
    print(f"PubMed failures          : {run.pubmed_failed_count}")
    print(f"Gated / watchlist        : {run.watchlist_count}")
    print(f"Reviewed                 : {run.reviewed_count}")
    print(f"Notion created           : {run.notion_created_count}")
    print(f"Notion duplicates        : {run.notion_skipped_duplicates}")

    if run.expansion_history:
        print("\nExpansion history:")
        for step in run.expansion_history:
            print(
                f"- days_back={step['days_back']} | collected={step['collected']} | deduped={step['deduped']} | gated={step['gated']} | abstracts_enriched={step['abstracts_enriched']} | pubmed_failures={step['pubmed_failures']}"
            )

    if run.warnings:
        print("\nWarnings:")
        for warning in run.warnings:
            print(f"- {warning}")

    for idx, reviewed in enumerate(run.reviewed_articles, start=1):
        article = reviewed.article
        review = reviewed.review
        print(f"\n[{idx}] {article.title}")
        print(f"  Journal               : {article.journal}")
        print(f"  Lane                  : {review.lane}")
        print(
            f"  Gate matches          : {', '.join(reviewed.prescore.gate_matches) if reviewed.prescore.gate_matches else 'N/A'}"
        )
        if article.watch_author_matches:
            print(f"  Watch authors         : {', '.join(article.watch_author_matches)}")
            print(f"  Watch basis           : {', '.join(article.watch_author_match_basis)}")
        print(f"  Rank / LLM            : {reviewed.prescore.score} / {review.llm_priority}")
        print(f"  FF Score / Rank       : {review.ff_score} / {review.ff_rank}")
        print(f"  Best FF               : {review.best_fast_follower_title}")


if __name__ == "__main__":
    main()
