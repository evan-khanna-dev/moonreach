import difflib
import io
import json
import logging
import os
import re
import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from anthropic import AI_PROMPT, Anthropic, HUMAN_PROMPT
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from postgrest.exceptions import APIError
from supabase import create_client

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("moonreach")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_CLIENT_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

if not SUPABASE_URL or not SUPABASE_CLIENT_KEY or not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "Missing required environment variables. Please ensure SUPABASE_URL, SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY, and ANTHROPIC_API_KEY are set."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_CLIENT_KEY)
supabase_service = None
if SUPABASE_SERVICE_ROLE_KEY:
    supabase_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

def db_table(table_name: str):
    return supabase_service.table(table_name) if supabase_service else supabase.table(table_name)

app = FastAPI(title="MoonReach Career Coach")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

def execute_db(operation, require_service_role: bool = False):
    try:
        response = operation.execute()
        return response
    except APIError as exc:
        error_info = exc.args[0] if exc.args else {}
        if isinstance(error_info, dict) and error_info.get("code") == "42501":
            raise HTTPException(
                status_code=500,
                detail=(
                    "Supabase row-level security blocked this request. "
                    "Use a Supabase service role key in SUPABASE_SERVICE_ROLE_KEY or adjust RLS policies for the backend key."
                ),
            )
        if isinstance(error_info, dict) and error_info.get("message"):
            raise HTTPException(status_code=500, detail=f"Supabase request failed: {error_info['message']}")
        raise HTTPException(status_code=500, detail="Supabase request failed")

SEARCH_KEYWORDS = [
    "opportunity",
    "opportunities",
    "internship",
    "internships",
    "recruit",
    "recruiting",
    "career center",
    "career fair",
    "network",
    "networking",
    "employer",
    "employers",
    "job",
    "jobs",
    "club",
    "clubs",
    "organization",
    "organizations",
    "hackathon",
    "fellowship",
    "application",
    "fair",
    "volunteer",
    "resume",
    "interview",
    "portfolio",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}

# Appointments: document reviews. Resume only for this pass - CV, cover
# letter, and LinkedIn intentionally not built yet (see DocumentReviewCreate).
SUPPORTED_DOCUMENT_TYPES = {"resume"}
RESUME_REVIEW_INTENTS = {"general_feedback", "tailor_to_role", "something_else"}
RESUME_FOLLOWUP_INTENT = "resume_follow_up"
RESUME_GROUNDING_DOCUMENT_PATH = os.path.join(os.path.dirname(__file__), "resume-grounding-document.md")

# Resume upload: which formats we accept and extract text from before any of
# the review logic above ever sees the document (see extract_resume_text).
SUPPORTED_RESUME_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt"}
# MIME type is a secondary signal, not the sole gate - browsers/OSes are
# inconsistent about what they send. A generic/missing content-type is
# tolerated; an outright mismatch (e.g. .txt extension, application/pdf
# content-type) is rejected.
RESUME_UPLOAD_MIME_TYPES_BY_EXTENSION = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",  # some browsers/OSes report the underlying zip container
    },
    ".txt": {"text/plain"},
}
GENERIC_UPLOAD_MIME_TYPES = {"application/octet-stream", ""}
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB - no existing app-wide upload limit to match, chosen fresh


class ProfileCreate(BaseModel):
    university: str
    major: str
    year: str


class ProfileUpdate(BaseModel):
    university: Optional[str] = None
    major: Optional[str] = None
    year: Optional[str] = None


class SessionCreate(BaseModel):
    goals: str


class ChatRequest(BaseModel):
    session_id: int
    message: str


class PlanRequest(BaseModel):
    session_id: int


class DocumentReviewCreate(BaseModel):
    session_id: int
    document_type: str = "resume"
    document_content: str
    intent: str
    role_context: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class OpportunityCreate(BaseModel):
    session_id: int
    title: str
    category: str
    description: str
    reason_relevant: str
    source_url: Optional[str] = None
    priority_score: Optional[int] = None
    status: Optional[str] = "suggested"


class OpportunityUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    reason_relevant: Optional[str] = None
    source_url: Optional[str] = None
    priority_score: Optional[int] = None
    status: Optional[str] = None


VALID_OPPORTUNITY_CATEGORIES = {
    "Internship",
    "Research",
    "Event",
    "Networking",
    "Organization",
    "Hackathon",
    "Competition",
    "Scholarship",
    "Leadership",
    "Career Center",
    "Employer Program",
    "Conference",
    "Other",
}

VALID_OPPORTUNITY_STATUSES = {"suggested", "interested", "exploring", "applied", "completed", "archived"}


def normalize_category(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return "Other"
    cleaned = value.strip()
    if not cleaned:
        return "Other"
    if cleaned in VALID_OPPORTUNITY_CATEGORIES:
        return cleaned
    return "Other"


def normalize_status(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return "suggested"
    cleaned = value.strip().lower()
    if cleaned in VALID_OPPORTUNITY_STATUSES:
        return cleaned
    return "suggested"


def normalize_priority_score(value: Any) -> int:
    if isinstance(value, bool):
        return 5
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, numeric))


STATUS_LIFECYCLE_ORDER = ["suggested", "interested", "exploring", "applied", "completed", "archived"]

# Documented forward-only transitions. Archived is a terminal state (only reachable, not escapable).
RECOMMENDED_STATUS_TRANSITIONS = {
    "suggested": {"interested", "exploring", "applied", "completed", "archived"},
    "interested": {"exploring", "applied", "completed", "archived"},
    "exploring": {"applied", "completed", "archived"},
    "applied": {"completed", "archived"},
    "completed": {"archived"},
    "archived": set(),
}

DUPLICATE_TITLE_SIMILARITY_THRESHOLD = 0.6
DUPLICATE_SOURCE_URL_MATCH_THRESHOLD = 0.9

# Generic career words that should never by themselves identify a specific
# opportunity. A reference consisting only of these is too vague to match.
GENERIC_TITLE_TOKENS = {
    "intern", "internship", "internships", "opportunity", "opportunities",
    "job", "jobs", "career", "careers", "fair", "event", "events", "program",
    "programs", "scholarship", "scholarships", "application", "applications",
    "club", "clubs", "research", "volunteer", "fellowship", "fellowships",
}


def transition_status(current_status: Optional[str], new_status: str) -> bool:
    """Return True when moving from current_status to new_status is sensible.

    Forward transitions follow RECOMMENDED_STATUS_TRANSITIONS. Any transition to a
    later state is allowed as well (e.g. suggested -> applied), while regressions
    (e.g. applied -> suggested) are rejected so the radar never moves backwards.
    """
    if not isinstance(new_status, str):
        return False
    new_status = new_status.lower()
    if new_status not in VALID_OPPORTUNITY_STATUSES:
        return False
    current = (current_status or "suggested").strip().lower()
    if current not in VALID_OPPORTUNITY_STATUSES:
        current = "suggested"
    if current == new_status:
        return True
    allowed = RECOMMENDED_STATUS_TRANSITIONS.get(current, set())
    if new_status in allowed:
        return True
    current_idx = STATUS_LIFECYCLE_ORDER.index(current) if current in STATUS_LIFECYCLE_ORDER else 0
    new_idx = STATUS_LIFECYCLE_ORDER.index(new_status) if new_status in STATUS_LIFECYCLE_ORDER else len(STATUS_LIFECYCLE_ORDER)
    return new_idx > current_idx


def title_similarity(a: str, b: str) -> float:
    """Return a 0..1 similarity for two opportunity titles.

    Combines exact token containment (catching partial / abbreviated references like
    "STEP" vs "Google STEP Internship") with a fuzzy sequence ratio and Jaccard.
    References made entirely of generic career words are deliberately discounted so
    a vague phrase like "internship" never drives a duplicate match on its own.
    """
    def tokens(value: str) -> List[str]:
        return [tok for tok in re.split(r"[^a-z0-9]+", str(value).lower()) if tok]

    ta = tokens(a)
    tb = tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0

    set_a, set_b = set(ta), set(tb)
    common = set_a & set_b
    jaccard = len(common) / len(set_a | set_b)
    containment = max(len(common) / len(set_a), len(common) / len(set_b))
    ratio = difflib.SequenceMatcher(None, ta, tb).ratio()

    score = max(jaccard, containment * 0.9, ratio)
    generic_only = set_a.issubset(GENERIC_TITLE_TOKENS) or set_b.issubset(GENERIC_TITLE_TOKENS)
    if generic_only and not common - GENERIC_TITLE_TOKENS:
        score *= 0.5
    return score


def source_url_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    def norm(value: str) -> str:
        return re.sub(r"^https?://", "", value.strip().lower()).rstrip("/")
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


