from __future__ import annotations

from dataclasses import dataclass


CNS_MAIN_JOURNALS = ["Nature", "Science", "Cell"]

CNS_HIGH_IMPACT_JOURNALS = [
    "Nature",
    "Nature Biotechnology",
    "Nature Methods",
    "Nature Genetics",
    "Nature Medicine",
    "Nature Neuroscience",
    "Nature Structural & Molecular Biology",
    "Nature Chemical Biology",
    "Nature Biomedical Engineering",
    "Nature Cell Biology",
    "Nature Metabolism",
    "Nature Communications",
    "Science",
    "Science Translational Medicine",
    "Cell",
    "Molecular Cell",
    "Neuron",
    "Cell Metabolism",
    "Cell Stem Cell",
    "Nucleic Acids Research",
]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            ordered.append(value)
            seen.add(key)
    return ordered


CNS_HIGH_IMPACT_JOURNALS = _unique(CNS_HIGH_IMPACT_JOURNALS)

JOURNAL_PRESETS: dict[str, list[str]] = {
    "cns_main": CNS_MAIN_JOURNALS,
    "cns_high_impact": CNS_HIGH_IMPACT_JOURNALS,
    "cns_bio_sisters": CNS_HIGH_IMPACT_JOURNALS,
}

DEFAULT_JOURNAL_PRESET = "cns_high_impact"
ALL_TRACKER_JOURNALS = _unique([journal for journals in JOURNAL_PRESETS.values() for journal in journals])

EXCLUSION_PATTERNS = [
    r"^author correction\b",
    r"^publisher correction\b",
    r"^correction to\b",
    r"^retraction\b",
    r"\bretracted\b",
    r"\beditorial\b",
    r"\bcommentary\b",
    r"\bperspective\b",
    r"\bnews\b",
    r"\binsight\b",
]

AUTO_PASS_TERMS = [
    "gene editing",
    "genome editing",
    "crispr",
    "cas9",
    "cas12",
    "cas13",
    "base editing",
    "base editor",
    "prime editing",
    "prime editor",
    "talen",
    "zinc finger",
    "zfn",
    "ddcbe",
    "taled",
]


@dataclass(frozen=True)
class WeightedPattern:
    term: str
    weight: int


TITLE_RANK_MULTIPLIER = 3
KEYWORD_RANK_MULTIPLIER = 2
ABSTRACT_RANK_MULTIPLIER = 1

LANE_OPTIONS = [
    "Genome editing core",
    "Editor engineering",
    "Delivery & translation",
    "Mitochondrial editing",
    "Mitochondrial biology",
    "General biology",
]

FAST_FOLLOWER_TYPES = [
    "editor engineering",
    "delivery",
    "assay",
    "disease model",
    "mechanism",
]

STATUS_OPTIONS = ["new", "read", "discussed", "parked"]
SOURCE_OPTIONS = ["Crossref", "PubMed", "Crossref Author Watch"]

MITO_EDITING_GATE_TERMS = [
    "mtdna",
    "mitochondrial dna",
    "mitochondrial genome",
    "mt-genome",
    "heteroplasmy",
    "heteroplasmic",
    "ddcbe",
    "taled",
]

GENOME_EDITING_GATE_TERMS = [
    "gene editing",
    "genome editing",
    "genome editor",
    "crispr",
    "cas9",
    "cas12",
    "cas13",
    "base editing",
    "base editor",
    "prime editing",
    "prime editor",
    "talen",
    "tale",
    "zinc finger",
    "zfn",
    "guide rna",
    "sgrna",
    "pegrna",
    "programmable nuclease",
    "ddcbe",
    "taled",
]

ENGINEERING_GATE_TERMS = [
    "off-target",
    "specificity",
    "fidelity",
    "structural basis",
    "structure",
    "structural",
    "cryo-em",
    "guide rna",
    "sgrna",
    "pegrna",
    "nuclease",
    "nickase",
    "deaminase",
]

DELIVERY_GATE_TERMS = [
    "aav",
    "capsid",
    "viral vector",
    "delivery",
    "lnp",
    "lipid nanoparticle",
    "rnp",
    "split intein",
    "compact editor",
    "mini editor",
]

MITO_BIO_GATE_TERMS = [
    "mitochondria",
    "mitochondrial",
    "bioenergetics",
    "oxphos",
    "respiratory chain",
]

GATE_GROUPS: dict[str, list[str]] = {
    "mito_editing": MITO_EDITING_GATE_TERMS,
    "genome_editing": GENOME_EDITING_GATE_TERMS,
    "engineering": ENGINEERING_GATE_TERMS,
    "delivery": DELIVERY_GATE_TERMS,
    "mito_biology": MITO_BIO_GATE_TERMS,
}

GATE_TERMS = sorted({term for terms in GATE_GROUPS.values() for term in terms})

