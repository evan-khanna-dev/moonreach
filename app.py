import difflib
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
from fastapi import FastAPI, HTTPException
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


class SessionCreate(BaseModel):
    university: str
    major: str
    year: str
    goals: str


class ChatRequest(BaseModel):
    session_id: int
    message: str


class PlanRequest(BaseModel):
    session_id: int


class NorthStarRequest(BaseModel):
    session_id: int


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
        try:
            print("INSERT PAYLOAD", insert_payload)
            response = self.table.insert(insert_payload).select("*").execute()
        except Exception as exc:
            print("SUPABASE ERROR:", exc)

        print("RAW RESPONSE", response)
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

    if isinstance(parsed.get("assistant_response"), str):
        nested = try_parse(parsed["assistant_response"])
        if isinstance(nested, dict):
            merged = dict(parsed)
            for key in ("assistant_response", "suggested_replies", "career_radar_updates"):
                if key in nested:
                    merged[key] = nested[key]
            return merged

    return parsed


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
    opportunities: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    plan_items: List[str],
) -> str:
    opportunity_lines = []
    if opportunities:
        for item in opportunities[:10]:
            opportunity_lines.append(
                f"- {item.get('title', 'Untitled')} | id={item.get('id')} | category={item.get('category', 'Other')} | status={item.get('status', 'suggested')} | priority={item.get('priority_score', 5)}/10 | reason={item.get('reason_relevant', '')}"
            )
    else:
        opportunity_lines.append("- (none yet)")

    history_lines = []
    for item in history[-12:]:
        role = item["role"].capitalize()
        history_lines.append(f"{role}: {item['content']}")

    plan_block = "- (no plan generated yet)"
    if plan_items:
        plan_block = "- " + "\n- ".join(plan_items)

    prompt = (
        f"{HUMAN_PROMPT}You are the North Star engine of a student career workspace. "
        "Your single job is to answer one question about the student: what should they focus on RIGHT NOW? "
        "You are a synthesis engine, NOT a recommendation engine. Do NOT predict job titles. "
        "Do NOT invent opportunities, programs, or facts about the student. Everything you say must be grounded in the evidence below. "
        "Students are not confused about which jobs exist; they are confused about what to do next. Reduce that confusion."
        "\n\n"
        "Student profile:\n"
        f"University: {context['university']}\n"
        f"Major: {context['major']}\n"
        f"Year: {context['year']}\n"
        f"Career goals: {context['goals']}\n\n"
        "Career Radar (the student's tracked opportunities and statuses):\n"
        + "\n".join(opportunity_lines) + "\n\n"
        "Recent conversation history:\n"
        + ("\n".join(history_lines) if history_lines else "- (no conversation yet)") + "\n\n"
        "Latest action plan:\n"
        f"{plan_block}\n\n"
        "Produce a JSON object with exactly these keys:\n"
        "- current_direction: object with direction (a short trajectory label such as 'Technology -> AI', 'Product Management', 'Research'), "
        "confidence (an integer 0-100, ONLY if the evidence clearly supports that direction; omit or null when evidence is thin), "
        "why (1-2 sentences grounded in evidence), alternative_directions (array of up to 2 short labels, may be empty).\n"
        "- priorities: array of up to 3 objects, each with title, why (why it matters now), impact (integer 1-10), "
        "recommended_action (a concrete executable action), action_chip (ONE short sentence the student can send to the chat to act on it).\n"
        "- risks: array of up to 3 objects, each with title, explanation (why it is a bottleneck), severity (integer 1-10), "
        "suggested_action (concrete), action_chip (ONE short sentence to act on it). Only surface meaningful, evidence-based risks - "
        "no generic advice. Return [] if there is genuinely nothing to flag.\n"
        "- upcoming_opportunities: array of up to 3 objects selected from the radar above, each with title, why (why it deserves attention now, "
        "mention near-term timing if there is evidence), impact (integer 1-10), recommended_next_action (concrete), action_chip (ONE short sentence to act on it).\n"
        "\n"
        "Rules:\n"
        "- Priorities/recommendations should prioritize existing radar items: raising their status, applying, attending, preparing.\n"
        "- Confidence must be honest: do not fabricate a high confidence number. If this is a brand-new profile with almost no evidence, "
        "use a low confidence or null.\n"
        "- Action chips must be ONE short sentence the student could paste directly into the chat to take the action (e.g. "
        "help me draft an email about the STEP opportunity, find networking events at the university this month). "
        "Never use generic text like 'Tell me more' or 'make a plan'.\n"
        "- Keep the whole plan output under ~550 words.\n"
        "Do not add any text outside the JSON object."
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
    return {
        "direction": str(raw.get("direction") or "").strip() or "Exploring",
        "confidence": confidence,
        "why": str(raw.get("why") or "").strip(),
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
            "why": str(entry.get(why_key) or "").strip(),
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

def get_session(session_id: int) -> Dict[str, str]:
    response = execute_db(
        db_table("sessions")
        .select("id, university, major, year, goals")
        .eq("id", session_id)
    )
    if not getattr(response, "data", None):
        raise HTTPException(status_code=404, detail="Session not found")
    return response.data[0]


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


@app.get("/sessions")
async def list_sessions() -> Dict[str, Any]:
    response = execute_db(
        db_table("sessions")
        .select("id, university, major, year, goals, created_at")
        .order("created_at", desc=True)
    )
    sessions = getattr(response, "data", None) or []
    return {"sessions": sessions}


@app.post("/session")
async def create_session(session: SessionCreate) -> Dict[str, int]:
    response = execute_db(
        db_table("sessions")
        .insert(
            {
                "university": session.university.strip(),
                "major": session.major.strip(),
                "year": session.year.strip(),
                "goals": session.goals.strip(),
            }
        )
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
            "assistant_response": raw_output.strip(),
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
                applied_updates.append({"action": "archive", "opportunity": archived})
            elif action == "reprioritize":
                if priority_score is None:
                    continue
                updated = opportunity_service.update_priority(int(existing["id"]), normalize_priority_score(priority_score))
                applied_updates.append({"action": "reprioritize", "opportunity": updated})
            else:
                clause = dict(update)
                if priority_score is not None:
                    clause["priority_score"] = priority_score
                updated = merge_opportunity_update(opportunity_service, existing, clause, payload.session_id)
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


@app.post("/north-star")
async def generate_north_star(payload: NorthStarRequest) -> Dict[str, Any]:
    session = get_session(payload.session_id)
    opportunity_service = OpportunityService()
    opportunities = opportunity_service.get_session_opportunities(payload.session_id)
    history = get_message_history(payload.session_id)
    plan_items = get_latest_plan(payload.session_id)

    prompt = compose_north_star_prompt(session, opportunities, history, plan_items)
    raw_output = call_claude(prompt, max_tokens=900)
    parsed = parse_json_response(raw_output)
    logger.info("North Star raw_output length=%s", len(raw_output))
    if parsed is None:
        logger.warning(
            "North Star parse failed; raw output %r",
            raw_output[:300],
        )
    return normalize_north_star(parsed)


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


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")