class OpportunityService:
    def __init__(self) -> None:
        self.table = db_table("opportunities")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _sanitize_payload(self, payload: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {}
        if not partial or "title" in payload:
            sanitized["title"] = str(payload.get("title") or "").strip()
        if not partial or "category" in payload:
            sanitized["category"] = normalize_category(payload.get("category"))
        if not partial or "description" in payload:
            sanitized["description"] = str(payload.get("description") or "").strip()
        if not partial or "reason_relevant" in payload:
            sanitized["reason_relevant"] = str(payload.get("reason_relevant") or "").strip()
        if not partial or "source_url" in payload:
            sanitized["source_url"] = str(payload.get("source_url") or "").strip() if payload.get("source_url") else None
        if not partial or "priority_score" in payload:
            sanitized["priority_score"] = normalize_priority_score(payload.get("priority_score"))
        if not partial or "status" in payload:
            sanitized["status"] = normalize_status(payload.get("status"))
        return sanitized

    def create_opportunity(self, session_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = self._sanitize_payload(payload)
        if not sanitized["title"]:
            raise HTTPException(status_code=400, detail="Opportunity title is required")
        if not sanitized["description"]:
            raise HTTPException(status_code=400, detail="Opportunity description is required")

        insert_payload = {
            "session_id": session_id,
            **sanitized,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        response = execute_db(self.table.insert(insert_payload).select("*"))
        if not getattr(response, "data", None):
            raise HTTPException(status_code=500, detail="Failed to create opportunity")
        return response.data[0]

    def update_opportunity(self, opportunity_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = self._sanitize_payload(payload, partial=True)
        if not sanitized:
            raise HTTPException(status_code=400, detail="No update fields provided")
        update_payload = {**sanitized, "updated_at": self._now()}
        response = execute_db(self.table.update(update_payload).eq("id", opportunity_id).select("*"))
        if not getattr(response, "data", None):
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return response.data[0]

    def archive_opportunity(self, opportunity_id: int) -> Dict[str, Any]:
        response = execute_db(
            self.table.update({"status": "archived", "updated_at": self._now()}).eq("id", opportunity_id).select("*")
        )
        if not getattr(response, "data", None):
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return response.data[0]

    def get_session_opportunities(self, session_id: int) -> List[Dict[str, Any]]:
        response = execute_db(
            self.table.select("*").eq("session_id", session_id).order("priority_score", desc=True).order("updated_at", desc=True)
        )
        return getattr(response, "data", None) or []

    def find_matching_opportunity(
        self,
        session_id: int,
        title: Optional[str],
        source_url: Optional[str] = None,
        category: Optional[str] = None,
        existing_opportunities: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve a candidate (by title/source_url) to an existing radar row.

        Returns the best non-archived match above the similarity threshold, or None.
        """
        opportunities = existing_opportunities if existing_opportunities is not None else self.get_session_opportunities(session_id)
        candidates = [o for o in opportunities if isinstance(o, dict) and str(o.get("status") or "").lower() != "archived"]

        title_match: Optional[Dict[str, Any]] = None
        title_score = 0.0
        source_match: Optional[Dict[str, Any]] = None
        source_score = 0.0

        for opportunity in candidates:
            claimed = str(title or "").strip()
            existing_title = str(opportunity.get("title") or "").strip()
            if claimed and existing_title:
                score = title_similarity(claimed, existing_title)
                if score > title_score:
                    title_score, title_match = score, opportunity

            cand_source = str(source_url or "").strip()
            existing_source = str(opportunity.get("source_url") or "").strip()
            if cand_source and existing_source:
                score = source_url_similarity(cand_source, existing_source)
                if score > source_score:
                    source_score, source_match = score, opportunity

        if source_match and source_score >= DUPLICATE_SOURCE_URL_MATCH_THRESHOLD:
            return source_match
        if (
            title_match
            and title_score >= DUPLICATE_TITLE_SIMILARITY_THRESHOLD
            and (not category or not title_match.get("category") or title_match.get("category") == category)
        ):
            return title_match
        return None

    def find_duplicate_opportunity(self, session_id: int, candidate: Dict[str, Any], existing_opportunities: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """DEPRECATED - resolves a candidate payload to an existing opportunity via fuzzy matching."""
        return self.find_matching_opportunity(
            session_id,
            title=str(candidate.get("title") or "").strip() or None,
            source_url=str(candidate.get("source_url") or "").strip() or None,
            category=str(candidate.get("category") or "").strip() or None,
            existing_opportunities=existing_opportunities,
        )

    def update_priority(self, opportunity_id: int, priority_score: int) -> Dict[str, Any]:
        return self.update_opportunity(opportunity_id, {"priority_score": priority_score})

    def update_status(self, opportunity_id: int, status: str) -> Dict[str, Any]:
        return self.update_opportunity(opportunity_id, {"status": status})

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\W+", " ", str(value).strip().lower()).strip()


STRONG_INTEREST_MARKERS = [
    "really want", "really excited", "top choice", "love", "favorite", "excited about",
    "priority", "dream", "first choice", "high priority", "pursue this", "committed",
    "must do", "definitely", "heavily interested",
]
DISINTEREST_MARKERS = [
    "not interested", "no longer interested", "don't care", "do not care", "skip",
    "not for me", "bored", "dropping", "won't", "not attending", "pass on",
    "doesn't interest", "not really feeling",
]


def detect_priority_signal(user_message: str) -> int:
    """Return +1 for strong interest, -1 for disinterest, 0 otherwise."""
    lowered = user_message.lower()
    if any(marker in lowered for marker in DISINTEREST_MARKERS):
        return -1
    if any(marker in lowered for marker in STRONG_INTEREST_MARKERS):
        return 1
    return 0


def resolve_opportunity_target(
    service: OpportunityService,
    existing_opportunities: List[Dict[str, Any]],
    update: Dict[str, Any],
    session_id: int,
) -> Optional[Dict[str, Any]]:
    """Resolve an update clause to an existing opportunity row.

    Preference order:
    1) explicit opportunity_id (or item id)
    2) a title/source_url fuzzy match against the current radar
    """
    opportunity_id = update.get("opportunity_id") or update.get("id")
    if opportunity_id is not None:
        try:
            target_id = int(opportunity_id)
        except (TypeError, ValueError):
            target_id = None
        if target_id is not None:
            for opp in existing_opportunities:
                if int(opp.get("id") or -1) == target_id:
                    return opp
            return None
    claimed_title = str(update.get("title") or "").strip() or None
    claimed_source = str(update.get("source_url") or "").strip() or None
    if claimed_title or claimed_source:
        matched = service.find_matching_opportunity(
            session_id,
            title=claimed_title,
            source_url=claimed_source,
            category=str(update.get("category") or "").strip() or None,
            existing_opportunities=existing_opportunities,
        )
        if matched:
            return matched
    return None


def merge_opportunity_update(
    service: OpportunityService,
    existing: Dict[str, Any],
    update: Dict[str, Any],
    session_id: int,
) -> Dict[str, Any]:
    """Merge a partial Claude update into an existing radar row.

    Enforces status transitions and re-applies the priority clamp so the radar
    always moves forward rather than rewriting from scratch.
    """
    payload: Dict[str, Any] = {}
    for field in ("category", "description", "reason_relevant", "source_url"):
        if update.get(field) not in (None, ""):
            payload[field] = update.get(field)

    new_title = str(update.get("title") or "").strip()
    if new_title and title_similarity(new_title, str(existing.get("title") or "")) < 0.8:
        payload["title"] = new_title

    new_status = update.get("status")
    should_change_status = False
    if isinstance(new_status, str):
        candidate_status = normalize_status(new_status)
        should_change_status = transition_status(existing.get("status"), candidate_status)
    if should_change_status:
        payload["status"] = normalize_status(new_status)
    elif new_status and not should_change_status:
        logger.info(
            "Rejected invalid status transition for opportunity %s: %r -> %r",
            existing.get("id"), existing.get("status"), new_status,
        )

    priority_score = update.get("priority_score")
    if priority_score is not None:
        payload["priority_score"] = normalize_priority_score(priority_score)

    if not payload:
        return existing
    updated = service.update_opportunity(int(existing["id"]), payload)
    return updated


def clean_text(raw: str) -> str:
    text = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def should_run_search(message: str) -> bool:
    normalized = message.lower()
    return any(keyword in normalized for keyword in SEARCH_KEYWORDS)


def parse_bing_search_results(html_text: str) -> List[Dict[str, str]]:
    blocks = re.findall(r"<li class=\"b_algo\".*?</li>", html_text, flags=re.S)
    results: List[Dict[str, str]] = []
    for block in blocks:
        title_match = re.search(r"<h2.*?>(.*?)</h2>", block, flags=re.S)
        url_match = re.search(r"<a[^>]+href=\"([^\"]+)\"", block)
        snippet_match = re.search(r"<p>(.*?)</p>", block, flags=re.S)
        if not title_match or not url_match:
            continue
        title = clean_text(title_match.group(1))
        url = url_match.group(1)
        snippet = clean_text(snippet_match.group(1)) if snippet_match else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= 4:
            break
    return results


def run_web_search(query: str) -> List[Dict[str, str]]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en-us"
    with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(url)
        if response.status_code != 200:
            return []
        return parse_bing_search_results(response.text)


def format_search_summary(query: str, results: List[Dict[str, str]]) -> str:
    if not results:
        return f"Search query: {query}\nNo relevant results were found."
    lines = [f"Search query: {query}"]
    for result in results:
        lines.append(f"- {result['title']}")
        lines.append(f"  {result['url']}")
        if result["snippet"]:
            lines.append(f"  {result['snippet']}")
    return "\n".join(lines)


def parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, str):
        return None

    def try_parse(candidate: str) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, str):
            return None
        cleaned = candidate.strip()
        if not cleaned:
            return None

        fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.S)
        if fenced_blocks:
            cleaned = fenced_blocks[0].strip()
        elif cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned.startswith("`json"):
            cleaned = re.sub(r"^`json\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned.startswith("`") and cleaned.endswith("`"):
            cleaned = cleaned[1:-1].strip()

        if cleaned.startswith('"') and cleaned.endswith('"'):
            inner = cleaned[1:-1]
            if inner:
                parsed = try_parse(inner)
                if parsed is not None:
                    return parsed

        if "{" in cleaned and "}" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if 0 <= start < end:
                candidates = [cleaned, cleaned[start : end + 1]]
                for item in candidates:
                    try:
                        parsed = json.loads(item)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        try:
            parsed = json.loads(cleaned)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    parsed = try_parse(raw)
    if not isinstance(parsed, dict):
        return None

    # Claude occasionally wraps its own JSON schema inside the
    # assistant_response string (sometimes more than once). Keep unwrapping
    # until it stops nesting, so a doubly-wrapped payload can't slip through
    # as literal JSON text in the visible response. Depth-capped so a
    # pathological/cyclical payload can't loop forever.
    for _ in range(5):
        if not isinstance(parsed.get("assistant_response"), str):
            break
        nested = try_parse(parsed["assistant_response"])
        if not isinstance(nested, dict):
            break
        merged = dict(parsed)
        for key in ("assistant_response", "suggested_replies", "career_radar_updates"):
            if key in nested:
                merged[key] = nested[key]
        if merged == parsed:
            break
        parsed = merged

    return parsed


def salvage_assistant_text(raw: str) -> str:
    """Best-effort recovery when parse_json_response gives up entirely (e.g.
    output truncated mid-JSON by max_tokens/stop_sequence, or a stray
    preamble breaks every parse attempt). Never return the raw JSON-shaped
    text verbatim - that's what ends up as a literal JSON blob in the chat
    bubble and gets persisted to the messages table."""
    text = (raw or "").strip()
    if not text.startswith("{"):
        # Doesn't look like the requested JSON shape at all - Claude likely
        # just replied in prose despite the instructions. Safe to show as-is.
        return text
    match = re.search(r'"assistant_response"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"')
        except Exception:
            return match.group(1)
    return "Sorry, I had trouble formatting that response - could you try rephrasing your last message?"


def compose_coach_prompt(
    context: Dict[str, str],
    history: List[Dict[str, str]],
    user_message: str,
    search_summary: Optional[str],
    opportunities: Optional[List[Dict[str, Any]]] = None,
) -> str:
    conversation_lines = []
    for item in history:
        role = item["role"].capitalize()
        conversation_lines.append(f"{role}: {item['content']}")
    conversation_text = "\n".join(conversation_lines)

    search_block = ""
    if search_summary:
        search_block = (
            "\nSearch results summary:\n"
            f"{search_summary}\n\n"
            "Incorporate these results where they are relevant and avoid inventing new details."
        )

    opportunity_block = ""
    if opportunities:
        opportunity_lines = ["Existing Career Radar items (id is required to update an existing item):"]
        for item in opportunities[:8]:
            opportunity_lines.append(
                f"- id={item.get('id')} | title={item.get('title', 'Untitled')} | category={item.get('category', 'Other')} | status={item.get('status', 'suggested')} | priority={item.get('priority_score', 5)} | reason={item.get('reason_relevant', '')}"
            )
        opportunity_block = "\n".join(opportunity_lines) + "\n\n"

    prompt = (
        f"{HUMAN_PROMPT}You are an empathetic AI career coach for college students. "
        "Maintain a conversational, flexible tone while keeping guidance focused on career opportunities, networking, employer connections, internships, and practical next steps. "
        "Do not provide academic course selection advice, degree planning, authentication/account guidance, or resume creation services. "
        "Use the student’s university, major, year, and goals as the foundation for every answer."
        "\n\n"
        "Student context:\n"
        f"University: {context['university']}\n"
        f"Major: {context['major']}\n"
        f"Year: {context['year']}\n"
        f"Goals: {context['goals']}\n\n"
        f"{opportunity_block}"
        "Recent conversation history:\n"
        f"{conversation_text}\n\n"
        f"User: {user_message}\n\n"
        f"{search_block}"
        "Your three jobs are:\n"
        "1. Answer the student's question naturally and empathetically.\n"
        "2. Suggest 3 short, sensible next-user prompts.\n"
        "3. Keep the Career Radar accurate and \"alive\": meaningfully evolve the matching opportunities instead of endlessly generating new ones.\n"
        "\n"
        "Career Radar update rules (career_radar_updates):\n"
        "- The radar is a live tracking workspace, not a static recommendation list. Every chat must EITHER create a genuinely new opportunity OR make an existing one more accurate.\n"
        "- When the user references an opportunity that already exists (same title, an abbreviation, a partial match, or an obvious conversational reference like \"STEP\", \"ACM\", \"the hackathon\", \"that Google one\"), you MUST update the existing item — never create a duplicate.\n"
        "- The `Existing Career Radar items` list above shows the ids. To modify an existing item include its `id` as `opportunity_id` in your update clause. New items created for the first time need no id.\n"
        "- Adding a new opportunity is the LAST RESORT — only for something genuinely not present on the radar.\n"
        "- Each clause is one of: add, update, reprioritize, or archive.\n"
        "  - update: change status, category, title, description, or reason for an EXISTING item (set opportunity_id). Prefer this action for nearly all adjustments.\n"
        "  - reprioritize: change priority_score of an existing item (set opportunity_id) when the user expresses strong interest (raise) or disinterest (lower).\n"
        "  - archive: mark an existing item archived when it is no longer relevant (set opportunity_id).\n"
        "  - add: only for a brand-new opportunity not already on the radar.\n"
        "Status meanings and transitions (status):\n"
        "- suggested: surfaced and worth watching\n"
        "- interested: user is thinking about / attracted to it\n"
        "- exploring: user is actively researching\n"
        "- applied: user has applied\n"
        "- completed: user finished the activity, e.g. attended a fair or finished a program\n"
        "- archived: no longer tracking\n"
        "- Move status FORWARD along suggested -> interested -> exploring -> applied -> completed (esp. when the user mentions applying, attending, or expressing interest). Never move backwards.\n"
        "Priority (priority_score, 1-10, default 5): raise when the user is strongly excited (e.g. \"I really want this\") and lower when the user seems uninterested or dismissive.\n"
        "Return only a valid JSON object with the keys\n"
        "- assistant_response: the coaching reply\n"
        "- suggested_replies: a short list of 3 next-user prompts relevant to the conversation\n"
        "- career_radar_updates: an array of update objects (empty array if nothing should change)\n"
        "Update object shape (only include fields that change): action, opportunity_id, title, category, description, reason_relevant, priority_score, status, source_url\n"
        "Do not add any additional text outside the JSON object."
        f"{AI_PROMPT}"
    )
    return prompt


def compose_plan_prompt(context: Dict[str, str], history: List[Dict[str, str]]) -> str:
    conversation_lines = []
    for item in history:
        role = item["role"].capitalize()
        conversation_lines.append(f"{role}: {item['content']}")
    conversation_text = "\n".join(conversation_lines)

    prompt = (
        f"{HUMAN_PROMPT}You are a practical AI career coach for college students. "
        "Use the student’s university, major, year, and goals as the basis for career-focused advice. "
        "Do not provide academic course selection guidance, resume drafting, or account setup instructions. "
        "Review the full conversation history and summarize the best next steps into a concise action plan.\n\n"
        "Student context:\n"
        f"University: {context['university']}\n"
        f"Major: {context['major']}\n"
        f"Year: {context['year']}\n"
        f"Goals: {context['goals']}\n\n"
        "Conversation history:\n"
        f"{conversation_text}\n\n"
        "Provide only a JSON array of 4 to 6 short action items."
        f"{AI_PROMPT}"
    )
    return prompt


def compose_north_star_prompt(
    context: Dict[str, str],
    chats: List[Dict[str, Any]],
    opportunities: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
    plans: List[Dict[str, Any]],
) -> str:
    goals_by_id = {int(chat["id"]): str(chat.get("goals") or f"Chat {chat['id']}") for chat in chats}

    chat_lines = []
    if chats:
        for chat in chats:
            chat_lines.append(f"- {chat.get('goals') or 'Untitled chat'} (started {str(chat.get('created_at'))[:10]})")
    else:
        chat_lines.append("- (no chats started yet)")
    chats_block = "\n".join(chat_lines)

    opportunity_lines = []
    if opportunities:
        for item in opportunities:
            chat_label = goals_by_id.get(int(item.get("session_id") or -1), "Unknown chat")
            entry = (
                f"- [{chat_label}] {item.get('title', 'Untitled')} (id={item.get('id')}) | "
                f"category={item.get('category', 'Other')} | "
                f"status={item.get('status', 'suggested')} | "
                f"priority={item.get('priority_score', 5)}/10"
            )
            if item.get("reason_relevant"):
                entry += f" | why on radar: {item['reason_relevant']}"
            if item.get("updated_at"):
                entry += f" | last_updated={str(item['updated_at'])[:10]}"
            opportunity_lines.append(entry)
    else:
        opportunity_lines.append("- (none yet)")

    status_titles: Dict[str, List[str]] = {
        "suggested": [],
        "interested": [],
        "exploring": [],
        "applied": [],
        "completed": [],
        "archived": [],
    }
    for item in opportunities:
        status = str(item.get("status") or "suggested").strip().lower()
        status_titles.setdefault(status, []).append(str(item.get("title") or "Untitled"))
    lifecycle_lines = []
    for status, titles in status_titles.items():
        if titles:
            label = status
            if status in ("interested", "exploring", "applied"):
                label = f"{status} (in motion)"
            shown = ", ".join(titles[:5])
            if len(titles) > 5:
                shown += f", and {len(titles) - 5} more"
            lifecycle_lines.append(f"- {label}: {shown}")
    lifecycle_block = "\n".join(lifecycle_lines) if lifecycle_lines else "- (no activity yet)"

    history_lines = []
    for item in history:
        role = str(item.get("role") or "user").capitalize()
        content = str(item.get("content") or "")
        if len(content) > 600:
            content = content[:600] + "…"
        chat_label = item.get("chat") or "Unknown chat"
        history_lines.append(f"[{chat_label}] {role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "- (no conversation yet)"

    plan_block = "- (no plan generated yet)"
    if plans:
        plan_lines = []
        for entry in plans:
            for item in entry.get("items", []):
                plan_lines.append(f"[{entry.get('chat')}] {item}")
        if plan_lines:
            plan_block = "- " + "\n- ".join(plan_lines)

    prompt = (
        f"{HUMAN_PROMPT}You are the North Star engine of a student career workspace. Your single job is to answer one "
        "question: what should this student focus on RIGHT NOW based on EVERYTHING we know about them, across ALL of "
        "their chats? "
        "You are a synthesis engine, NOT a recommendation engine and NOT a job-title predictor. "
        "Do NOT invent opportunities, programs, degrees, employers, or facts. Everything must be grounded in the "
        "profile, chats, opportunities, opportunity statuses, and conversations below. "
        "Students are not confused about which careers exist; they are confused about what to do next. Reduce that "
        "confusion and move them forward. You are the student's career command center, not a chat summary."
        "\n\n"
        "Student profile (identity, shared across every chat):\n"
        f"University: {context['university']}\n"
        f"Major: {context['major']}\n"
        f"Year: {context['year']}\n\n"
        "This student's chats (each is a distinct pursuit/topic; use these as the student's stated goals):\n"
        f"{chats_block}\n\n"
        "Career Radar - all tracked opportunities across every chat and their whole lifecycle (statuses and priorities "
        "are cumulative history):\n"
        + "\n".join(opportunity_lines)
        + "\n\n"
        "Opportunity lifecycle snapshot:\n"
        f"{lifecycle_block}\n\n"
        "Recent conversation history across all chats (tagged by which chat each message belongs to):\n"
        f"{history_block}\n\n"
        "Latest action plan per chat:\n"
        f"{plan_block}\n\n"
        "Produce a JSON object with exactly these keys:\n"
        "- current_direction: object with direction (a broad direction label only, e.g. 'Technology', 'AI / Research', "
        "'Consulting', 'Entrepreneurship', 'Healthcare', 'Finance'. NEVER a job title), confidence (integer 0-100, "
        "omitted/null when evidence is thin), why (1-2 sentences grounded in evidence), "
        "evidence (array of 1-4 short evidence strings, each drawn verbatim from the profile, radar, or conversations), "
        "alternative_directions (array of up to 2 short labels, may be empty).\n"
        "- priorities: array of 3 objects, each with title, why (why it matters right now), impact (integer 1-10), "
        "recommended_action (a concrete executable action), action_chip (ONE short actionable sentence).\n"
        "- risks: array of up to 3 objects, each with title, explanation (why it is a bottleneck), severity (integer 1-10), "
        "suggested_action (concrete), action_chip (ONE short actionable sentence). Use [] only if there is genuinely "
        "nothing evidence-based to flag.\n"
        "- upcoming_opportunities: array of up to 3 objects drawn ONLY from the radar opportunities above, each with "
        "title, why (why it deserves attention now, mention timing if known), impact (integer 1-10), "
        "recommended_action (concrete), action_chip (ONE short actionable sentence).\n"
        "\n"
        "Rules:\n"
        "- Always base the analysis on the WHOLE profile, radar, and conversations - never only the most recent chat.\n"
        "- ALWAYS produce content whenever evidence exists. One priority from profile goals alone is enough evidence. "
        "One tracked opportunity is enough evidence. Never say 'not enough evidence', never ask the user to chat more, "
        "and never reply with empty arrays when the profile, radar, or conversations exist. Only when there is zero "
        "evidence at all may you return \"current_direction\" with an empty direction and empty arrays.\n"
        "- Give each item a concrete, one-sentence action chip that MOVES THE STUDENT FORWARD and that they can paste "
        "into the chat to take the action (e.g. 'Draft an email to a professor about joining their lab', 'Find MLH "
        "hackathons within 100 miles of my university this semester'). Never use generic text like 'Tell me more' or "
        "'Explore options'.\n"
        "- Every Future is calibrated toward momentum: the next most useful action now, followed by the action after that.\n"
        "- Confidence must be honest. Low evidence = low or null confidence.\n"
        "- Keep the whole JSON output under ~700 words and no text outside the JSON."
        f"{AI_PROMPT}"
    )
    return prompt


def _score_int(value: Any) -> int:
    try:
        return max(1, min(10, int(value)))
    except (TypeError, ValueError):
        return 5


def _direction_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    else:
        confidence = max(0, min(100, int(confidence)))
    alternatives = raw.get("alternative_directions") or []
    if not isinstance(alternatives, list):
        alternatives = []
    evidence = raw.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    return {
        "direction": str(raw.get("direction") or "").strip() or "Exploring",
        "confidence": confidence,
        "why": str(raw.get("why") or "").strip(),
        "evidence": [str(e).strip() for e in evidence if str(e).strip()][:4],
        "alternative_directions": [str(a).strip() for a in alternatives if str(a).strip()][:2],
    }


def _item_list(raw: Any, chip_key: str, why_key: str, score_key: str = "impact") -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw[:3]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        item: Dict[str, Any] = {
            "title": title,
            "why": str(entry.get(why_key) or entry.get("why") or "").strip(),
            "impact": _score_int(entry.get(score_key)),
            "recommended_action": str(entry.get("recommended_action") or entry.get("suggested_action") or "").strip(),
            "action_chip": str(entry.get(chip_key) or "").strip(),
        }
        if score_key == "severity":
            item["severity"] = item.pop("impact")
        items.append(item)
    return items


def normalize_north_star(parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        return {
            "current_direction": {"direction": "Exploring", "confidence": None, "why": "", "alternative_directions": []},
            "priorities": [],
            "risks": [],
            "upcoming_opportunities": [],
        }
    direction_raw = parsed.get("current_direction") if isinstance(parsed.get("current_direction"), dict) else {}
    return {
        "current_direction": _direction_dict(direction_raw),
        "priorities": _item_list(parsed.get("priorities"), "action_chip", "why", "impact"),
        "risks": _item_list(parsed.get("risks"), "action_chip", "explanation", "severity"),
        "upcoming_opportunities": _item_list(parsed.get("upcoming_opportunities"), "action_chip", "why", "impact"),
    }


def diff_north_star(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> List[str]:
    """Plain-Python comparison of two normalized North Star payloads, so the
    "living profile" is visibly dynamic without spending another Claude call
    just to describe its own diff."""
    if not previous:
        return ["Initial North Star generated."]

    changes: List[str] = []

    prev_direction = str((previous.get("current_direction") or {}).get("direction") or "").strip()
    new_direction = str((current.get("current_direction") or {}).get("direction") or "").strip()
    if prev_direction and new_direction and prev_direction != new_direction:
        changes.append(f"Direction shifted from \"{prev_direction}\" to \"{new_direction}\".")

    for key, singular in (("priorities", "priority"), ("risks", "risk"), ("upcoming_opportunities", "upcoming opportunity")):
        prev_titles = {str(item.get("title") or "").strip().lower() for item in (previous.get(key) or [])}
        new_titles = {str(item.get("title") or "").strip().lower() for item in (current.get(key) or [])}
        added = new_titles - prev_titles
        removed = prev_titles - new_titles
        if added:
            changes.append(f"{len(added)} new {singular}{'s' if len(added) != 1 else ''} surfaced.")
        if removed:
            changes.append(f"{len(removed)} {singular}{'s' if len(removed) != 1 else ''} resolved or dropped off.")

    if not changes:
        changes.append("No material change since the last analysis.")
    return changes


def load_resume_grounding_document() -> str:
    """Read the curated resume best-practices document that all resume
    feedback must be grounded in. Raises rather than falling back to any
    built-in knowledge - feedback must be traceable to this file, not
    fabricated when it's missing."""
    try:
        with open(RESUME_GROUNDING_DOCUMENT_PATH, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=(
                "resume-grounding-document.md was not found in the project root. "
                "Resume feedback requires this file to be present."
            ),
        )
    if not content:
        raise HTTPException(status_code=500, detail="resume-grounding-document.md is empty.")
    return content


class ResumeExtractionError(Exception):
    """A user-facing document-parsing failure: unsupported type, corrupt
    file, empty content, or a parser error. Always safe to show str(exc) to
    the caller - never wraps a raw internal exception message."""


_docling_converter = None
_docling_stream_class = None


def _get_docling_classes():
    """Lazily import and cache Docling's DocumentConverter instance and
    DocumentStream class together, as the single import point for both.

    Imported lazily (not at module top-level) on purpose: docling is a heavy
    dependency, and a bad import here must only break PDF/DOCX extraction,
    not crash the entire app at startup for every other endpoint. Doing both
    imports here - rather than a second lazy import inside
    _extract_text_with_docling's try/except - matters: otherwise a missing-
    dependency ImportError gets caught by that function's generic
    parse-failure handler and misreported as "corrupted file" instead of
    "not installed."
    """
    global _docling_converter, _docling_stream_class
    if _docling_converter is None or _docling_stream_class is None:
        try:
            from docling.document_converter import DocumentConverter
            from docling.datamodel.base_models import DocumentStream
        except ImportError as exc:
            logger.error("Docling is not installed/importable: %s", exc)
            raise ResumeExtractionError(
                "PDF/DOCX parsing isn't available right now. Please try again later or paste your resume text directly."
            )
        _docling_converter = DocumentConverter()
        _docling_stream_class = DocumentStream
    return _docling_converter, _docling_stream_class


def _extract_text_from_txt(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw_bytes.decode("latin-1")
        except UnicodeDecodeError:
            raise ResumeExtractionError(
                "Could not read that text file. Please make sure it's a plain-text file and try again."
            )


def _extract_text_with_docling(raw_bytes: bytes, extension: str) -> str:
    """PDF/DOCX -> Markdown via Docling, preserving headings/bullets/tables/
    reading order rather than flattening to an unstructured blob. Runs
    entirely in memory (DocumentStream over BytesIO) - no temp file is ever
    written to disk for an untrusted upload."""
    converter, document_stream_cls = _get_docling_classes()
    try:
        stream = document_stream_cls(name=f"resume{extension}", stream=io.BytesIO(raw_bytes))
        result = converter.convert(stream)
        markdown = result.document.export_to_markdown()
    except ResumeExtractionError:
        raise
    except Exception as exc:
        logger.warning("Docling failed to parse uploaded resume (%s): %s", extension, exc)
        raise ResumeExtractionError(
            "That file couldn't be read - it may be corrupted, password-protected, or in an unsupported format. "
            "Please try a different file or paste your resume text directly."
        )
    return markdown


def extract_resume_text(filename: str, content_type: Optional[str], raw_bytes: bytes) -> str:
    """Normalize an uploaded resume (PDF/DOCX/TXT) into plain/Markdown text.
    Everything downstream of this function (the review prompts, /document-
    reviews) only ever sees the returned string - it never needs to know
    which format the original file was."""
    extension = os.path.splitext(filename or "")[1].lower()

    if extension not in SUPPORTED_RESUME_UPLOAD_EXTENSIONS:
        raise ResumeExtractionError(
            f"Unsupported file type '{extension or 'unknown'}'. Please upload a PDF, DOCX, or TXT file."
        )

    allowed_mimes = RESUME_UPLOAD_MIME_TYPES_BY_EXTENSION.get(extension, set())
    if content_type and content_type not in allowed_mimes and content_type not in GENERIC_UPLOAD_MIME_TYPES:
        raise ResumeExtractionError(
            f"That file doesn't look like a valid {extension} file. Please double-check the file and try again."
        )

    if len(raw_bytes) > MAX_RESUME_UPLOAD_BYTES:
        raise ResumeExtractionError("That file is too large. Please upload a resume under 10 MB.")

    if not raw_bytes:
        raise ResumeExtractionError("The uploaded file is empty.")

    if extension == ".txt":
        # Simplest appropriate handling for plain text - no reason to route
        # it through Docling's document-layout pipeline.
        text = _extract_text_from_txt(raw_bytes)
    else:
        text = _extract_text_with_docling(raw_bytes, extension)

    text = text.strip()
    if not text:
        raise ResumeExtractionError(
            "No readable text could be extracted from that file. Please try a different file or paste your resume text directly."
        )
    return text


def format_role_context(role_context: Optional[Dict[str, Any]]) -> str:
    if not role_context:
        return ""
    lines = []
    title = str(role_context.get("title") or "").strip()
    company = str(role_context.get("company") or "").strip()
    industry = str(role_context.get("industry") or "").strip()
    job_posting = str(role_context.get("job_posting") or "").strip()
    if title:
        lines.append(f"Target role: {title}")
    if company:
        lines.append(f"Company/organization: {company}")
    if industry:
        lines.append(f"Industry/field: {industry}")
    if job_posting:
        lines.append(f"Pasted job posting / link (context only, not browsed):\n{job_posting}")
    return "\n".join(lines)


def build_role_search_query(role_context: Optional[Dict[str, Any]]) -> str:
    if not role_context:
        return "resume expectations and norms"
    parts = [
        str(role_context.get("title") or "").strip(),
        str(role_context.get("company") or "").strip(),
        str(role_context.get("industry") or "").strip(),
        "resume expectations qualifications norms",
    ]
    return " ".join(part for part in parts if part)


def compose_resume_review_prompt(
    grounding_doc: str,
    resume_text: str,
    intent: str,
    role_context: Optional[Dict[str, Any]],
    search_summary: Optional[str],
) -> str:
    role_block = format_role_context(role_context)
    search_block = (
        f"\nLive search results on role/company expectations:\n{search_summary}\n"
        if search_summary
        else ""
    )
    role_alignment_instruction = (
        "\n- role_alignment: a dedicated \"How this aligns with "
        f"{(role_context or {}).get('title') or 'the target role'}\" section combining the grounding "
        "document's baseline principles with the live search results above. Ground every claim in "
        "either the document or the search results - never invent role expectations."
        if intent == "tailor_to_role"
        else ""
    )

    prompt = (
        f"{HUMAN_PROMPT}You are a resume feedback assistant for college students. Your ONLY job is to "
        "strengthen a resume the student has ALREADY WRITTEN. You never author a resume from scratch, "
        "never invent a full section or bullet the student didn't write, and never produce a complete "
        "replacement resume - only feedback on what's there.\n\n"
        "CRITICAL GROUNDING RULE: base your feedback ONLY on the principles in the grounding document "
        "below. Do not draw on general internet knowledge of resume writing beyond what this document "
        "states. Where a suggestion reflects a specific principle from the document, briefly say which "
        "one (e.g. \"per the document's guidance on quantifying impact\") so the feedback is traceable, "
        "not just asserted.\n\n"
        "Grounding document (resume-grounding-document.md, full contents):\n"
        "-----\n"
        f"{grounding_doc}\n"
        "-----\n\n"
        "Student's resume (verbatim, as submitted):\n"
        "-----\n"
        f"{resume_text}\n"
        "-----\n\n"
        f"{f'Role context:{chr(10)}{role_block}{chr(10)}{chr(10)}' if role_block else ''}"
        f"{search_block}"
        "Produce a JSON object with exactly these keys:\n"
        "- strengths: array of short strings, specific things the resume already does well\n"
        "- areas_to_improve: array of short strings, concrete gaps grounded in the document\n"
        "- line_suggestions: array of short strings, each a specific line/bullet-level rewrite "
        "suggestion (quote or reference the original line)\n"
        "- overall_summary: 2-3 sentence summary\n"
        f"{role_alignment_instruction}\n"
        "Do not add any additional text outside the JSON object."
        f"{AI_PROMPT}"
    )
    return prompt


def compose_resume_followup_prompt(
    grounding_doc: str,
    resume_text: str,
    role_context: Optional[Dict[str, Any]],
    thread_so_far: List[Dict[str, Any]],
    user_message: str,
) -> str:
    role_block = format_role_context(role_context)
    thread_lines = []
    for row in thread_so_far:
        feedback = row.get("ai_feedback") or {}
        if row.get("intent") == RESUME_FOLLOWUP_INTENT:
            thread_lines.append(f"Student: {feedback.get('user_message', '')}")
            thread_lines.append(f"You: {feedback.get('assistant_response', '')}")
        else:
            thread_lines.append(
                "You (initial review): "
                f"strengths={feedback.get('strengths')}; areas_to_improve={feedback.get('areas_to_improve')}; "
                f"line_suggestions={feedback.get('line_suggestions')}; summary={feedback.get('overall_summary')}"
            )
    thread_block = "\n".join(thread_lines) if thread_lines else "(no prior turns)"

    prompt = (
        f"{HUMAN_PROMPT}You are continuing a resume feedback conversation. Same rules as before: you "
        "strengthen what the student already wrote, you never author new resume content from scratch, "
        "and your feedback must stay grounded only in the document below, not general knowledge.\n\n"
        "Grounding document (resume-grounding-document.md, full contents):\n"
        "-----\n"
        f"{grounding_doc}\n"
        "-----\n\n"
        "Student's resume (verbatim):\n"
        "-----\n"
        f"{resume_text}\n"
        "-----\n\n"
        f"{f'Role context:{chr(10)}{role_block}{chr(10)}{chr(10)}' if role_block else ''}"
        "Conversation so far:\n"
        f"{thread_block}\n\n"
        f"Student's new message: {user_message}\n\n"
        "Produce a JSON object with exactly one key, assistant_response, containing your reply. "
        "Do not add any additional text outside the JSON object."
        f"{AI_PROMPT}"
    )
    return prompt


def _string_list(raw: Any, limit: int = 8) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()][:limit]


def normalize_resume_review(parsed: Optional[Dict[str, Any]], intent: str) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        return {"strengths": [], "areas_to_improve": [], "line_suggestions": [], "overall_summary": "", "role_alignment": ""}
    return {
        "strengths": _string_list(parsed.get("strengths")),
        "areas_to_improve": _string_list(parsed.get("areas_to_improve")),
        "line_suggestions": _string_list(parsed.get("line_suggestions")),
        "overall_summary": str(parsed.get("overall_summary") or "").strip(),
        "role_alignment": str(parsed.get("role_alignment") or "").strip() if intent == "tailor_to_role" else "",
    }


# def call_claude(prompt: str, max_tokens: int = 900, temperature: float = 0.7) -> str:
#     response = anthropic.completions.create(
#         model=ANTHROPIC_MODEL,
#         prompt=prompt,
#         max_tokens_to_sample=max_tokens,
#         temperature=temperature,
#         stop_sequences=[HUMAN_PROMPT],
#     )
#     return response["completion"] if isinstance(response, dict) else getattr(response, "completion", "")

def call_claude(prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
    response = anthropic.messages.create(
        model=ANTHROPIC_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        stop_sequences=[HUMAN_PROMPT],
    )

    content_blocks = getattr(response, "content", []) or []
    assistant_text = ""
    for block in content_blocks:
        if isinstance(block, dict):
            assistant_text += block.get("text", "") or ""
        else:
            assistant_text += getattr(block, "text", "") or ""
    return assistant_text.strip()

def get_profile_by_device(device_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not device_id:
        return None
    response = execute_db(
        db_table("profiles")
        .select("id, university, major, year, created_at, updated_at")
        .eq("device_id", device_id)
    )
    data = getattr(response, "data", None) or []
    return data[0] if data else None


def require_profile(device_id: Optional[str]) -> Dict[str, Any]:
    profile = get_profile_by_device(device_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No profile found for this device. Complete onboarding first.",
        )
    return profile


def get_session(session_id: int) -> Dict[str, str]:
    """Return a chat's context, joining the profile it belongs to for
    university/major/year (the single source of truth for identity fields).
    `goals` remains this chat's own per-chat topic.
    """
    response = execute_db(
        db_table("sessions")
        .select("id, goals, created_at, profile_id, profiles(university, major, year)")
        .eq("id", session_id)
    )
    if not getattr(response, "data", None):
        raise HTTPException(status_code=404, detail="Session not found")
    row = response.data[0]
    profile = row.get("profiles") or {}
    return {
        "id": row["id"],
        "goals": row.get("goals") or "",
        "university": profile.get("university") or "",
        "major": profile.get("major") or "",
        "year": profile.get("year") or "",
    }


def get_message_history(session_id: int) -> List[Dict[str, str]]:
    response = execute_db(
        db_table("messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
    )
    return response.data or []


def normalize_plan_items(raw_plan: Any) -> List[str]:
    if isinstance(raw_plan, list):
        return [str(item).strip() for item in raw_plan if str(item).strip()]
    if isinstance(raw_plan, str):
        try:
            parsed = json.loads(raw_plan)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [item.strip() for item in re.split(r"\n+", raw_plan) if item.strip()]
    return []


def get_latest_plan(session_id: int) -> List[str]:
    response = execute_db(
        db_table("plans")
        .select("plan_items")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    if not getattr(response, "data", None):
        return []
    return normalize_plan_items(response.data[0].get("plan_items"))


def get_profile_chats(profile_id: int) -> List[Dict[str, Any]]:
    response = execute_db(
        db_table("sessions")
        .select("id, goals, created_at")
        .eq("profile_id", profile_id)
        .order("created_at", desc=False)
    )
    return getattr(response, "data", None) or []


def get_profile_opportunities(chat_ids: List[int]) -> List[Dict[str, Any]]:
    if not chat_ids:
        return []
    response = execute_db(
        db_table("opportunities")
        .select("*")
        .in_("session_id", chat_ids)
        .order("priority_score", desc=True)
        .order("updated_at", desc=True)
    )
    return getattr(response, "data", None) or []


def get_profile_history(chat_ids: List[int], goals_by_id: Dict[int, str], limit_per_chat: int = 30) -> List[Dict[str, Any]]:
    """Return recent messages across all of a profile's chats, each tagged
    with the chat's goal so the North Star prompt can attribute evidence to
    the right pursuit."""
    tagged: List[Dict[str, Any]] = []
    for chat_id in chat_ids:
        response = execute_db(
            db_table("messages")
            .select("role, content, created_at")
            .eq("session_id", chat_id)
            .order("created_at", desc=True)
            .limit(limit_per_chat)
        )
        rows = list(reversed(getattr(response, "data", None) or []))
        chat_label = goals_by_id.get(chat_id) or f"Chat {chat_id}"
        for row in rows:
            tagged.append({"chat": chat_label, "role": row.get("role"), "content": row.get("content")})
    return tagged


def get_profile_plans(chat_ids: List[int], goals_by_id: Dict[int, str]) -> List[Dict[str, Any]]:
    plans: List[Dict[str, Any]] = []
    for chat_id in chat_ids:
        items = get_latest_plan(chat_id)
        if items:
            plans.append({"chat": goals_by_id.get(chat_id) or f"Chat {chat_id}", "items": items})
    return plans


def get_session_document_reviews(session_id: int) -> List[Dict[str, Any]]:
    response = execute_db(
        db_table("document_reviews")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
    )
    return getattr(response, "data", None) or []


def get_document_review_thread(session_id: int, document_content: str) -> List[Dict[str, Any]]:
    """Rows in the same chat with matching document_content form one review
    thread (the initial review plus every follow-up on that same resume).
    There's no parent/thread-id column in document_reviews by design, so this
    is how a thread is reconstructed."""
    response = execute_db(
        db_table("document_reviews")
        .select("*")
        .eq("session_id", session_id)
        .eq("document_content", document_content)
        .order("created_at", desc=False)
    )
    return getattr(response, "data", None) or []


@app.post("/profile")
async def create_profile(
    payload: ProfileCreate, x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
) -> Dict[str, Any]:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="X-Device-Id header is required")

    existing = get_profile_by_device(x_device_id)
    if existing:
        return {"profile": existing}

    response = execute_db(
        db_table("profiles")
        .insert(
            {
                "university": payload.university.strip(),
                "major": payload.major.strip(),
                "year": payload.year.strip(),
                "device_id": x_device_id,
            }
        )
        .select("id, university, major, year, created_at, updated_at")
    )
    if not getattr(response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to create profile")
    return {"profile": response.data[0]}


@app.get("/profile")
async def read_profile(x_device_id: Optional[str] = Header(None, alias="X-Device-Id")) -> Dict[str, Any]:
    return {"profile": require_profile(x_device_id)}


@app.patch("/profile")
async def update_profile(
    payload: ProfileUpdate, x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
) -> Dict[str, Any]:
    profile = require_profile(x_device_id)
    updates = {k: v.strip() for k, v in payload.dict(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No update fields provided")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    response = execute_db(
        db_table("profiles")
        .update(updates)
        .eq("id", profile["id"])
        .select("id, university, major, year, created_at, updated_at")
    )
    if not getattr(response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to update profile")
    return {"profile": response.data[0]}


@app.get("/sessions")
async def list_sessions(x_device_id: Optional[str] = Header(None, alias="X-Device-Id")) -> Dict[str, Any]:
    profile = get_profile_by_device(x_device_id)
    if not profile:
        return {"sessions": []}
    response = execute_db(
        db_table("sessions")
        .select("id, goals, created_at")
        .eq("profile_id", profile["id"])
        .order("created_at", desc=True)
    )
    sessions = getattr(response, "data", None) or []
    return {"sessions": sessions}


@app.post("/session")
async def create_session(
    session: SessionCreate, x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
) -> Dict[str, int]:
    profile = require_profile(x_device_id)
    goals = session.goals.strip()
    if not goals:
        raise HTTPException(status_code=400, detail="goals is required")

    response = execute_db(
        db_table("sessions")
        .insert({"profile_id": profile["id"], "goals": goals})
        .select("id")
    )

    if not getattr(response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to create session")

    created_session_id = response.data[0]["id"]
    return {"session_id": created_session_id}


@app.post("/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    session = get_session(payload.session_id)
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    insert_response = execute_db(
        db_table("messages").insert(
            {"session_id": payload.session_id, "role": "user", "content": user_text}
        )
    )
    if not getattr(insert_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save user message")

    history = get_message_history(payload.session_id)
    opportunity_service = OpportunityService()
    existing_opportunities = opportunity_service.get_session_opportunities(payload.session_id)
    search_summary = None
    search_triggered = should_run_search(user_text)
    if search_triggered:
        query = f"{session['university']} career opportunities {user_text}"
        results = run_web_search(query)
        if results:
            search_summary = format_search_summary(query, results)

    prompt = compose_coach_prompt(session, history, user_text, search_summary, opportunities=existing_opportunities)
    raw_output = call_claude(prompt)
    parsed = parse_json_response(raw_output)
    logger.info("Claude raw_output length=%s", len(raw_output))
    logger.info("Claude parsed_payload=%s", parsed)
    if parsed is None or "assistant_response" not in parsed:
        logger.warning(
            "Claude payload fallback triggered; parse_json_response returned %s for raw output %s",
            parsed,
            raw_output,
        )
        parsed = {
            "assistant_response": salvage_assistant_text(raw_output),
            "suggested_replies": [
                "Tell me more about relevant campus opportunities.",
                "How can I approach employers in my field?",
                "What should I do next to build my career readiness?",
            ],
            "career_radar_updates": [],
        }
    else:
        suggested = parsed.get("suggested_replies")
        if not isinstance(suggested, list) or not suggested:
            parsed["suggested_replies"] = [
                "Tell me more about relevant campus opportunities.",
                "How can I approach employers in my field?",
                "What should I do next to build my career readiness?",
            ]
        if not isinstance(parsed.get("career_radar_updates"), list):
            parsed["career_radar_updates"] = []

    assistant_text = str(parsed.get("assistant_response") or "").strip()
    if not assistant_text and isinstance(parsed.get("assistant_response"), str):
        assistant_text = str(parsed["assistant_response"]).strip()
    save_response = execute_db(
        db_table("messages").insert(
            {"session_id": payload.session_id, "role": "assistant", "content": assistant_text}
        )
    )
    if not getattr(save_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save assistant response")

    def _remember(opportunity: Dict[str, Any]) -> None:
        """Keep existing_opportunities current as clauses are applied so a
        later clause in the SAME Claude response (e.g. "add X" followed by
        "update X") resolves against the row just written instead of the
        stale snapshot fetched at the top of the request."""
        opp_id = opportunity.get("id")
        for index, existing_item in enumerate(existing_opportunities):
            if existing_item.get("id") == opp_id:
                existing_opportunities[index] = opportunity
                return
        existing_opportunities.append(opportunity)

    applied_updates = []
    priority_signal = detect_priority_signal(user_text)
    for update in parsed.get("career_radar_updates", []):
        if not isinstance(update, dict):
            continue
        action = str(update.get("action") or "").strip().lower()
        if action not in {"add", "update", "archive", "reprioritize"}:
            continue

        if action == "add":
            existing = opportunity_service.find_matching_opportunity(
                payload.session_id,
                title=str(update.get("title") or "").strip() or None,
                source_url=str(update.get("source_url") or "").strip() or None,
                category=str(update.get("category") or "").strip() or None,
                existing_opportunities=existing_opportunities,
            )
            if existing:
                updated = merge_opportunity_update(opportunity_service, existing, update, payload.session_id)
                _remember(updated)
                applied_updates.append({"action": "update", "opportunity": updated, "matched": True})
                continue
            created = opportunity_service.create_opportunity(payload.session_id, {
                "title": update.get("title") or "Untitled opportunity",
                "category": update.get("category"),
                "description": update.get("description") or "",
                "reason_relevant": update.get("reason_relevant") or "",
                "source_url": update.get("source_url"),
                "priority_score": update.get("priority_score") or 5 + max(priority_signal, 0),
                "status": update.get("status") or "suggested",
            })
            _remember(created)
            applied_updates.append({"action": "add", "opportunity": created})
        elif action in {"update", "reprioritize", "archive"}:
            existing = resolve_opportunity_target(opportunity_service, existing_opportunities, update, payload.session_id)
            if existing is None:
                logger.info("Career Radar update skipped: no match for %s", update.get("title") or update.get("opportunity_id"))
                continue
            existing = dict(existing)
            priority_score = update.get("priority_score")
            if priority_score is None and priority_signal:
                existing_priority = int(existing.get("priority_score") or 5)
                priority_score = max(1, min(10, existing_priority + priority_signal))
            if action == "archive":
                archived = opportunity_service.archive_opportunity(int(existing["id"]))
                _remember(archived)
                applied_updates.append({"action": "archive", "opportunity": archived})
            elif action == "reprioritize":
                if priority_score is None:
                    continue
                updated = opportunity_service.update_priority(int(existing["id"]), normalize_priority_score(priority_score))
                _remember(updated)
                applied_updates.append({"action": "reprioritize", "opportunity": updated})
            else:
                clause = dict(update)
                if priority_score is not None:
                    clause["priority_score"] = priority_score
                updated = merge_opportunity_update(opportunity_service, existing, clause, payload.session_id)
                _remember(updated)
                applied_updates.append({"action": "update", "opportunity": updated, "matched": True})

    return {
        "assistant_response": assistant_text,
        "suggested_replies": parsed["suggested_replies"],
        "search_used": bool(search_summary),
        "career_radar_updates": applied_updates,
    }


@app.post("/plan")
async def generate_plan(payload: PlanRequest) -> Dict[str, Any]:
    session = get_session(payload.session_id)
    history = get_message_history(payload.session_id)
    if not history:
        raise HTTPException(status_code=404, detail="No conversation history found for this session")

    prompt = compose_plan_prompt(session, history)
    raw_output = call_claude(prompt, max_tokens=600)
    plan_json = None
    try:
        extracted = raw_output[raw_output.index("["): raw_output.rindex("]") + 1]
        plan_json = json.loads(extracted)
    except Exception:
        plan_json = None

    if not isinstance(plan_json, list) or not plan_json:
        plan_json = [item.strip() for item in re.split(r"\n+", raw_output) if item.strip()][:6]

    plan_json = normalize_plan_items(plan_json)

    save_response = execute_db(
        db_table("plans").insert(
            {"session_id": payload.session_id, "plan_items": plan_json}
        )
    )
    if not getattr(save_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save generated plan")

    return {"plan": plan_json}


def get_latest_north_star_snapshot(profile_id: int) -> Optional[Dict[str, Any]]:
    response = execute_db(
        db_table("north_star_snapshots")
        .select("payload, created_at")
        .eq("profile_id", profile_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    data = getattr(response, "data", None) or []
    return data[0] if data else None


def save_north_star_snapshot(profile_id: int, payload: Dict[str, Any]) -> None:
    execute_db(db_table("north_star_snapshots").insert({"profile_id": profile_id, "payload": payload}))


@app.post("/north-star")
async def generate_north_star(x_device_id: Optional[str] = Header(None, alias="X-Device-Id")) -> Dict[str, Any]:
    """Cross-chat synthesis for the caller's profile. Always computed fresh -
    there is no cache to go stale here (see HISTORY / PRD notes on the prior
    in-memory cache bug); each run is persisted to north_star_snapshots so we
    can show when it last changed and what changed."""
    profile = require_profile(x_device_id)
    profile_context = {
        "university": profile.get("university") or "",
        "major": profile.get("major") or "",
        "year": profile.get("year") or "",
    }

    chats = get_profile_chats(profile["id"])
    chat_ids = [int(chat["id"]) for chat in chats]
    goals_by_id = {int(chat["id"]): str(chat.get("goals") or "") for chat in chats}
    opportunities = get_profile_opportunities(chat_ids)
    history = get_profile_history(chat_ids, goals_by_id)
    plans = get_profile_plans(chat_ids, goals_by_id)

    has_evidence = bool(
        profile_context["university"].strip()
        or profile_context["major"].strip()
        or profile_context["year"].strip()
        or chats
        or opportunities
        or history
        or plans
    )

    prompt = compose_north_star_prompt(profile_context, chats, opportunities, history, plans)

    def synthesize(max_tokens: int) -> Optional[Dict[str, Any]]:
        raw_output = call_claude(prompt, max_tokens=max_tokens)
        logger.info("North Star raw_output length=%s", len(raw_output))
        parsed = parse_json_response(raw_output)
        if parsed is None:
            logger.warning("North Star parse failed; raw output %r", raw_output[:300])
        return parsed

    parsed = synthesize(2400)
    if parsed is None and has_evidence:
        # A single retry: truncated/failed JSON must not collapse a real analysis to "Exploring"
        # because there could be plenty of evidence to build a North Star from.
        parsed = synthesize(2400)
        if parsed is None:
            logger.warning("North Star retry also failed to parse")
    result = normalize_north_star(parsed)
    result["has_evidence"] = has_evidence

    if not has_evidence:
        result["whats_new"] = []
        result["generated_at"] = None
        return result

    previous_snapshot = get_latest_north_star_snapshot(profile["id"])
    previous_payload = previous_snapshot.get("payload") if previous_snapshot else None
    result["whats_new"] = diff_north_star(previous_payload, result)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    save_north_star_snapshot(profile["id"], result)
    return result



@app.post("/opportunities")
async def create_opportunity(payload: OpportunityCreate) -> Dict[str, Any]:
    get_session(payload.session_id)
    service = OpportunityService()
    created = service.create_opportunity(payload.session_id, payload.dict())
    return {"opportunity": created}


@app.get("/opportunities/{session_id}")
async def list_opportunities(session_id: int) -> Dict[str, Any]:
    get_session(session_id)
    service = OpportunityService()
    return {"opportunities": service.get_session_opportunities(session_id)}


@app.patch("/opportunities/{opportunity_id}")
async def update_opportunity(opportunity_id: int, payload: OpportunityUpdate) -> Dict[str, Any]:
    service = OpportunityService()
    updated = service.update_opportunity(opportunity_id, payload.dict(exclude_none=True))
    return {"opportunity": updated}


@app.delete("/opportunities/{opportunity_id}")
async def delete_opportunity(opportunity_id: int) -> Dict[str, Any]:
    service = OpportunityService()
    archived = service.archive_opportunity(opportunity_id)
    return {"opportunity": archived}


@app.get("/career-radar/{session_id}")
async def career_radar(session_id: int) -> Dict[str, Any]:
    get_session(session_id)
    service = OpportunityService()
    return {"opportunities": service.get_session_opportunities(session_id)}


@app.get("/session/{session_id}/history")
async def session_history(session_id: int) -> Dict[str, Any]:
    session = get_session(session_id)
    messages = get_message_history(session_id)
    plan = get_latest_plan(session_id)
    return {"session": session, "messages": messages, "plan": plan}


@app.post("/resume-upload")
async def upload_resume(
    file: UploadFile = File(...), x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
) -> Dict[str, Any]:
    """Extract plain/Markdown text from an uploaded PDF, DOCX, or TXT resume
    (see extract_resume_text). Purely a transformation - nothing is written
    to Supabase here; the returned text is what the client then sends to
    /document-reviews exactly as if it had been pasted directly, so the rest
    of the review pipeline never needs to know the original file format."""
    require_profile(x_device_id)
    raw_bytes = await file.read()
    try:
        text = extract_resume_text(file.filename or "", file.content_type, raw_bytes)
    except ResumeExtractionError as exc:
        logger.warning(
            "Resume upload rejected: filename=%r content_type=%r size=%s reason=%s",
            file.filename, file.content_type, len(raw_bytes), exc,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    return {"document_content": text}


@app.post("/document-reviews")
async def create_document_review(payload: DocumentReviewCreate) -> Dict[str, Any]:
    """Appointments: resume feedback (CV/cover letter/LinkedIn not built yet -
    see SUPPORTED_DOCUMENT_TYPES). Deliberately writes only to
    document_reviews - never to messages, opportunities, or
    north_star_snapshots, so reviews never leak into the Career Radar or
    North Star."""
    get_session(payload.session_id)

    if payload.document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Only resume reviews are supported currently.")

    document_content = payload.document_content.strip()
    if not document_content:
        raise HTTPException(status_code=400, detail="document_content is required")

    grounding_doc = load_resume_grounding_document()

    if payload.intent == RESUME_FOLLOWUP_INTENT:
        message = (payload.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        thread = get_document_review_thread(payload.session_id, document_content)
        prompt = compose_resume_followup_prompt(
            grounding_doc, document_content, payload.role_context, thread, message
        )
        raw_output = call_claude(prompt, max_tokens=1200)
        parsed = parse_json_response(raw_output)
        if parsed and isinstance(parsed.get("assistant_response"), str):
            assistant_response = parsed["assistant_response"].strip()
        else:
            assistant_response = salvage_assistant_text(raw_output)
        ai_feedback = {"user_message": message, "assistant_response": assistant_response}
        intent = RESUME_FOLLOWUP_INTENT
    elif payload.intent in RESUME_REVIEW_INTENTS:
        search_summary = None
        if payload.intent == "tailor_to_role":
            # Unlike the main coach's keyword-triggered search, this branch
            # always wants live results - that's the whole point of it.
            query = build_role_search_query(payload.role_context)
            results = run_web_search(query)
            if results:
                search_summary = format_search_summary(query, results)
        prompt = compose_resume_review_prompt(
            grounding_doc, document_content, payload.intent, payload.role_context, search_summary
        )
        raw_output = call_claude(prompt, max_tokens=2000)
        parsed = parse_json_response(raw_output)
        ai_feedback = normalize_resume_review(parsed, payload.intent)
        intent = payload.intent
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported intent: {payload.intent}")

    insert_payload = {
        "session_id": payload.session_id,
        "document_type": payload.document_type,
        "document_content": document_content,
        "intent": intent,
        "role_context": payload.role_context,
        "ai_feedback": ai_feedback,
    }
    response = execute_db(db_table("document_reviews").insert(insert_payload).select("*"))
    if not getattr(response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save document review")
    return {"review": response.data[0]}


@app.get("/document-reviews/{session_id}")
async def list_document_reviews(session_id: int) -> Dict[str, Any]:
    get_session(session_id)
    return {"reviews": get_session_document_reviews(session_id)}


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")
