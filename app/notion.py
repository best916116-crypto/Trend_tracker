from __future__ import annotations

import json
from typing import Any

import requests

from app.keywords import (
    ALL_TRACKER_JOURNALS,
    FAST_FOLLOWER_TYPES,
    LANE_OPTIONS,
    SOURCE_OPTIONS,
    STATUS_OPTIONS,
    TOPIC_TERMS,
)
from app.models import ReviewedArticle, normalize_title
from app.prescore import extract_paper_keywords


REQUIRED_PROPERTIES: dict[str, dict[str, Any]] = {
    "Journal": {"select": {"options": [{"name": journal} for journal in ALL_TRACKER_JOURNALS]}},
    "Published": {"date": {}},
    "DOI/URL": {"url": {}},
    "PMID": {"rich_text": {}},
    "Lane": {"select": {"options": [{"name": lane} for lane in LANE_OPTIONS]}},
    "Prescore": {"number": {"format": "number"}},
    "LLM Priority": {"number": {"format": "number"}},
    "Topic": {"multi_select": {"options": [{"name": topic} for topic in TOPIC_TERMS]}},
    "5-line Review": {"rich_text": {}},
    "Why It Matters": {"rich_text": {}},
    "Best Fast-Follower": {"rich_text": {}},
    "FF Type": {"select": {"options": [{"name": option} for option in FAST_FOLLOWER_TYPES]}},
    "FF Score": {"number": {"format": "number"}},
    "FF Rank": {"select": {"options": [{"name": "S"}, {"name": "A"}, {"name": "B"}, {"name": "C"}]}},
    "Share Blurb": {"rich_text": {}},
    "Status": {"select": {"options": [{"name": option} for option in STATUS_OPTIONS]}},
    "Discuss This Week": {"checkbox": {}},
    "Source": {"multi_select": {"options": [{"name": option} for option in SOURCE_OPTIONS]}},
    "Paper Keywords": {"rich_text": {}},
    "Gate Reason": {"rich_text": {}},
    "Matched Keywords": {"rich_text": {}},
    "Watch Authors": {"rich_text": {}},
    "Watch Basis": {"rich_text": {}},
    "Corresponding Authors": {"rich_text": {}},
}


