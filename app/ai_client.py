"""
MOCK AI client.

Every function here returns realistic, hardcoded data in the EXACT
shape the real `ai_service` package will return. When that package is
ready, swap the internals of these functions for real API calls and
leave the function signatures / return shapes untouched so nothing
else in the codebase needs to change.

TODO: replace the mocked bodies below with calls into the real
`ai_service` package (Gemini-backed classification, embeddings,
transcription, and department-splitting) once it's available.
"""
import hashlib
import random
from typing import List, Optional, TypedDict


class ClassificationResult(TypedDict):
    category: str
    subcategory: str
    priority: str
    confidence: float
    location_text: Optional[str]
    summary: str


class EmbeddingResult(TypedDict):
    vector: List[float]


class DepartmentSplitEntry(TypedDict):
    department: str
    sub_issue: str


class DepartmentSplitResult(TypedDict):
    needs_split: bool
    departments: List[DepartmentSplitEntry]


# Very small keyword table so the mock's category guess is at least
# vaguely plausible for manual testing, instead of always returning
# the same category.
_KEYWORD_CATEGORY_MAP = {
    "water": ("water_supply", "no_water_supply"),
    "pipe": ("water_supply", "pipe_leakage"),
    "leak": ("water_supply", "pipe_leakage"),
    "road": ("roads", "pothole"),
    "pothole": ("roads", "pothole"),
    "garbage": ("garbage", "uncollected_garbage"),
    "trash": ("garbage", "uncollected_garbage"),
    "waste": ("sanitation", "waste_management"),
    "sewage": ("sanitation", "sewage_overflow"),
    "drain": ("drainage", "blocked_drain"),
    "streetlight": ("streetlights", "not_working"),
    "street light": ("streetlights", "not_working"),
    "electric": ("electricity", "power_outage"),
    "power": ("electricity", "power_outage"),
    "park": ("parks", "maintenance"),
}


def classify_complaint(text: str, image_description: Optional[str] = None) -> ClassificationResult:
    """
    MOCK: pretends to run an LLM classification pass over the complaint text
    (and optionally an image description) and returns category, subcategory,
    priority, a confidence score, an extracted location string, and a short
    summary.

    TODO: replace with a real call into ai_service.classify_complaint.
    """
    lowered = (text or "").lower()

    category, subcategory = "other", "general"
    for keyword, (cat, subcat) in _KEYWORD_CATEGORY_MAP.items():
        if keyword in lowered:
            category, subcategory = cat, subcat
            break

    urgent_markers = ("urgent", "emergency", "danger", "flood", "electrocut", "collapse")
    if any(marker in lowered for marker in urgent_markers):
        priority = "critical"
    elif category in ("water_supply", "electricity", "drainage"):
        priority = "high"
    elif category == "other":
        priority = "medium"
    else:
        priority = "medium"

    # Deterministic-but-varied confidence so repeated calls with the same
    # text always return the same "AI opinion" during manual testing.
    seed = int(hashlib.sha256(lowered.encode()).hexdigest(), 16) % 1000
    confidence = round(0.55 + (seed / 1000) * 0.4, 2)  # roughly 0.55 - 0.95

    summary = text.strip()[:140] + ("..." if len(text.strip()) > 140 else "")

    return {
        "category": category,
        "subcategory": subcategory,
        "priority": priority,
        "confidence": confidence,
        "location_text": None,
        "summary": summary or "Citizen complaint",
    }


def embed_text(text: str) -> EmbeddingResult:
    """
    MOCK: pretends to call an embedding model and returns a 768-dim vector.
    The vector is deterministically derived from the text (via a seeded
    RNG) so identical/similar text produces identical/similar-ish vectors,
    which is good enough for exercising the pgvector similarity search
    during local development.

    TODO: replace with a real call into ai_service.embed_text.
    """
    seed = int(hashlib.sha256((text or "").encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    vector = [rng.uniform(-1.0, 1.0) for _ in range(768)]
    return {"vector": vector}


def transcribe_audio(path: str) -> str:
    """
    MOCK: pretends to transcribe a voice note into text.

    TODO: replace with a real call into ai_service.transcribe_audio.
    """
    return "[MOCK TRANSCRIPTION] This is a placeholder transcript for the audio file."


def split_departments(text: str, classification: ClassificationResult) -> DepartmentSplitResult:
    """
    MOCK: pretends to detect whether a single complaint actually spans
    multiple civic departments (e.g. "the road is flooded because of a
    burst pipe" -> Roads + Water Board) and, if so, returns the split.

    NOTE ON CONTRACT AMBIGUITY (flag for the AI pair before final
    integration — see project doc section 7): the original SIH spec
    describes each entry as {"department", "sub_issue"}, while a later
    planning doc describes {"department_id", "sub_issue_description"}.
    This mock returns {"category", "sub_issue"} instead — a category
    value (e.g. "water_supply"), not a department name or numeric id —
    so the caller can route it through the same CATEGORY_TO_DEPARTMENT
    mapping used everywhere else in the codebase, keeping department
    routing logic in one place. Confirm the real shape with the AI pair
    and adjust the caller (app/routers/intake.py) if it differs.

    TODO: replace with a real call into ai_service.split_departments.
    """
    lowered = (text or "").lower()

    matched: dict = {}
    for keyword, (cat, subcat) in _KEYWORD_CATEGORY_MAP.items():
        if keyword in lowered:
            matched.setdefault(cat, subcat)

    # The primary category from classify_complaint always counts as one
    # of the departments involved, if it wasn't already keyword-matched.
    primary_category = classification.get("category") if classification else None
    if primary_category:
        matched.setdefault(primary_category, "general")

    if len(matched) < 2:
        return {"needs_split": False, "departments": []}

    departments: List[DepartmentSplitEntry] = [
        {
            "category": cat,
            "sub_issue": f"{cat.replace('_', ' ').title()} issue: {subcat.replace('_', ' ')}",
        }
        for cat, subcat in matched.items()
    ]
    return {"needs_split": True, "departments": departments}
