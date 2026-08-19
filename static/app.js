const deviceIdStorageKey = "moonreach_device_id";
const sessionStorageKey = "moonreach_session_id";
const northstarCacheKey = "moonreach_northstar_cache";

const generateUuid = () => {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  // Fallback for non-secure contexts where crypto.randomUUID is unavailable.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

let deviceId = localStorage.getItem(deviceIdStorageKey);
if (!deviceId) {
  deviceId = generateUuid();
  localStorage.setItem(deviceIdStorageKey, deviceId);
}

const onboardingSection = document.getElementById("onboarding");
const emptyChatState = document.getElementById("empty-chat-state");
const workspaceSection = document.getElementById("workspace-container");
const messageArea = document.getElementById("message-area");
const chipsContainer = document.getElementById("chips");
const chatGoalElement = document.getElementById("chat-goal");
const planList = document.getElementById("plan-list");
const radarListElement = document.getElementById("radar-list");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-message");
const planButton = document.getElementById("generate-plan");
const newSessionButton = document.getElementById("new-session-button");
const emptyStateNewChatButton = document.getElementById("empty-state-new-chat");
const northstarOutputElement = document.getElementById("northstar-output");
const northstarUpdatedElement = document.getElementById("northstar-updated");
const northstarWhatsNewElement = document.getElementById("northstar-whats-new");
const refreshNorthStarButton = document.getElementById("refresh-northstar");
const sessionListElement = document.getElementById("session-list");
const chatsCard = document.getElementById("chats-card");
const profileCardElement = document.getElementById("profile-card");
const editProfileButton = document.getElementById("edit-profile-button");

const newChatModal = document.getElementById("new-chat-modal");
const newChatForm = document.getElementById("new-chat-form");
const newChatGoalsInput = document.getElementById("new-chat-goals");
const newChatCancelButton = document.getElementById("new-chat-cancel");

const editProfileModal = document.getElementById("edit-profile-modal");
const editProfileForm = document.getElementById("edit-profile-form");
const editProfileUniversityInput = document.getElementById("edit-profile-university");
const editProfileMajorInput = document.getElementById("edit-profile-major");
const editProfileYearInput = document.getElementById("edit-profile-year");
const editProfileCancelButton = document.getElementById("edit-profile-cancel");

const appointmentsMenu = document.getElementById("appointments-menu");
const resumeFeedbackOption = document.getElementById("resume-feedback-option");
const resumeFeedbackFlow = document.getElementById("resume-feedback-flow");
const resumeFlowBackButton = document.getElementById("resume-flow-back");
const resumeUploadStep = document.getElementById("resume-upload-step");
const resumeFileInput = document.getElementById("resume-file-input");
const resumeUploadStatus = document.getElementById("resume-upload-status");
const resumeTextInput = document.getElementById("resume-text-input");
const resumeUploadContinueButton = document.getElementById("resume-upload-continue");
const resumeIntentStep = document.getElementById("resume-intent-step");
const resumeIntentChips = document.getElementById("resume-intent-chips");
const resumeRoleContextStep = document.getElementById("resume-role-context-step");
const resumeRoleTitleInput = document.getElementById("resume-role-title");
const resumeRoleCompanyInput = document.getElementById("resume-role-company");
const resumeRoleIndustryInput = document.getElementById("resume-role-industry");
const resumeRolePostingInput = document.getElementById("resume-role-posting");
const resumeRoleContextSubmitButton = document.getElementById("resume-role-context-submit");
const resumeThreadStep = document.getElementById("resume-thread-step");
const resumeThreadElement = document.getElementById("resume-thread");
const resumeFollowupInput = document.getElementById("resume-followup-input");
const resumeFollowupSendButton = document.getElementById("resume-followup-send");

// Appointments: resume feedback flow state. Chat-specific, reset whenever
// the active chat changes (see clearChatState) or the flow is (re)opened.
let resumeDocumentContent = "";
let resumeIntent = null;
let resumeRoleContext = null;
let resumeThreadSessionId = null;

const RESUME_INTENT_LABELS = {
  general_feedback: "General feedback and evaluation",
  tailor_to_role: "Tailor this to a specific role",
  something_else: "Something else",
};

let profile = null;
let currentSessionId = localStorage.getItem(sessionStorageKey);
let sessions = [];
let northstarRequestSeq = 0;
let chatRequestSeq = 0;
let cachedNorthStarPayload = null;

// In-memory, per-tab cache of each chat's messages/radar/plan, keyed by
// session_id. Deliberately module-level (not localStorage) - it exists only
// for this page load, and is the single source of truth for "have we
// already fetched this chat's data this session." See loadHistory() for the
// cache-hit/cache-miss branch and sendMessage()/generatePlan() for how it's
// kept in sync with Supabase on every write.
const chatCache = {};

const ensureCacheEntry = (sessionId) => {
  if (!chatCache[sessionId]) {
    // documentReviews: null means "not fetched yet for this chat" (distinct
    // from [] = fetched, zero reviews) - see loadDocumentReviews().
    chatCache[sessionId] = { goals: "", messages: [], radar: [], plan: [], documentReviews: null };
  }
  return chatCache[sessionId];
};

const appendCachedMessage = (sessionId, message) => {
  ensureCacheEntry(sessionId).messages.push(message);
};

const cacheDocumentReview = (sessionId, review) => {
  const entry = ensureCacheEntry(sessionId);
  if (!Array.isArray(entry.documentReviews)) {
    entry.documentReviews = [];
  }
  entry.documentReviews.push(review);
};

try {
  const stored = localStorage.getItem(northstarCacheKey);
  if (stored) {
    cachedNorthStarPayload = JSON.parse(stored);
  }
} catch (err) {
  console.error("Failed to load cached North Star payload", err);
}

const NORTHSTAR_PLACEHOLDER = `<div class="radar-empty">Analyzing your profile and career radar to find your current direction...</div>`;

const deviceHeaders = (extraHeaders = {}) => ({
  "X-Device-Id": deviceId,
  ...extraHeaders,
});

const showElement = (element) => element && element.classList.remove("hidden");
const hideElement = (element) => element && element.classList.add("hidden");

const switchPage = (targetPageId) => {
  const navTabs = document.querySelectorAll(".nav-tab");
  const appPages = document.querySelectorAll(".app-page");

  navTabs.forEach((tab) => {
    const isActive = tab.dataset.page === targetPageId;
    tab.classList.toggle("active", isActive);
  });

  appPages.forEach((page) => {
    const isTarget = page.id === targetPageId;
    if (isTarget) {
      showElement(page);
    } else {
      hideElement(page);
    }
  });
};

document.querySelectorAll(".nav-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    switchPage(tab.dataset.page);
  });
});