class NotionClient:
    def __init__(self, api_key: str, database_id: str, notion_version: str = "2026-03-11", reader_language: str = "ko") -> None:
        self.database_id = database_id
        self.reader_language = reader_language
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
            }
        )

    def retrieve_database(self) -> dict[str, Any]:
        response = self.session.get(f"https://api.notion.com/v1/databases/{self.database_id}", timeout=60)
        response.raise_for_status()
        return response.json()

    def get_primary_data_source_id(self) -> str:
        db = self.retrieve_database()
        data_sources = db.get("data_sources", [])
        if not data_sources:
            raise RuntimeError("No data_sources found under the database. Share the original database with the integration.")
        return data_sources[0]["id"]

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        response = self.session.get(f"https://api.notion.com/v1/data_sources/{data_source_id}", timeout=60)
        response.raise_for_status()
        return response.json()

    def detect_title_property_name(self, data_source: dict[str, Any]) -> str:
        for name, prop in data_source.get("properties", {}).items():
            if prop.get("type") == "title":
                return name
        raise RuntimeError("Could not detect the title property in the Notion data source.")

    def ensure_schema(self, data_source_id: str) -> dict[str, Any]:
        current = self.retrieve_data_source(data_source_id)
        properties = current.get("properties", {})
        patch: dict[str, Any] = {}

        for name, schema in REQUIRED_PROPERTIES.items():
            if name not in properties:
                patch[name] = schema
                continue

            current_type = properties[name].get("type")
            if current_type not in schema:
                continue

            current_options = properties[name].get(current_type, {}).get("options")
            desired_options = schema.get(current_type, {}).get("options")
            if not current_options or not desired_options:
                continue

            existing_option_names = {opt.get("name") for opt in current_options}
            merged_options = list(current_options)
            for option in desired_options:
                if option.get("name") not in existing_option_names:
                    merged_options.append(option)
            if len(merged_options) != len(current_options):
                patch[name] = {current_type: {"options": merged_options}}

        if patch:
            response = self.session.patch(
                f"https://api.notion.com/v1/data_sources/{data_source_id}",
                json={"properties": patch},
                timeout=60,
            )
            response.raise_for_status()
            current = response.json()
        return current

    def build_existing_index(self, data_source_id: str, title_property: str) -> set[str]:
        index: set[str] = set()
        has_more = True
        cursor: str | None = None
        while has_more:
            body: dict[str, Any] = {
                "page_size": 100,
                "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            }
            if cursor:
                body["start_cursor"] = cursor
            response = self.session.post(
                f"https://api.notion.com/v1/data_sources/{data_source_id}/query",
                json=body,
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            for page in payload.get("results", []):
                props = page.get("properties", {})
                title = extract_title_property(props.get(title_property))
                doi_url = extract_url_property(props.get("DOI/URL"))
                if title:
                    index.add(normalize_title(title))
                if doi_url:
                    index.add(doi_url.lower().strip())
            has_more = payload.get("has_more", False)
            cursor = payload.get("next_cursor")
        return index

    def create_review_page(self, data_source_id: str, title_property: str, item: ReviewedArticle) -> dict[str, Any]:
        article = item.article
        prescore = item.prescore
        review = item.review

        gate_or_matches = prescore.gate_matches or [f"match:{kw}" for kw in prescore.matched_keywords]
        paper_keywords = extract_paper_keywords(article)
        data_source = self.retrieve_data_source(data_source_id)
        property_types = {name: prop.get("type") for name, prop in data_source.get("properties", {}).items()}

        desired_props: dict[str, tuple[str, Any]] = {
            title_property: ("title", title_value(article.title)),
            "Journal": ("select", select_value(article.journal)),
            "Published": ("date", date_value(article.published.isoformat() if article.published else "")),
            "DOI/URL": ("url", {"url": article.url or (f"https://doi.org/{article.doi}" if article.doi else None)}),
            "PMID": ("rich_text", rich_text_value(article.pmid)),
            "Lane": ("select", select_value(review.lane or prescore.lane)),
            "Prescore": ("number", {"number": prescore.score}),
            "LLM Priority": ("number", {"number": review.llm_priority}),
            "Topic": ("multi_select", multi_select_value(review.key_topics)),
            "5-line Review": ("rich_text", rich_text_value(format_review_lines(review.paper_tldr_5_lines))),
            "Why It Matters": ("rich_text", rich_text_value(review.why_it_matters_to_our_lab)),
            "Best Fast-Follower": ("rich_text", rich_text_value(format_best_fast_follower_field(review.best_fast_follower_title, review.best_fast_follower_rationale))),
            "FF Type": ("select", select_value(review.fast_follower_type)),
            "FF Score": ("number", {"number": review.ff_score}),
            "FF Rank": ("select", select_value(review.ff_rank)),
            "Share Blurb": ("rich_text", rich_text_value(review.share_blurb_1line)),
            "Status": ("select", select_value("new")),
            "Discuss This Week": ("checkbox", {"checkbox": review.ff_rank in {"S", "A"}}),
            "Source": ("multi_select", multi_select_value(article.source_tags)),
            "Paper Keywords": ("rich_text", rich_text_value(", ".join(paper_keywords[:25]))),
            "Gate Reason": ("rich_text", rich_text_value(", ".join(prescore.gate_matches[:20]))),
            "Matched Keywords": ("rich_text", rich_text_value(", ".join(gate_or_matches[:25]))),
            "Watch Authors": ("rich_text", rich_text_value(", ".join(article.watch_author_matches[:12]))),
            "Watch Basis": ("rich_text", rich_text_value(", ".join(article.watch_author_match_basis[:12]))),
            "Corresponding Authors": ("rich_text", rich_text_value(", ".join(article.corresponding_authors[:12]))),
        }

        props = adapt_properties_to_schema(desired_props, property_types)
        body = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": props,
            "children": build_page_blocks(item, self.reader_language),
        }
        response = self.session.post("https://api.notion.com/v1/pages", json=body, timeout=60)
        if not response.ok:
            detail = extract_notion_error(response)
            raise RuntimeError(f"Notion page create failed ({response.status_code}): {detail}")
        return response.json()


def safe_text(text: str, limit: int = 1900) -> str:
    text = " ".join((text or "").replace("\t", " ").split())
    return text[:limit]


def clean_option_name(text: str, limit: int = 100) -> str:
    text = (text or "").replace(",", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = " ".join(text.split())
    return text[:limit].strip()


def title_value(text: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": safe_text(text, 1900) or "Untitled"}}]}


def rich_text_value(text: str) -> dict[str, Any]:
    text = safe_text(text)
    if not text:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": text}}]}


def select_value(name: str) -> dict[str, Any]:
    cleaned = clean_option_name(name, 100)
    if not cleaned:
        return {"select": None}
    return {"select": {"name": cleaned}}


def multi_select_value(values: list[str]) -> dict[str, Any]:
    unique = []
    seen = set()
    for value in values:
        cleaned = clean_option_name(value, 100)
        if cleaned and cleaned not in seen:
            unique.append({"name": cleaned})
            seen.add(cleaned)
    return {"multi_select": unique}


def date_value(value: str) -> dict[str, Any]:
    if not value:
        return {"date": None}
    return {"date": {"start": value}}


def extract_title_property(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    fragments = prop.get("title", [])
    return "".join(fragment.get("plain_text", "") for fragment in fragments).strip()


def extract_url_property(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    return (prop.get("url") or "").strip()


def format_review_lines(lines: list[str]) -> str:
    cleaned = [safe_text(line, 300) for line in lines if safe_text(line, 300)]
    if not cleaned:
        return ""
    return "\n".join(f"• {line}" for line in cleaned)


def format_best_fast_follower_field(title: str, rationale: str) -> str:
    title = safe_text(title, 300)
    rationale = safe_text(rationale, 1500)
    if title and rationale:
        return f"{title}\n{rationale}"
    return title or rationale


def localized_headings(reader_language: str) -> dict[str, str]:
    if reader_language.lower().startswith("ko"):
        return {
            "share": "한줄 공유",
            "tldr": "5줄 핵심 요약",
            "why": "왜 우리 랩에 중요한가",
            "takeaway": "기술적 핵심",
            "ff": "베스트 fast-follower",
            "first_experiment": "첫 실험 제안",
            "scoring": "점수",
            "red_flags": "주의할 점",
            "paper_keywords": "논문 키워드",
            "gate_reason": "필터 통과 근거",
            "watch_authors": "주목 PI / watch author",
            "corresponding_authors": "교신저자 후보",
            "metadata": "메타데이터",
        }
    return {
        "share": "Share blurb",
        "tldr": "TL;DR",
        "why": "Why it matters to our lab",
        "takeaway": "Technical takeaway",
        "ff": "Best fast-follower",
        "first_experiment": "First experiment",
        "scoring": "Scoring",
        "red_flags": "Red flags",
        "paper_keywords": "Paper keywords",
        "gate_reason": "Gate reason",
        "watch_authors": "Watch authors",
        "corresponding_authors": "Corresponding-author candidates",
        "metadata": "Metadata",
    }


def build_page_blocks(item: ReviewedArticle, reader_language: str = "ko") -> list[dict[str, Any]]:
    article = item.article
    review = item.review
    prescore = item.prescore

    headings = localized_headings(reader_language)
    blocks: list[dict[str, Any]] = []
    blocks.append(heading_block(headings["share"]))
    blocks.append(paragraph_block(review.share_blurb_1line))
    blocks.append(heading_block(headings["tldr"]))
    blocks.extend(bulleted_list(review.paper_tldr_5_lines))
    blocks.append(heading_block(headings["why"]))
    blocks.append(paragraph_block(review.why_it_matters_to_our_lab))
    blocks.append(heading_block(headings["takeaway"]))
    blocks.append(paragraph_block(review.technical_takeaway))
    blocks.append(heading_block(headings["ff"]))
    blocks.append(paragraph_block(format_best_fast_follower_field(review.best_fast_follower_title, review.best_fast_follower_rationale)))
    blocks.append(heading_block(headings["first_experiment"]))
    blocks.append(paragraph_block(review.first_experiment))
    blocks.append(heading_block(headings["scoring"]))
    blocks.append(
        paragraph_block(
            f"Rank score: {prescore.score} | LLM Priority: {review.llm_priority} | FF Score: {review.ff_score} | FF Rank: {review.ff_rank}"
        )
    )
    blocks.append(heading_block(headings["red_flags"]))
    blocks.extend(bulleted_list(review.red_flags))
    blocks.append(heading_block(headings["paper_keywords"]))
    blocks.append(paragraph_block(", ".join(extract_paper_keywords(article)) or "-"))
    blocks.append(heading_block(headings["gate_reason"]))
    blocks.append(paragraph_block(", ".join(prescore.gate_matches) or "-"))
    blocks.append(heading_block(headings["watch_authors"]))
    blocks.append(paragraph_block(", ".join(article.watch_author_matches) or "-"))
    blocks.append(heading_block(headings["corresponding_authors"]))
    blocks.append(paragraph_block(", ".join(article.corresponding_authors) or "-"))
    blocks.append(heading_block(headings["metadata"]))
    blocks.append(
        paragraph_block(
            json.dumps(
                {
                    "journal": article.journal,
                    "published": article.published.isoformat() if article.published else None,
                    "doi": article.doi or None,
                    "pmid": article.pmid or None,
                    "lane": review.lane,
                    "article_keywords": article.keywords[:25],
                    "paper_keywords": extract_paper_keywords(article),
                    "gate_matches": prescore.gate_matches,
                    "matched_keywords": prescore.matched_keywords,
                    "watch_author_matches": article.watch_author_matches,
                    "watch_author_match_basis": article.watch_author_match_basis,
                    "corresponding_authors": article.corresponding_authors[:12],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    )
    return blocks


def heading_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": safe_text(text)}}]},
    }


def paragraph_block(text: str) -> dict[str, Any]:
    text = safe_text(text)
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text or "-"}}]},
    }


def bulleted_list(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in lines:
        blocks.append(
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": safe_text(line)}}]
                },
            }
        )
    return blocks or [paragraph_block("-")]


def adapt_properties_to_schema(desired_props: dict[str, tuple[str, Any]], property_types: dict[str, str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for name, (expected_type, value) in desired_props.items():
        actual_type = property_types.get(name)
        if not actual_type:
            continue
        if actual_type == expected_type:
            props[name] = value
            continue
        adapted = adapt_property_value(expected_type, actual_type, value)
        if adapted is not None:
            props[name] = adapted
    return props


def adapt_property_value(expected_type: str, actual_type: str, value: dict[str, Any]) -> dict[str, Any] | None:
    if expected_type == "select" and actual_type == "status":
        selected = ((value.get("select") or {}).get("name") or "").strip()
        return {"status": {"name": selected}} if selected else {"status": None}
    if actual_type == "rich_text":
        return rich_text_value(flatten_property_value(value))
    if actual_type == "title":
        return title_value(flatten_property_value(value))
    if actual_type == "url":
        flattened = flatten_property_value(value)
        return {"url": flattened or None}
    if actual_type == "checkbox":
        flattened = flatten_property_value(value).lower()
        return {"checkbox": flattened in {"true", "1", "yes", "y", "checked"}}
    if actual_type == "number":
        try:
            return {"number": float(flatten_property_value(value))}
        except Exception:
            return None
    if actual_type == "date":
        flattened = flatten_property_value(value)
        return date_value(flattened)
    if actual_type == "select":
        return select_value(flatten_property_value(value))
    if actual_type == "multi_select":
        flattened = flatten_property_value(value)
        parts = [part.strip() for part in flattened.split(",") if part.strip()]
        return multi_select_value(parts)
    return None


def flatten_property_value(value: dict[str, Any]) -> str:
    if "rich_text" in value:
        parts = []
        for item in value.get("rich_text", []):
            parts.append(((item.get("text") or {}).get("content") or "").strip())
        return " ".join(part for part in parts if part).strip()
    if "title" in value:
        parts = []
        for item in value.get("title", []):
            parts.append(((item.get("text") or {}).get("content") or "").strip())
        return " ".join(part for part in parts if part).strip()
    if "select" in value:
        return ((value.get("select") or {}).get("name") or "").strip()
    if "status" in value:
        return ((value.get("status") or {}).get("name") or "").strip()
    if "multi_select" in value:
        return ", ".join((item.get("name") or "").strip() for item in value.get("multi_select", []) if (item.get("name") or "").strip())
    if "url" in value:
        return (value.get("url") or "").strip()
    if "date" in value:
        date_obj = value.get("date") or {}
        return (date_obj.get("start") or "").strip()
    if "number" in value:
        number = value.get("number")
        return "" if number is None else str(number)
    if "checkbox" in value:
        return "true" if value.get("checkbox") else "false"
    return ""


def extract_notion_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text[:2000]
    code = payload.get("code") or "unknown_error"
    message = payload.get("message") or json.dumps(payload, ensure_ascii=False)
    additional = payload.get("additional_data")
    if additional:
        return f"{code}: {message} | additional_data={json.dumps(additional, ensure_ascii=False)}"
    return f"{code}: {message}"