RANK_BUCKETS: dict[str, dict[str, object]] = {
    "bucket_a_editing_core": {
        "max": 40,
        "patterns": [
            WeightedPattern("gene editing", 9),
            WeightedPattern("genome editing", 9),
            WeightedPattern("genome editor", 8),
            WeightedPattern("crispr", 8),
            WeightedPattern("cas9", 9),
            WeightedPattern("cas12", 8),
            WeightedPattern("cas13", 8),
            WeightedPattern("base editing", 10),
            WeightedPattern("base editor", 10),
            WeightedPattern("prime editing", 9),
            WeightedPattern("prime editor", 9),
            WeightedPattern("talen", 8),
            WeightedPattern("tale", 4),
            WeightedPattern("zinc finger", 7),
            WeightedPattern("zfn", 7),
            WeightedPattern("programmable nuclease", 7),
            WeightedPattern("guide rna", 5),
            WeightedPattern("sgrna", 5),
            WeightedPattern("pegrna", 6),
            WeightedPattern("deaminase", 5),
            WeightedPattern("nuclease", 4),
            WeightedPattern("nickase", 4),
            WeightedPattern("ddcbe", 10),
            WeightedPattern("taled", 10),
        ],
    },
    "bucket_b_editor_engineering": {
        "max": 25,
        "patterns": [
            WeightedPattern("off-target", 9),
            WeightedPattern("specificity", 8),
            WeightedPattern("fidelity", 8),
            WeightedPattern("structure", 7),
            WeightedPattern("structural", 7),
            WeightedPattern("structural basis", 8),
            WeightedPattern("cryo-em", 7),
            WeightedPattern("engineering", 5),
            WeightedPattern("optimization", 5),
            WeightedPattern("activity", 4),
            WeightedPattern("mechanism", 4),
            WeightedPattern("supercoiling", 5),
            WeightedPattern("allosteric", 4),
        ],
    },
    "bucket_c_delivery_translation": {
        "max": 20,
        "patterns": [
            WeightedPattern("aav", 6),
            WeightedPattern("capsid", 6),
            WeightedPattern("viral vector", 6),
            WeightedPattern("delivery", 5),
            WeightedPattern("vector", 3),
            WeightedPattern("lnp", 6),
            WeightedPattern("lipid nanoparticle", 6),
            WeightedPattern("rnp", 5),
            WeightedPattern("split intein", 6),
            WeightedPattern("compact editor", 8),
            WeightedPattern("mini editor", 8),
            WeightedPattern("packaging", 4),
            WeightedPattern("in vivo", 5),
        ],
    },
    "bucket_d_mito_bonus": {
        "max": 15,
        "patterns": [
            WeightedPattern("mtdna", 10),
            WeightedPattern("mitochondrial dna", 10),
            WeightedPattern("mitochondrial genome", 10),
            WeightedPattern("mt-genome", 9),
            WeightedPattern("heteroplasmy", 9),
            WeightedPattern("heteroplasmic", 9),
            WeightedPattern("ddcbe", 12),
            WeightedPattern("taled", 12),
            WeightedPattern("mitochondria", 4),
            WeightedPattern("mitochondrial", 4),
            WeightedPattern("bioenergetics", 3),
            WeightedPattern("oxphos", 3),
        ],
    },
}

TOPIC_TERMS = [
    "genome editing",
    "gene editing",
    "CRISPR",
    "Cas9",
    "Cas12",
    "Cas13",
    "base editing",
    "prime editing",
    "TALEN",
    "zinc finger",
    "DdCBE",
    "TALED",
    "guide RNA",
    "pegRNA",
    "off-target",
    "specificity",
    "editor engineering",
    "structural biology",
    "cryo-EM",
    "delivery",
    "AAV delivery",
    "LNP delivery",
    "compact editor",
    "mitochondrial genome",
    "mtDNA heteroplasmy",
    "mitochondria",
]

WATCHED_AUTHOR_ALIASES = {
    "David R. Liu": ["David R. Liu", "David Liu"],
    "Jennifer A. Doudna": ["Jennifer A. Doudna", "Jennifer Doudna", "J A Doudna"],
    "Feng Zhang": ["Feng Zhang"],
    "Jay Shendure": ["Jay Shendure"],
    "Omar O. Abudayyeh": ["Omar O. Abudayyeh", "Omar Abudayyeh", "Omar Osama Abudayyeh"],
    "Jonathan S. Gootenberg": ["Jonathan S. Gootenberg", "Jonathan Gootenberg", "Jonathan Samuel Gootenberg"],
    "Patrick D. Hsu": ["Patrick D. Hsu", "Patrick Hsu", "Patrick David Hsu"],
    "Samuel H. Sternberg": ["Samuel H. Sternberg", "Samuel Sternberg", "Sam Sternberg"],
    "Caixia Gao": ["Caixia Gao"],
    "Wensheng Wei": ["Wensheng Wei"],
    "Sangsu Bae": ["Sangsu Bae"],
    "Hyongbum Henry Kim": ["Hyongbum Henry Kim", "Hyongbum Kim", "Henry Kim", "Hyongbum (Henry) Kim"],
}

WATCH_AUTHOR_ROWS_PER_AUTHOR = 10


def resolve_journal_preset(preset: str | None) -> list[str]:
    key = (preset or DEFAULT_JOURNAL_PRESET).strip().lower()
    return JOURNAL_PRESETS.get(key, JOURNAL_PRESETS[DEFAULT_JOURNAL_PRESET])
