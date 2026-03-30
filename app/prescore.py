from __future__ import annotations

import re
from typing import Iterable

from app.keywords import (
    ABSTRACT_RANK_MULTIPLIER,
    AUTO_PASS_TERMS,
    EXCLUSION_PATTERNS,
    GATE_GROUPS,
    GATE_TERMS,
    KEYWORD_RANK_MULTIPLIER,
    LANE_OPTIONS,
    RANK_BUCKETS,
    TITLE_RANK_MULTIPLIER,
    WATCHED_AUTHOR_ALIASES,
)
from app.models import Article, PrescoreResult


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_person_name(name: str) -> str:
    name = (name or "").lower()
    name = name.replace("–", "-").replace("—", "-")
    name = re.sub(r"[.,()]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _term_pattern(term: str) -> str:
    tokens = [re.escape(tok) for tok in re.split(r"[\s\-]+", term.lower()) if tok]
    if not tokens:
        return r"$^"
    return r"\b" + r"[\s\-]+".join(tokens) + r"\b"


def _contains_term(text: str, term: str) -> bool:
    return re.search(_term_pattern(term), text) is not None


def _find_matches(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _contains_term(text, term)]


def _score_text_segment(text: str, multiplier: int) -> tuple[dict[str, int], list[str]]:
    bucket_scores: dict[str, int] = {bucket_name: 0 for bucket_name in RANK_BUCKETS}
    matched_keywords: list[str] = []

    for bucket_name, bucket_meta in RANK_BUCKETS.items():
        bucket_cap = int(bucket_meta["max"])
        subtotal = 0
        for rule in bucket_meta["patterns"]:  # type: ignore[index]
            if _contains_term(text, rule.term):
                subtotal += rule.weight * multiplier
                matched_keywords.append(rule.term)
        bucket_scores[bucket_name] += min(subtotal, bucket_cap)
    return bucket_scores, matched_keywords


def _merge_bucket_scores(*score_maps: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {bucket_name: 0 for bucket_name in RANK_BUCKETS}
    for bucket_name in merged:
        merged[bucket_name] = min(
            int(RANK_BUCKETS[bucket_name]["max"]),
            sum(score_map.get(bucket_name, 0) for score_map in score_maps),
        )
    return merged


def _exclude_article(article: Article) -> str:
    title = _normalize_text(article.title)
    for pattern in EXCLUSION_PATTERNS:
        if re.search(pattern, title):
            return f"excluded_by_title_pattern:{pattern}"
    if article.crossref_type and article.crossref_type not in {"journal-article"}:
        return f"excluded_by_crossref_type:{article.crossref_type}"
    return ""


_NORMALIZED_WATCHED_AUTHOR_ALIASES = {
    canonical: {_normalize_person_name(alias) for alias in aliases}
    for canonical, aliases in WATCHED_AUTHOR_ALIASES.items()
}


def _watch_author_matches_from_names(names: list[str]) -> list[str]:
    normalized_names = {_normalize_person_name(name) for name in names if name}
    matches: list[str] = []
    for canonical, aliases in _NORMALIZED_WATCHED_AUTHOR_ALIASES.items():
        if normalized_names & aliases:
            matches.append(canonical)
    return matches


def _detect_watch_author_matches(article: Article) -> tuple[list[str], list[str]]:
    matches: list[str] = []
    bases: list[str] = []

    query_name = (article.raw.get("author_query") or "").strip()
    if query_name:
        query_matches = _watch_author_matches_from_names([query_name])
        for match in query_matches:
            if match not in matches:
                matches.append(match)
                bases.append("crossref_author_query")

    direct_author_matches = _watch_author_matches_from_names(article.authors)
    for match in direct_author_matches:
        if match not in matches:
            matches.append(match)
            bases.append("author_list_match")

    corr_matches = _watch_author_matches_from_names(article.corresponding_authors)
    for match in corr_matches:
        if match not in matches:
            matches.append(match)
            bases.append("pubmed_affiliation_email")

    if article.authors:
        last_author_matches = _watch_author_matches_from_names([article.authors[-1]])
        for match in last_author_matches:
            if match not in matches:
                matches.append(match)
                bases.append("last_author_fallback")

    return matches, bases


def _detect_gate_matches(article: Article) -> tuple[list[str], bool, bool, bool, bool, bool]:
    title_text = _normalize_text(article.title)
    keyword_text = _normalize_text(" | ".join(article.keywords))
    abstract_text = _normalize_text(article.abstract)

    title_matches = _find_matches(title_text, GATE_TERMS)
    keyword_matches = _find_matches(keyword_text, GATE_TERMS)

    gate_matches = [f"title:{term}" for term in title_matches] + [f"keyword:{term}" for term in keyword_matches]

    auto_pass = any(
        _contains_term(title_text, term) or _contains_term(keyword_text, term) or _contains_term(abstract_text, term)
        for term in AUTO_PASS_TERMS
    )

    editing_hit = any(term in title_matches or term in keyword_matches for term in GATE_GROUPS["genome_editing"])
    engineering_hit = any(term in title_matches or term in keyword_matches for term in GATE_GROUPS["engineering"])
    delivery_hit = any(term in title_matches or term in keyword_matches for term in GATE_GROUPS["delivery"])
    mito_editing_hit = any(term in title_matches or term in keyword_matches for term in GATE_GROUPS["mito_editing"])
    mito_bio_hit = any(term in title_matches or term in keyword_matches for term in GATE_GROUPS["mito_biology"])

    gate_passed = bool(gate_matches) or auto_pass
    return gate_matches, gate_passed, editing_hit or auto_pass, engineering_hit, delivery_hit, mito_editing_hit, mito_bio_hit


def _lane_from_signals(
    editing_hit: bool,
    engineering_hit: bool,
    delivery_hit: bool,
    mito_editing_hit: bool,
    mito_bio_hit: bool,
    watch_matches: list[str],
    bucket_scores: dict[str, int],
) -> str:
    if mito_editing_hit and (editing_hit or bucket_scores["bucket_a_editing_core"] >= 10):
        return "Mitochondrial editing"
    if delivery_hit and (editing_hit or bucket_scores["bucket_c_delivery_translation"] >= 10):
        return "Delivery & translation"
    if engineering_hit and (editing_hit or bucket_scores["bucket_b_editor_engineering"] >= 10):
        return "Editor engineering"
    if editing_hit or bucket_scores["bucket_a_editing_core"] >= 12 or watch_matches:
        return "Genome editing core"
    if mito_bio_hit or bucket_scores["bucket_d_mito_bonus"] >= 5:
        return "Mitochondrial biology"
    return "General biology"


def prescore_article(article: Article) -> PrescoreResult:
    drop_reason = _exclude_article(article)
    zero_buckets = {bucket_name: 0 for bucket_name in RANK_BUCKETS}
    if drop_reason:
        return PrescoreResult(
            score=0,
            lane="General biology",
            matched_keywords=[],
            gate_matches=[],
            bucket_scores=zero_buckets,
            gate_passed=False,
            auto_pass=False,
            drop_reason=drop_reason,
        )

    title = _normalize_text(article.title)
    keywords = _normalize_text(" | ".join(article.keywords))
    abstract = _normalize_text(article.abstract)

    gate_matches, gate_passed, editing_hit, engineering_hit, delivery_hit, mito_editing_hit, mito_bio_hit = _detect_gate_matches(article)

    watch_matches, watch_bases = _detect_watch_author_matches(article)
    article.watch_author_matches = watch_matches
    article.watch_author_match_basis = watch_bases

    if watch_matches:
        gate_matches = sorted(set(gate_matches + [f"author:{name}" for name in watch_matches]))
        gate_passed = True

    title_scores, title_matches = _score_text_segment(title, TITLE_RANK_MULTIPLIER)
    keyword_scores, keyword_matches = _score_text_segment(keywords, KEYWORD_RANK_MULTIPLIER)
    abstract_scores, abstract_matches = _score_text_segment(abstract, ABSTRACT_RANK_MULTIPLIER)
    bucket_scores = _merge_bucket_scores(title_scores, keyword_scores, abstract_scores)

    matched = sorted(set(title_matches + keyword_matches + abstract_matches))
    auto_pass = any(
        _contains_term(title, term) or _contains_term(keywords, term) or _contains_term(abstract, term)
        for term in AUTO_PASS_TERMS
    )

    score = sum(bucket_scores.values())
    if bucket_scores["bucket_a_editing_core"] >= 12 and bucket_scores["bucket_b_editor_engineering"] >= 10:
        score += 10
    if bucket_scores["bucket_a_editing_core"] >= 12 and bucket_scores["bucket_c_delivery_translation"] >= 8:
        score += 6
    if bucket_scores["bucket_a_editing_core"] >= 10 and bucket_scores["bucket_d_mito_bonus"] >= 8:
        score += 8
    if auto_pass:
        score += 5
        matched.append("auto_pass")

    if watch_matches:
        if "pubmed_affiliation_email" in watch_bases:
            score += 15
        elif "last_author_fallback" in watch_bases:
            score += 12
        else:
            score += 8
        matched.extend([f"watch_author:{name}" for name in watch_matches])

    score = min(score, 100)

    lane = _lane_from_signals(
        editing_hit=editing_hit,
        engineering_hit=engineering_hit,
        delivery_hit=delivery_hit,
        mito_editing_hit=mito_editing_hit,
        mito_bio_hit=mito_bio_hit,
        watch_matches=watch_matches,
        bucket_scores=bucket_scores,
    )

    if not gate_passed:
        return PrescoreResult(
            score=score,
            lane=lane,
            matched_keywords=matched,
            gate_matches=[],
            bucket_scores=bucket_scores,
            gate_passed=False,
            auto_pass=auto_pass,
            drop_reason="no_gate_match:title_or_keywords_or_watch_author",
        )

    return PrescoreResult(
        score=score,
        lane=lane,
        matched_keywords=sorted(set(matched)),
        gate_matches=sorted(set(gate_matches)),
        bucket_scores=bucket_scores,
        gate_passed=True,
        auto_pass=auto_pass,
        drop_reason="",
    )


def sort_review_candidates(scored_articles: Iterable[tuple[Article, PrescoreResult]]) -> list[tuple[Article, PrescoreResult]]:
    lane_priority = {
        "Genome editing core": 4,
        "Editor engineering": 4,
        "Mitochondrial editing": 4,
        "Delivery & translation": 3,
        "Mitochondrial biology": 2,
        "General biology": 1,
    }
    return sorted(
        scored_articles,
        key=lambda x: (
            x[1].score,
            lane_priority.get(x[1].lane, 0),
            1 if x[1].auto_pass else 0,
            len(x[0].watch_author_matches),
            len(x[1].gate_matches),
            x[0].published.isoformat() if x[0].published else "",
        ),
        reverse=True,
    )


def _display_term(term: str) -> str:
    mapping = {
        "gene editing": "gene editing",
        "genome editing": "genome editing",
        "genome editor": "genome editor",
        "crispr": "CRISPR",
        "cas9": "Cas9",
        "cas12": "Cas12",
        "cas13": "Cas13",
        "base editing": "base editing",
        "base editor": "base editor",
        "prime editing": "prime editing",
        "prime editor": "prime editor",
        "talen": "TALEN",
        "tale": "TALE",
        "zinc finger": "zinc finger",
        "zfn": "ZFN",
        "guide rna": "guide RNA",
        "sgrna": "sgRNA",
        "pegrna": "pegRNA",
        "programmable nuclease": "programmable nuclease",
        "off-target": "off-target",
        "specificity": "specificity",
        "fidelity": "fidelity",
        "structure": "structure",
        "structural": "structural biology",
        "structural basis": "structural basis",
        "cryo-em": "cryo-EM",
        "engineering": "engineering",
        "optimization": "optimization",
        "activity": "activity",
        "mechanism": "mechanism",
        "supercoiling": "supercoiling",
        "allosteric": "allosteric",
        "aav": "AAV",
        "capsid": "capsid",
        "viral vector": "viral vector",
        "delivery": "delivery",
        "vector": "vector",
        "lnp": "LNP",
        "lipid nanoparticle": "lipid nanoparticle",
        "rnp": "RNP",
        "split intein": "split intein",
        "compact editor": "compact editor",
        "mini editor": "mini editor",
        "packaging": "packaging",
        "in vivo": "in vivo",
        "mtdna": "mtDNA",
        "mitochondrial dna": "mitochondrial DNA",
        "mitochondrial genome": "mitochondrial genome",
        "mt-genome": "mt-genome",
        "heteroplasmy": "heteroplasmy",
        "heteroplasmic": "heteroplasmic",
        "ddcbe": "DdCBE",
        "taled": "TALED",
        "mitochondria": "mitochondria",
        "mitochondrial": "mitochondrial",
        "bioenergetics": "bioenergetics",
        "oxphos": "OXPHOS",
        "respiratory chain": "respiratory chain",
        "deaminase": "deaminase",
        "nuclease": "nuclease",
        "nickase": "nickase",
    }
    return mapping.get(term.lower(), term)


_ALL_EXTRACTION_TERMS = sorted({
    *GATE_TERMS,
    *AUTO_PASS_TERMS,
    *[rule.term for bucket in RANK_BUCKETS.values() for rule in bucket["patterns"]],
})


def extract_paper_keywords(article: Article, limit: int = 25) -> list[str]:
    text = _normalize_text(" ".join([article.title or "", article.abstract or "", " | ".join(article.keywords)]))
    results: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = (value or "").strip()
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        results.append(cleaned)

    for kw in article.keywords:
        add(kw)
        if len(results) >= limit:
            return results[:limit]

    for term in _ALL_EXTRACTION_TERMS:
        if _contains_term(text, term):
            add(_display_term(term))
            if len(results) >= limit:
                break
    return results[:limit]
