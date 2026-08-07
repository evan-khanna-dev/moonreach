import json
import os
import re
import html
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
    raw = raw.strip()
    for candidate in [raw, raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw and "}" in raw else [raw]]:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def compose_coach_prompt(
    context: Dict[str, str], history: List[Dict[str, str]], user_message: str, search_summary: Optional[str]
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
        "Recent conversation history:\n"
        f"{conversation_text}\n\n"
        f"User: {user_message}\n\n"
        f"{search_block}"
        "Respond only with a valid JSON object containing the keys\n"
        "- assistant_response: the coaching reply\n"
        "- suggested_replies: a short list of 3 next-user prompts relevant to the conversation\n"
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


# def call_claude(prompt: str, max_tokens: int = 900, temperature: float = 0.7) -> str:
#     response = anthropic.completions.create(
#         model=ANTHROPIC_MODEL,
#         prompt=prompt,
#         max_tokens_to_sample=max_tokens,
#         temperature=temperature,
#         stop_sequences=[HUMAN_PROMPT],
#     )
#     return response["completion"] if isinstance(response, dict) else getattr(response, "completion", "")

def call_claude(prompt: str, max_tokens: int = 900, temperature: float = 0.7) -> str:
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
    return {"session_id": response.data[0]["id"]}


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    session = get_session(request.session_id)
    user_text = request.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    insert_response = execute_db(
        db_table("messages").insert(
            {"session_id": request.session_id, "role": "user", "content": user_text}
        )
    )
    if not getattr(insert_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save user message")

    history = get_message_history(request.session_id)
    search_summary = None
    search_triggered = should_run_search(user_text)
    if search_triggered:
        query = f"{session['university']} career opportunities {user_text}"
        results = run_web_search(query)
        if results:
            search_summary = format_search_summary(query, results)

    prompt = compose_coach_prompt(session, history, user_text, search_summary)
    raw_output = call_claude(prompt)
    parsed = parse_json_response(raw_output)
    if parsed is None or "assistant_response" not in parsed:
        parsed = {
            "assistant_response": raw_output.strip(),
            "suggested_replies": [
                "Tell me more about relevant campus opportunities.",
                "How can I approach employers in my field?",
                "What should I do next to build my career readiness?",
            ],
        }
    else:
        suggested = parsed.get("suggested_replies")
        if not isinstance(suggested, list) or not suggested:
            parsed["suggested_replies"] = [
                "Tell me more about relevant campus opportunities.",
                "How can I approach employers in my field?",
                "What should I do next to build my career readiness?",
            ]

    assistant_text = str(parsed["assistant_response"]).strip()
    save_response = execute_db(
        db_table("messages").insert(
            {"session_id": request.session_id, "role": "assistant", "content": assistant_text}
        )
    )
    if not getattr(save_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save assistant response")

    return {
        "assistant_response": assistant_text,
        "suggested_replies": parsed["suggested_replies"],
        "search_used": bool(search_summary),
    }


@app.post("/plan")
async def generate_plan(request: PlanRequest) -> Dict[str, Any]:
    session = get_session(request.session_id)
    history = get_message_history(request.session_id)
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
            {"session_id": request.session_id, "plan_items": plan_json}
        )
    )
    if not getattr(save_response, "data", None):
        raise HTTPException(status_code=500, detail="Failed to save generated plan")

    return {"plan": plan_json}


@app.get("/session/{session_id}/history")
async def session_history(session_id: int) -> Dict[str, Any]:
    session = get_session(session_id)
    messages = get_message_history(session_id)
    plan = get_latest_plan(session_id)
    return {"session": session, "messages": messages, "plan": plan}


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")