const showOnboarding = () => {
  hideElement(chatsCard);
  hideElement(editProfileButton);
  hideElement(emptyChatState);
  hideElement(workspaceSection);
  showElement(onboardingSection);
};

const showEmptyChatState = () => {
  hideElement(onboardingSection);
  hideElement(workspaceSection);
  showElement(emptyChatState);
};

const showWorkspace = () => {
  hideElement(onboardingSection);
  hideElement(emptyChatState);
  showElement(workspaceSection);
};

const timeAgo = (isoString) => {
  if (!isoString) return "";
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

const renderProfileCard = () => {
  if (!profile) {
    profileCardElement.innerHTML = "";
    return;
  }
  profileCardElement.innerHTML = `
    <div class="profile-row"><span class="profile-label">University</span><span class="profile-value">${profile.university || "—"}</span></div>
    <div class="profile-row"><span class="profile-label">Major</span><span class="profile-value">${profile.major || "—"}</span></div>
    <div class="profile-row"><span class="profile-label">Year</span><span class="profile-value">${profile.year || "—"}</span></div>
  `;
};

const extractAssistantText = (content) => {
  // Defense in depth: the backend now guards against ever saving raw
  // JSON-shaped text as a message (see salvage_assistant_text/parse_json_response
  // in app.py), but this also covers any rows already in the DB from before
  // that fix. Only ever show the assistant_response field, never the whole object.
  if (typeof content !== "string") {
    return content;
  }
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") || trimmed.indexOf('"assistant_response"') === -1) {
    return content;
  }
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed.assistant_response === "string") {
      return parsed.assistant_response;
    }
  } catch (err) {
    // Not actually valid JSON - show the original text as-is.
  }
  return content;
};

const addMessageBubble = (role, content, container = messageArea) => {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.innerHTML = `<div class="meta">${role === "user" ? "You" : "Coach"}</div><div>${content}</div>`;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
};

const clearChatState = () => {
  messageArea.innerHTML = "";
  clearChips();
  planList.innerHTML = "";
  radarListElement.innerHTML = "";
  showAppointmentsMenu();
};

const setActiveSession = (sessionId) => {
  const buttons = sessionListElement.querySelectorAll(".session-item");
  buttons.forEach((button) => {
    const isActive = Number(button.dataset.sessionId) === Number(sessionId);
    button.classList.toggle("active", isActive);
  });
};

const renderSessionList = () => {
  sessionListElement.innerHTML = "";
  if (!sessions.length) {
    const emptyState = document.createElement("p");
    emptyState.className = "session-meta";
    emptyState.textContent = "No chats yet.";
    sessionListElement.appendChild(emptyState);
    return;
  }

  sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.dataset.sessionId = session.id;
    const title = (session.goals || `Chat ${session.id}`).slice(0, 60);
    button.innerHTML = `<div class="session-title">${title}</div>`;
    button.addEventListener("click", () => {
      setSession(session.id);
    });
    sessionListElement.appendChild(button);
  });
  setActiveSession(currentSessionId);
};

