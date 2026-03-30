from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config
from app.notion import NotionClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Notion schema for the genome editing literature tracker")
    parser.add_argument("--apply", action="store_true", help="Actually patch the data source schema")
    args = parser.parse_args()

    config = load_config(require_openai=False)
    if not config.notion_enabled:
        raise SystemExit("NOTION_API_KEY and NOTION_DATABASE_ID must be set.")

    notion = NotionClient(
        api_key=config.notion_api_key,
        database_id=config.notion_database_id,
        notion_version=config.notion_version,
        reader_language=config.reader_language,
    )
    data_source_id = notion.get_primary_data_source_id()
    data_source = notion.retrieve_data_source(data_source_id)
    title_property = notion.detect_title_property_name(data_source)

    print(f"database_id      : {config.notion_database_id}")
    print(f"data_source_id   : {data_source_id}")
    print(f"title_property   : {title_property}")
    print("current_properties:")
    print(json.dumps(sorted(data_source.get("properties", {}).keys()), ensure_ascii=False, indent=2))
    print("\ncurrent_property_types:")
    print(json.dumps({k: v.get("type") for k, v in data_source.get("properties", {}).items()}, ensure_ascii=False, indent=2))

    if args.apply:
        updated = notion.ensure_schema(data_source_id)
        print("\nupdated_properties:")
        print(json.dumps(sorted(updated.get("properties", {}).keys()), ensure_ascii=False, indent=2))
        print("\nupdated_property_types:")
        print(json.dumps({k: v.get("type") for k, v in updated.get("properties", {}).items()}, ensure_ascii=False, indent=2))
    else:
        print("\nDry run only. Re-run with --apply to patch missing properties.")


if __name__ == "__main__":
    main()