const setSession = (sessionId, { skipHistory = false } = {}) => {
  currentSessionId = sessionId;
  localStorage.setItem(sessionStorageKey, String(sessionId));
  setActiveSession(sessionId);
  showWorkspace();
  if (!skipHistory) {
    loadHistory();
  }
};

const clearChips = () => {
  chipsContainer.innerHTML = "";
};

// Shared chip component: existing chat suggestions, North Star action chips,
// and the resume-intent chips all build a `.chip` button around a click
// handler. Only the handler differs by caller.
const buildChip = (text, onClick) => {
  if (!text) return null;
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "chip";
  chip.textContent = text;
  chip.addEventListener("click", onClick);
  return chip;
};

const showSuggestedChips = (chips) => {
  clearChips();
  if (!Array.isArray(chips) || !chips.length) {
    return;
  }
  chips.forEach((text) => {
    const chip = buildChip(text, () => {
      messageInput.value = text;
      sendMessage();
    });
    if (chip) {
      chipsContainer.appendChild(chip);
    }
  });
};

const normalizePlan = (plan) => {
  if (Array.isArray(plan)) {
    return plan.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
  }
  if (typeof plan === "string") {
    try {
      const parsed = JSON.parse(plan);
      if (Array.isArray(parsed)) {
        return parsed.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
      }
    } catch (err) {
      return plan.split(/\n+/).map((item) => item.trim()).filter(Boolean);
    }
  }
  return [];
};

const renderPlan = (plan) => {
  const normalizedPlan = normalizePlan(plan);
  if (!normalizedPlan.length) {
    planList.innerHTML = "<li>No action plan items generated yet. Click 'Generate plan' above.</li>";
    return;
  }

  planList.innerHTML = "";
  normalizedPlan.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    planList.appendChild(li);
  });
};

const renderRadar = (opportunities) => {
  radarListElement.innerHTML = "";
  const items = Array.isArray(opportunities) ? opportunities : [];
  if (!items.length) {
    const emptyState = document.createElement("div");
    emptyState.className = "radar-empty";
    emptyState.textContent = "Your Career Radar is still empty. Start a conversation to add opportunities.";
    radarListElement.appendChild(emptyState);
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "radar-card";
    card.innerHTML = `
      <div class="radar-card-header">
        <div>
          <h3>${item.title || "Untitled opportunity"}</h3>
          <p class="pill">${item.category || "Other"}</p>
        </div>
        <span class="priority-pill">P${item.priority_score || 5}</span>
      </div>
      <p class="radar-description">${item.description || ""}</p>
      <p class="radar-reason">${item.reason_relevant || ""}</p>
      <div class="radar-meta">
        <span>Status: ${item.status || "suggested"}</span>
        ${item.source_url ? `<a href="${item.source_url}" target="_blank" rel="noreferrer">Open source</a>` : ""}
      </div>
    `;
    radarListElement.appendChild(card);
  });
};

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));

const buildActionChip = (text) =>
  buildChip(text, () => {
    messageInput.value = text;
    switchPage("chat-page");
    sendMessage();
  });

const buildNorthStarItem = (item) => {
  const el = document.createElement("div");
  el.className = "northstar-block-item";
  const impact = typeof item.impact === "number" ? item.impact : null;
  const severity = typeof item.severity === "number" ? item.severity : null;
  const scoreText = impact !== null ? `Impact ${impact}/10` : severity !== null ? `Severity ${severity}/10` : "";
  el.innerHTML = `
    <div class="northstar-block-head">
      <strong>${escapeHtml(item.title)}</strong>
      ${scoreText ? `<span class="priority-pill">${escapeHtml(scoreText)}</span>` : ""}
    </div>
    ${item.why ? `<p>${escapeHtml(item.why)}</p>` : ""}
    ${item.recommended_action ? `<p class="northstar-action">${escapeHtml(item.recommended_action)}</p>` : ""}
  `;
  const chip = buildActionChip(item.action_chip);
  if (chip) {
    el.appendChild(chip);
  }
  return el;
};

const buildNorthStarSection = (label, items) => {
  const block = document.createElement("div");
  block.className = "northstar-section";
  const heading = document.createElement("div");
  heading.className = "panel-header";
  heading.innerHTML = `<div><p class="section-label">${escapeHtml(label)}</p></div>`;
  block.appendChild(heading);
  items.forEach((item) => {
    block.appendChild(buildNorthStarItem(item));
  });
  return block;
};

const renderNorthStarMeta = (payload) => {
  if (!payload || !payload.generated_at) {
    northstarUpdatedElement.textContent = "";
  } else {
    northstarUpdatedElement.textContent = `Last updated ${timeAgo(payload.generated_at)}`;
  }

  const whatsNew = Array.isArray(payload && payload.whats_new) ? payload.whats_new : [];
  if (!whatsNew.length) {
    hideElement(northstarWhatsNewElement);
    northstarWhatsNewElement.innerHTML = "";
    return;
  }
  northstarWhatsNewElement.innerHTML = `
    <p>What's new</p>
    <ul>${whatsNew.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
  `;
  showElement(northstarWhatsNewElement);
};

const renderNorthStar = (payload) => {
  renderNorthStarMeta(payload);
  const noEvidence = !payload || payload.has_evidence === false;
  if (noEvidence) {
    northstarOutputElement.innerHTML = `<div class="radar-empty">North Star will build itself from everything in your workspace. Add your first opportunity on the Career Radar or share a goal in a short conversation and check back here.</div>`;
    return;
  }

  const direction = (payload && payload.current_direction) || {};
  const directionText = direction.direction || "Exploring";
  const confidence = typeof direction.confidence === "number" ? `${direction.confidence}%` : null;
  const alternatives = Array.isArray(direction.alternative_directions) ? direction.alternative_directions : [];
  const evidence = Array.isArray(direction.evidence) ? direction.evidence : [];

  northstarOutputElement.innerHTML = `
    <div class="northstar-direction">
      <p class="section-label">Current direction</p>
      <div class="northstar-direction-row">
        <strong>${escapeHtml(directionText)}</strong>
        ${confidence ? `<span class="priority-pill">Confidence ${confidence}</span>` : ""}
      </div>
      ${direction.why ? `<p class="northstar-action">${escapeHtml(direction.why)}</p>` : ""}
      ${
        evidence.length
          ? `<ul class="northstar-evidence">${evidence.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>`
          : ""
      }
      ${
        alternatives.length
          ? `<p class="northstar-alts">Alternate paths: ${alternatives.map((a) => `<span class="pill">${escapeHtml(a)}</span>`).join(" ")}</p>`
          : ""
      }
    </div>
  `;

  const priorities = Array.isArray(payload.priorities) ? payload.priorities.slice(0, 3) : [];
  if (priorities.length) {
    northstarOutputElement.appendChild(buildNorthStarSection("Top priorities", priorities));
  }

  const risks = Array.isArray(payload.risks) ? payload.risks.slice(0, 3) : [];
  if (risks.length) {
    northstarOutputElement.appendChild(buildNorthStarSection("Risks to watch", risks));
  }

  const upcoming = Array.isArray(payload.upcoming_opportunities) ? payload.upcoming_opportunities.slice(0, 3) : [];
  if (upcoming.length) {
    northstarOutputElement.appendChild(buildNorthStarSection("Upcoming opportunities", upcoming));
  }
};

const loadNorthStar = async () => {
  if (!profile) {
    return;
  }

  // Render cached payload instantly if available, then always refresh -
  // the backend no longer caches, so this fetch is the source of truth.
  if (cachedNorthStarPayload) {
    renderNorthStar(cachedNorthStarPayload);
  } else {
    northstarOutputElement.innerHTML = NORTHSTAR_PLACEHOLDER;
  }

  const seq = ++northstarRequestSeq;
  refreshNorthStarButton.disabled = true;
  refreshNorthStarButton.textContent = "Updating…";

  const isLatest = () => northstarRequestSeq === seq;
  try {
    const response = await fetch("/north-star", {
      method: "POST",
      headers: deviceHeaders(),
    });
    if (!response.ok) {
      const errorBody = await response.text();
      console.error("[NorthStar] backend error", response.status, errorBody);
      if (isLatest() && !cachedNorthStarPayload) {
        northstarOutputElement.innerHTML = `<div class="radar-empty radar-error">North Star failed to load (${response.status}). Please try again.</div>`;
      }
      return;
    }
    const payload = await response.json();
    cachedNorthStarPayload = payload;
    try {
      localStorage.setItem(northstarCacheKey, JSON.stringify(payload));
    } catch (e) {}

    if (isLatest()) {
      renderNorthStar(payload);
    }
  } catch (error) {
    console.error("[NorthStar] exception", error);
    if (isLatest() && !cachedNorthStarPayload) {
      northstarOutputElement.innerHTML = `<div class="radar-empty radar-error">North Star failed to load. Please try again.</div>`;
    }
  } finally {
    if (isLatest()) {
      refreshNorthStarButton.disabled = false;
      refreshNorthStarButton.textContent = "🔄 Refresh Analysis";
    }
  }
};

const handleError = async (response) => {
  const text = await response.text();
  addMessageBubble("assistant", `Error: ${response.status} ${text}`);
};

const loadSessions = async () => {
  try {
    const response = await fetch("/sessions", { headers: deviceHeaders() });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    renderSessionList();
  } catch (error) {
    console.error(error);
  }
};

const sendMessage = async () => {
  const text = messageInput.value.trim();
  if (!text || !currentSessionId) {
    return;
  }
  // Pin the chat this message belongs to. If the user switches chats before
  // the response comes back, we must not render this reply (or the radar
  // refresh it triggers) into whatever chat happens to be on screen by then.
  const sendingSessionId = currentSessionId;
  addMessageBubble("user", text);
  appendCachedMessage(sendingSessionId, { role: "user", content: text });
  messageInput.value = "";
  clearChips();
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ session_id: Number(sendingSessionId), message: text }),
    });
    if (!response.ok) {
      if (sendingSessionId === currentSessionId) {
        return handleError(response);
      }
      return;
    }
    const data = await response.json();
    // Cache is updated for sendingSessionId regardless of whether it's still
    // the visible chat - it must never fall behind what's actually in
    // Supabase. Rendering into the DOM, on the other hand, only happens if
    // the user is still looking at this chat.
    appendCachedMessage(sendingSessionId, { role: "assistant", content: data.assistant_response });
    if (sendingSessionId === currentSessionId) {
      addMessageBubble("assistant", extractAssistantText(data.assistant_response));
    }

    const radar = await loadCareerRadar(sendingSessionId);
    if (radar) {
      ensureCacheEntry(sendingSessionId).radar = radar;
    }

    if (sendingSessionId === currentSessionId) {
      showSuggestedChips(data.suggested_replies || []);
    }
    loadNorthStar();
  } catch (error) {
    if (sendingSessionId === currentSessionId) {
      addMessageBubble("assistant", "Unable to reach the server. Please try again.");
    }
    console.error(error);
  }
};

// Returns the fetched opportunities regardless of whether this chat is still
// the one on screen (callers need that to keep the cache in sync even when
// the user has switched away), but only renders into the DOM if it is.
const loadCareerRadar = async (sessionId = currentSessionId) => {
  if (!sessionId) {
    return null;
  }
  try {
    const response = await fetch(`/career-radar/${sessionId}`, { headers: deviceHeaders() });
    if (!response.ok) {
      return null;
    }
    const payload = await response.json();
    const opportunities = payload.opportunities || [];
    if (sessionId === currentSessionId) {
      renderRadar(opportunities);
    }
    return opportunities;
  } catch (error) {
    console.error(error);
    return null;
  }
};

const renderChatFromCache = (cached) => {
  chatGoalElement.textContent = cached.goals || "—";
  cached.messages.forEach((message) => {
    addMessageBubble(message.role, extractAssistantText(message.content));
  });
  renderPlan(cached.plan);
  renderRadar(cached.radar);
  showWorkspace();
};

const loadHistory = async () => {
  const requestedSessionId = currentSessionId;
  const seq = ++chatRequestSeq;
  const isStale = () => seq !== chatRequestSeq || requestedSessionId !== currentSessionId;

  clearChatState();
  if (!requestedSessionId) {
    showEmptyChatState();
    return;
  }

  // Cache hit: this chat was already opened once this browser session, so
  // render straight from memory - no /session/.../history or
  // /career-radar/... request at all (North Star is intentionally excluded;
  // it's a cross-chat aggregate and stays always-live, see prior fix notes).
  const cached = chatCache[requestedSessionId];
  if (cached) {
    renderChatFromCache(cached);
    loadNorthStar();
    return;
  }

  try {
    const response = await fetch(`/session/${requestedSessionId}/history`, { headers: deviceHeaders() });
    if (isStale()) {
      return; // a newer chat switch has already superseded this in-flight load
    }
    if (!response.ok) {
      localStorage.removeItem(sessionStorageKey);
      currentSessionId = null;
      setActiveSession(null);
      return showEmptyChatState();
    }
    const payload = await response.json();
    if (isStale()) {
      return;
    }
    const goals = (payload.session && payload.session.goals) || "—";
    chatGoalElement.textContent = goals;
    payload.messages.forEach((message) => {
      addMessageBubble(message.role, extractAssistantText(message.content));
    });
    renderPlan(payload.plan);
    showWorkspace();
    const radar = await loadCareerRadar(requestedSessionId);
    if (isStale()) {
      return;
    }
    chatCache[requestedSessionId] = {
      goals,
      messages: payload.messages || [],
      radar: radar || [],
      plan: payload.plan || [],
    };
    loadNorthStar();
  } catch (error) {
    console.error(error);
    if (!isStale()) {
      showEmptyChatState();
    }
  }
};

const createProfile = async (event) => {
  event.preventDefault();
  const university = document.getElementById("onboarding-university").value.trim();
  const major = document.getElementById("onboarding-major").value.trim();
  const year = document.getElementById("onboarding-year").value.trim();

  if (!university || !major || !year) {
    return;
  }

  try {
    const response = await fetch("/profile", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ university, major, year }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    profile = data.profile;
    renderProfileCard();
    showElement(chatsCard);
    showElement(editProfileButton);
    showEmptyChatState();
  } catch (error) {
    console.error(error);
  }
};

const openNewChatModal = () => {
  newChatGoalsInput.value = "";
  showElement(newChatModal);
  newChatGoalsInput.focus();
};

const closeNewChatModal = () => hideElement(newChatModal);

const createChat = async (event) => {
  event.preventDefault();
  const goals = newChatGoalsInput.value.trim();
  if (!goals) {
    return;
  }
  try {
    const response = await fetch("/session", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ goals }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    const createdChat = { id: data.session_id, goals, created_at: new Date().toISOString() };
    sessions = [createdChat, ...sessions.filter((session) => Number(session.id) !== Number(data.session_id))];
    renderSessionList();
    closeNewChatModal();
    setSession(data.session_id, { skipHistory: true });
    await loadHistory();
    const welcomeText = "New chat started. Ask me anything about this pursuit.";
    addMessageBubble("assistant", welcomeText);
    appendCachedMessage(data.session_id, { role: "assistant", content: welcomeText });
  } catch (error) {
    console.error(error);
  }
};

const openEditProfileModal = () => {
  if (!profile) return;
  editProfileUniversityInput.value = profile.university || "";
  editProfileMajorInput.value = profile.major || "";
  editProfileYearInput.value = profile.year || "";
  showElement(editProfileModal);
};

const closeEditProfileModal = () => hideElement(editProfileModal);

const saveProfile = async (event) => {
  event.preventDefault();
  const university = editProfileUniversityInput.value.trim();
  const major = editProfileMajorInput.value.trim();
  const year = editProfileYearInput.value.trim();
  if (!university || !major || !year) {
    return;
  }
  try {
    const response = await fetch("/profile", {
      method: "PATCH",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ university, major, year }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    profile = data.profile;
    renderProfileCard();
    closeEditProfileModal();
    cachedNorthStarPayload = null;
    loadNorthStar();
  } catch (error) {
    console.error(error);
  }
};

const generatePlan = async () => {
  if (!currentSessionId) {
    return;
  }
  const planningSessionId = currentSessionId;
  try {
    const response = await fetch("/plan", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ session_id: Number(planningSessionId) }),
    });
    if (!response.ok) {
      if (planningSessionId === currentSessionId) {
        return handleError(response);
      }
      return;
    }
    const data = await response.json();
    ensureCacheEntry(planningSessionId).plan = data.plan || [];
    if (planningSessionId === currentSessionId) {
      renderPlan(data.plan);
    }
  } catch (error) {
    if (planningSessionId === currentSessionId) {
      addMessageBubble("assistant", "Unable to generate a plan. Please try again.");
    }
    console.error(error);
  }
};

// ---- Appointments: resume feedback ----
// A deliberately separate conversational surface from the Coach chat above -
// it never touches messageInput/sendMessage/messages, only /document-reviews.

const showAppointmentsMenu = () => {
  hideElement(resumeFeedbackFlow);
  showElement(appointmentsMenu);
};

const openResumeFeedbackFlow = () => {
  resumeDocumentContent = "";
  resumeIntent = null;
  resumeRoleContext = null;
  resumeThreadSessionId = currentSessionId;
  resumeFileInput.value = "";
  resumeTextInput.value = "";
  resumeRoleTitleInput.value = "";
  resumeRoleCompanyInput.value = "";
  resumeRoleIndustryInput.value = "";
  resumeRolePostingInput.value = "";
  resumeFollowupInput.value = "";
  resumeThreadElement.innerHTML = "";
  setResumeUploadStatus("");

  hideElement(appointmentsMenu);
  showElement(resumeFeedbackFlow);
  hideElement(resumeIntentStep);
  hideElement(resumeRoleContextStep);
  hideElement(resumeThreadStep);
  showElement(resumeUploadStep);
};

const setResumeUploadStatus = (text, isError = false) => {
  if (!text) {
    resumeUploadStatus.textContent = "";
    hideElement(resumeUploadStatus);
    return;
  }
  resumeUploadStatus.textContent = text;
  resumeUploadStatus.classList.toggle("resume-upload-error", isError);
  showElement(resumeUploadStatus);
};

// PDF/DOCX/TXT all go through the same server-side extraction endpoint
// (Docling for PDF/DOCX, plain decode for TXT server-side - see
// extract_resume_text in app.py) so there is exactly one upload code path
// here regardless of file type. The extracted text lands in the same
// textarea used for pasting, so the user can review/edit it either way
// before continuing.
const handleResumeFileUpload = async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) {
    return;
  }
  setResumeUploadStatus(`Extracting text from ${file.name}...`);
  resumeUploadContinueButton.disabled = true;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/resume-upload", {
      method: "POST",
      headers: deviceHeaders(),
      body: formData,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setResumeUploadStatus(
        body.detail || "Could not read that file. Please try a different file or paste your resume text.",
        true
      );
      return;
    }
    const data = await response.json();
    resumeTextInput.value = data.document_content || "";
    setResumeUploadStatus(`Loaded ${file.name}. Review the text below before continuing.`);
  } catch (error) {
    console.error(error);
    setResumeUploadStatus("Unable to reach the server. Please try again or paste your resume text.", true);
  } finally {
    resumeUploadContinueButton.disabled = false;
  }
};

const renderResumeIntentChips = () => {
  resumeIntentChips.innerHTML = "";
  Object.entries(RESUME_INTENT_LABELS).forEach(([intent, label]) => {
    const chip = buildChip(label, () => selectResumeIntent(intent));
    if (chip) {
      resumeIntentChips.appendChild(chip);
    }
  });
};

const submitResumeUpload = () => {
  const text = resumeTextInput.value.trim();
  if (!text) {
    return;
  }
  resumeDocumentContent = text;
  hideElement(resumeUploadStep);
  renderResumeIntentChips();
  showElement(resumeIntentStep);
};

const renderResumeReviewList = (label, items) => {
  if (!Array.isArray(items) || !items.length) {
    return "";
  }
  return `<p class="section-label">${escapeHtml(label)}</p><ul class="northstar-evidence">${items
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("")}</ul>`;
};

const renderResumeReviewTurn = (review) => {
  if (!review) {
    return;
  }
  const feedback = review.ai_feedback || {};
  if (review.intent === "resume_follow_up") {
    addMessageBubble("user", escapeHtml(feedback.user_message || ""), resumeThreadElement);
    addMessageBubble("assistant", escapeHtml(feedback.assistant_response || ""), resumeThreadElement);
    return;
  }
  const card = document.createElement("div");
  card.className = "message assistant resume-review-card";
  card.innerHTML = `
    ${renderResumeReviewList("Strengths", feedback.strengths)}
    ${renderResumeReviewList("Areas to improve", feedback.areas_to_improve)}
    ${renderResumeReviewList("Specific line-level suggestions", feedback.line_suggestions)}
    ${
      feedback.role_alignment
        ? `<p class="section-label">How this aligns with the role</p><p>${escapeHtml(feedback.role_alignment)}</p>`
        : ""
    }
    <p class="section-label">Overall summary</p>
    <p>${escapeHtml(feedback.overall_summary || "")}</p>
  `;
  resumeThreadElement.appendChild(card);
  resumeThreadElement.scrollTop = resumeThreadElement.scrollHeight;
};

const submitInitialResumeReview = async () => {
  if (!currentSessionId) {
    return;
  }
  const targetSessionId = currentSessionId;
  resumeThreadSessionId = targetSessionId;
  showElement(resumeThreadStep);
  resumeThreadElement.innerHTML = `<div class="radar-empty">Reviewing your resume...</div>`;
  try {
    const response = await fetch("/document-reviews", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        session_id: Number(targetSessionId),
        document_type: "resume",
        document_content: resumeDocumentContent,
        intent: resumeIntent,
        role_context: resumeRoleContext,
      }),
    });
    if (!response.ok) {
      resumeThreadElement.innerHTML = `<div class="radar-empty radar-error">Something went wrong getting feedback. Please try again.</div>`;
      return;
    }
    const data = await response.json();
    resumeThreadElement.innerHTML = "";
    renderResumeReviewTurn(data.review);
    cacheDocumentReview(targetSessionId, data.review);
  } catch (error) {
    console.error(error);
    resumeThreadElement.innerHTML = `<div class="radar-empty radar-error">Unable to reach the server. Please try again.</div>`;
  }
};

const selectResumeIntent = (intent) => {
  resumeIntent = intent;
  hideElement(resumeIntentStep);
  if (intent === "tailor_to_role") {
    showElement(resumeRoleContextStep);
    return;
  }
  submitInitialResumeReview();
};

const submitRoleContext = () => {
  const title = resumeRoleTitleInput.value.trim();
  if (!title) {
    return;
  }
  resumeRoleContext = {
    title,
    company: resumeRoleCompanyInput.value.trim(),
    industry: resumeRoleIndustryInput.value.trim(),
    job_posting: resumeRolePostingInput.value.trim(),
  };
  hideElement(resumeRoleContextStep);
  submitInitialResumeReview();
};

const sendResumeFollowUp = async () => {
  const message = resumeFollowupInput.value.trim();
  if (!message || !resumeThreadSessionId || !resumeDocumentContent) {
    return;
  }
  const sessionId = resumeThreadSessionId;
  addMessageBubble("user", escapeHtml(message), resumeThreadElement);
  resumeFollowupInput.value = "";
  try {
    const response = await fetch("/document-reviews", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        session_id: Number(sessionId),
        document_type: "resume",
        document_content: resumeDocumentContent,
        intent: "resume_follow_up",
        role_context: resumeRoleContext,
        message,
      }),
    });
    if (!response.ok) {
      if (sessionId === resumeThreadSessionId) {
        addMessageBubble("assistant", "Something went wrong. Please try again.", resumeThreadElement);
      }
      return;
    }
    const data = await response.json();
    cacheDocumentReview(sessionId, data.review);
    if (sessionId === resumeThreadSessionId) {
      const feedback = (data.review && data.review.ai_feedback) || {};
      addMessageBubble("assistant", escapeHtml(feedback.assistant_response || ""), resumeThreadElement);
    }
  } catch (error) {
    console.error(error);
    if (sessionId === resumeThreadSessionId) {
      addMessageBubble("assistant", "Unable to reach the server. Please try again.", resumeThreadElement);
    }
  }
};

const loadDocumentReviews = async (sessionId) => {
  const entry = ensureCacheEntry(sessionId);
  if (Array.isArray(entry.documentReviews)) {
    return entry.documentReviews; // already fetched this browser session
  }
  try {
    const response = await fetch(`/document-reviews/${sessionId}`, { headers: deviceHeaders() });
    if (!response.ok) {
      return [];
    }
    const payload = await response.json();
    entry.documentReviews = Array.isArray(payload.reviews) ? payload.reviews : [];
    return entry.documentReviews;
  } catch (error) {
    console.error(error);
    return [];
  }
};

const openResumeThreadFromReviews = (sessionId, thread) => {
  const initialTurn = thread.find((row) => row.intent !== "resume_follow_up") || thread[0];
  resumeDocumentContent = initialTurn.document_content;
  resumeIntent = initialTurn.intent === "resume_follow_up" ? null : initialTurn.intent;
  resumeRoleContext = initialTurn.role_context || null;
  resumeThreadSessionId = sessionId;

  hideElement(appointmentsMenu);
  showElement(resumeFeedbackFlow);
  hideElement(resumeUploadStep);
  hideElement(resumeIntentStep);
  hideElement(resumeRoleContextStep);
  showElement(resumeThreadStep);
  resumeThreadElement.innerHTML = "";
  thread.forEach((review) => renderResumeReviewTurn(review));
};

const handleResumeFeedbackOptionClick = async () => {
  if (!currentSessionId) {
    return;
  }
  const sessionId = currentSessionId;
  const reviews = await loadDocumentReviews(sessionId);
  const resumeReviews = reviews.filter((review) => review.document_type === "resume");
  if (!resumeReviews.length) {
    openResumeFeedbackFlow();
    return;
  }
  // Most recent thread only, grouped by document_content (see
  // get_document_review_thread in app.py for why that's the grouping key).
  const latest = resumeReviews[resumeReviews.length - 1];
  const thread = resumeReviews.filter((review) => review.document_content === latest.document_content);
  openResumeThreadFromReviews(sessionId, thread);
};

const bootstrap = async () => {
  try {
    const response = await fetch("/profile", { headers: deviceHeaders() });
    if (!response.ok) {
      return showOnboarding();
    }
    const data = await response.json();
    profile = data.profile;
    renderProfileCard();
    showElement(chatsCard);
    showElement(editProfileButton);

    await loadSessions();
    const storedIdStillValid = currentSessionId && sessions.some((s) => Number(s.id) === Number(currentSessionId));
    if (storedIdStillValid) {
      setSession(currentSessionId);
    } else if (sessions.length) {
      setSession(sessions[0].id);
    } else {
      currentSessionId = null;
      showEmptyChatState();
    }
  } catch (error) {
    console.error(error);
    showOnboarding();
  }
};

document.getElementById("onboarding-form").addEventListener("submit", createProfile);
sendButton.addEventListener("click", sendMessage);
planButton.addEventListener("click", generatePlan);
newSessionButton.addEventListener("click", openNewChatModal);
emptyStateNewChatButton.addEventListener("click", openNewChatModal);
newChatForm.addEventListener("submit", createChat);
newChatCancelButton.addEventListener("click", closeNewChatModal);
editProfileButton.addEventListener("click", openEditProfileModal);
editProfileForm.addEventListener("submit", saveProfile);
editProfileCancelButton.addEventListener("click", closeEditProfileModal);
refreshNorthStarButton.addEventListener("click", () => {
  cachedNorthStarPayload = null;
  loadNorthStar();
});
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

resumeFeedbackOption.addEventListener("click", handleResumeFeedbackOptionClick);
resumeFlowBackButton.addEventListener("click", showAppointmentsMenu);
resumeFileInput.addEventListener("change", handleResumeFileUpload);
resumeUploadContinueButton.addEventListener("click", submitResumeUpload);
resumeRoleContextSubmitButton.addEventListener("click", submitRoleContext);
resumeFollowupSendButton.addEventListener("click", sendResumeFollowUp);
resumeFollowupInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendResumeFollowUp();
  }
});

bootstrap();
