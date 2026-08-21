// MoonReach controller. Owns all backend I/O and the 2D overlay panels.
// Never touches Three.js/rendering directly - all scene/camera control goes
// through window.MR.scene (focus/release/setStarMode/reshuffleStars) and
// window.MR.bus (object:click, starprompt:click), both defined in scene.js.

const deviceIdStorageKey = "moonreach_device_id";
const sessionStorageKey = "moonreach_session_id";
const northstarCacheKey = "moonreach_northstar_cache";

const generateUuid = () => {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
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

const deviceHeaders = (extraHeaders = {}) => ({
  "X-Device-Id": deviceId,
  ...extraHeaders,
});

const showElement = (element) => element && element.classList.remove("hidden");
const hideElement = (element) => element && element.classList.add("hidden");
const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));

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

/* ============================================================
   Local-only extensions: fields the task asks for that have no
   backend column and must not become one (the North Star goal
   statement, opportunity notes, action-plan step status).
   Persisted client-side, namespaced by device id so they survive
   reloads without touching Supabase.
   ============================================================ */
const localKey = (suffix) => `moonreach_${suffix}_${deviceId}`;

const readLocalJson = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) {
    return fallback;
  }
};
const writeLocalJson = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (err) {
    /* storage full/unavailable - extension fields just won't persist */
  }
};

const getNorthStarGoal = () => readLocalJson(localKey("northstar_goal"), "");
const setNorthStarGoal = (text) => writeLocalJson(localKey("northstar_goal"), text);

const getOpportunityNotes = () => readLocalJson(localKey("opportunity_notes"), {});
const setOpportunityNote = (opportunityId, note) => {
  const notes = getOpportunityNotes();
  notes[opportunityId] = note;
  writeLocalJson(localKey("opportunity_notes"), notes);
};

const getPlanStatuses = (sessionId) => readLocalJson(localKey(`plan_status_${sessionId}`), {});
const setPlanStatus = (sessionId, index, status) => {
  const statuses = getPlanStatuses(sessionId);
  statuses[index] = status;
  writeLocalJson(localKey(`plan_status_${sessionId}`), statuses);
};

/* ============================================================
   Recommended-prompt library. scene.js owns the highlighted-star
   subset visuals; app.js only supplies which prompts exist and
   what to do when one is clicked.
   ============================================================ */
const PROMPT_LIBRARY = [
  { id: "internships", text: "What internships should I be applying to right now?" },
  { id: "resume-gaps", text: "What's missing from my resume for the roles I want?" },
  { id: "networking", text: "How do I start networking in my field without feeling awkward?" },
  { id: "grad-school", text: "Should I consider grad school, or go straight into industry?" },
  { id: "first-job", text: "How do I stand out for my first job in a competitive field?" },
  { id: "career-fair", text: "How should I prepare for an upcoming career fair?" },
  { id: "interview-prep", text: "Help me prepare for a behavioral interview." },
  { id: "switch-majors", text: "How does my major affect my career options if I want to pivot?" },
  { id: "linkedin", text: "What should my LinkedIn profile say to attract recruiters?" },
  { id: "research-vs-industry", text: "Is undergrad research worth it if I want an industry job?" },
];
const PROMPT_BY_ID = Object.fromEntries(PROMPT_LIBRARY.map((p) => [p.id, p]));

const pickRandomPromptIds = (count) => {
  const pool = [...PROMPT_LIBRARY];
  const picked = [];
  while (picked.length < count && pool.length) {
    const idx = Math.floor(Math.random() * pool.length);
    picked.push(pool.splice(idx, 1)[0].id);
  }
  return picked;
};

const RESHUFFLE_EVENTS = ["chat:completed", "radar:changed", "actionplan:changed"];
const triggerReshuffle = (eventName) => {
  if (!window.MR || !MR.bus || !MR.scene) return;
  MR.bus.dispatchEvent(new CustomEvent(eventName, { detail: { promptIds: pickRandomPromptIds(5) } }));
};

/* ============================================================
   DOM references
   ============================================================ */
const onboardingOverlay = document.getElementById("onboarding-overlay");
const onboardingForm = document.getElementById("onboarding-form");

const panelHost = document.getElementById("panel-host");
const panelBackdrop = document.getElementById("panel-backdrop");
const panels = {
  profile: document.getElementById("panel-profile"),
  chats: document.getElementById("panel-chats"),
  chat: document.getElementById("panel-chat"),
  radar: document.getElementById("panel-radar"),
  star: document.getElementById("panel-star"),
};

const profileForm = document.getElementById("profile-form");
const profileUniversityInput = document.getElementById("profile-university");
const profileMajorInput = document.getElementById("profile-major");
const profileYearInput = document.getElementById("profile-year");
const profileSaveStatus = document.getElementById("profile-save-status");

const newChatButton = document.getElementById("new-chat-button");
const newChatInline = document.getElementById("new-chat-inline");
const newChatGoalsInput = document.getElementById("new-chat-goals");
const newChatSubmitButton = document.getElementById("new-chat-submit");
const newChatCancelButton = document.getElementById("new-chat-cancel");
const sessionListElement = document.getElementById("session-list");

const chatGoalElement = document.getElementById("chat-goal");
const messageArea = document.getElementById("message-area");
const chipsContainer = document.getElementById("chips");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-message");

const radarListElement = document.getElementById("radar-list");

const northstarGoalInput = document.getElementById("northstar-goal-input");
const northstarGoalSaveButton = document.getElementById("northstar-goal-save");
const northstarGoalStatus = document.getElementById("northstar-goal-status");
const northstarOutputElement = document.getElementById("northstar-output");
const northstarUpdatedElement = document.getElementById("northstar-updated");
const northstarWhatsNewElement = document.getElementById("northstar-whats-new");
const refreshNorthStarButton = document.getElementById("refresh-northstar");

const planSessionSelect = document.getElementById("actionplan-session-select");
const planButton = document.getElementById("generate-plan");
const planList = document.getElementById("plan-list");

/* ============================================================
   State
   ============================================================ */
let profile = null;
let activePanel = "none";
let currentSessionId = localStorage.getItem(sessionStorageKey);
let sessions = [];
let northstarRequestSeq = 0;
let chatRequestSeq = 0;
let cachedNorthStarPayload = null;

// Per-tab cache of each chat's messages/radar/plan, keyed by session_id.
const chatCache = {};
const ensureCacheEntry = (sessionId) => {
  if (!chatCache[sessionId]) {
    chatCache[sessionId] = { goals: "", messages: [], radar: [], plan: [], lastMessagePreview: "" };
  }
  return chatCache[sessionId];
};
const appendCachedMessage = (sessionId, message) => {
  const entry = ensureCacheEntry(sessionId);
  entry.messages.push(message);
  entry.lastMessagePreview = typeof message.content === "string" ? message.content : "";
};

try {
  const stored = localStorage.getItem(northstarCacheKey);
  if (stored) cachedNorthStarPayload = JSON.parse(stored);
} catch (err) {
  console.error("Failed to load cached North Star payload", err);
}

const NORTHSTAR_PLACEHOLDER = `<div class="radar-empty">Analyzing your profile and career radar to find your current direction...</div>`;

/* ============================================================
   Panel host / camera orchestration
   ============================================================ */
const isSceneReady = () => Boolean(window.MR && MR.scene);

function setActivePanel(name) {
  activePanel = name;
  Object.entries(panels).forEach(([key, el]) => {
    if (key === name) {
      el.classList.remove("hidden");
      requestAnimationFrame(() => el.classList.add("panel-visible"));
    } else {
      el.classList.remove("panel-visible");
      el.classList.add("hidden");
    }
  });
  if (name === "none") {
    panelHost.classList.remove("panel-open");
    window.setTimeout(() => {
      if (activePanel === "none") panelHost.classList.add("hidden");
    }, 220);
  } else {
    panelHost.classList.remove("hidden");
    requestAnimationFrame(() => panelHost.classList.add("panel-open"));
  }
}

function requireProfileOrOnboard() {
  if (profile) return true;
  showOnboarding();
  return false;
}

function openProfilePanel() {
  if (!profile) {
    showOnboarding();
    return;
  }
  if (isSceneReady()) MR.scene.focus("ridge");
  populateProfileForm();
  setActivePanel("profile");
}
function closeProfilePanel() {
  if (isSceneReady()) MR.scene.release();
  setActivePanel("none");
}

function openChatsPanel() {
  if (!requireProfileOrOnboard()) return;
  if (isSceneReady()) MR.scene.focus("belt");
  hideElement(newChatInline);
  setActivePanel("chats");
  loadSessions();
}
function closeChatsPanel() {
  if (isSceneReady()) MR.scene.release();
  setActivePanel("none");
}

function openChatPanel(sessionId, { fresh = false, goals = null } = {}) {
  // Assumes the belt frame is already focused (from openChatsPanel or the
  // starprompt shortcut, which pushes both frames itself) - this only pushes
  // the second, deeper "docked" frame.
  if (isSceneReady()) MR.scene.focus("belt-chat");
  setSession(sessionId, { skipHistory: fresh });
  if (fresh && goals) {
    // A brand new chat has no history to derive the goal heading from -
    // set it directly instead of leaving the previous chat's heading (or
    // the "—" placeholder) on screen until the next reload.
    chatGoalElement.textContent = goals;
    ensureCacheEntry(sessionId).goals = goals;
  }
  setActivePanel("chat");
}
function closeChatPanel() {
  if (isSceneReady()) MR.scene.release(); // -> belt-level view
  setActivePanel("chats");
  loadSessions();
}

function openRadarPanel() {
  if (!requireProfileOrOnboard()) return;
  if (isSceneReady()) MR.scene.focus("moon");
  setActivePanel("radar");
  loadRadarAcrossChats();
}
function closeRadarPanel() {
  if (isSceneReady()) MR.scene.release();
  setActivePanel("none");
}

function openStarPanel() {
  if (!requireProfileOrOnboard()) return;
  if (isSceneReady()) MR.scene.focus("star");
  northstarGoalInput.value = getNorthStarGoal();
  setActivePanel("star");
  loadNorthStar();
  populatePlanSessionSelect();
}
function closeStarPanel() {
  if (isSceneReady()) MR.scene.release();
  if (isSceneReady()) MR.scene.setStarMode("northstar");
  setActivePanel("none");
}

document.querySelectorAll(".panel-close").forEach((btn) => {
  btn.addEventListener("click", () => {
    const panelEl = btn.closest(".panel");
    if (!panelEl) return;
    if (panelEl === panels.profile) closeProfilePanel();
    else if (panelEl === panels.chats) closeChatsPanel();
    else if (panelEl === panels.chat) closeChatPanel();
    else if (panelEl === panels.radar) closeRadarPanel();
    else if (panelEl === panels.star) closeStarPanel();
  });
});

function closeActivePanel() {
  if (activePanel === "profile") closeProfilePanel();
  else if (activePanel === "chats") closeChatsPanel();
  else if (activePanel === "chat") closeChatPanel();
  else if (activePanel === "radar") closeRadarPanel();
  else if (activePanel === "star") closeStarPanel();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || activePanel === "none") return;
  closeActivePanel();
});
panelBackdrop.addEventListener("click", () => {
  if (activePanel !== "none") closeActivePanel();
});

function showOnboarding() {
  showElement(onboardingOverlay);
}
function hideOnboarding() {
  hideElement(onboardingOverlay);
}

/* ============================================================
   Scene event wiring: MR.bus is the only channel scene.js and
   app.js talk through - scene.js never reaches into panel DOM,
   app.js never reaches into Three.js internals.
   ============================================================ */
function wireSceneEvents() {
  if (!window.MR || !MR.bus) return;
  MR.bus.addEventListener("object:click", (event) => {
    const name = event.detail && event.detail.name;
    if (name === "ridge") openProfilePanel();
    else if (name === "belt") openChatsPanel();
    else if (name === "moon") openRadarPanel();
    else if (name === "star") openStarPanel();
  });

  MR.bus.addEventListener("starprompt:click", (event) => {
    if (!requireProfileOrOnboard()) return;
    const promptId = event.detail && event.detail.promptId;
    const prompt = PROMPT_BY_ID[promptId];
    startChatFromPrompt(prompt ? prompt.text : "Let's talk about my career options.");
  });
}

/* ============================================================
   Profile (ridge)
   ============================================================ */
function populateProfileForm() {
  profileUniversityInput.value = (profile && profile.university) || "";
  profileMajorInput.value = (profile && profile.major) || "";
  profileYearInput.value = (profile && profile.year) || "";
}

async function saveProfileForm(event) {
  event.preventDefault();
  const university = profileUniversityInput.value.trim();
  const major = profileMajorInput.value.trim();
  const year = profileYearInput.value.trim();
  if (!university || !major || !year) return;

  profileSaveStatus.textContent = "Saving...";
  try {
    const response = await fetch("/profile", {
      method: profile ? "PATCH" : "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ university, major, year }),
    });
    if (!response.ok) {
      profileSaveStatus.textContent = "Couldn't save. Try again.";
      return;
    }
    const data = await response.json();
    const hadProfile = Boolean(profile);
    profile = data.profile;
    cachedNorthStarPayload = null;
    profileSaveStatus.textContent = "Saved.";
    window.setTimeout(() => { profileSaveStatus.textContent = ""; }, 2000);
    if (!hadProfile) {
      hideOnboarding();
      await loadSessions();
    }
  } catch (error) {
    console.error(error);
    profileSaveStatus.textContent = "Unable to reach the server.";
  }
}

/* ============================================================
   Chats list (belt) + chat interface (belt-chat)
   ============================================================ */
const timeOf = (session) => session.created_at;

async function fetchPreview(session) {
  const entry = ensureCacheEntry(session.id);
  if (entry.lastMessagePreview || chatCache[session.id]?.previewFetched) {
    return entry.lastMessagePreview;
  }
  try {
    const response = await fetch(`/session/${session.id}/history`, { headers: deviceHeaders() });
    if (!response.ok) return "";
    const payload = await response.json();
    const messages = payload.messages || [];
    const last = messages[messages.length - 1];
    entry.previewFetched = true;
    if (last) entry.lastMessagePreview = extractAssistantText(last.content);
    return entry.lastMessagePreview || "";
  } catch (error) {
    return "";
  }
}

async function loadSessions() {
  try {
    const response = await fetch("/sessions", { headers: deviceHeaders() });
    if (!response.ok) return;
    const payload = await response.json();
    sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    renderSessionList();
    populatePlanSessionSelect();
    // Previews scale independently of the belt's fixed asteroid count -
    // fetched lazily and cached, never re-fetched once known.
    sessions.forEach(async (session) => {
      await fetchPreview(session);
      if (activePanel === "chats") renderSessionList();
    });
  } catch (error) {
    console.error(error);
  }
}

function setActiveSessionHighlight(sessionId) {
  sessionListElement.querySelectorAll(".session-item").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.sessionId) === Number(sessionId));
  });
}

function renderSessionList() {
  sessionListElement.innerHTML = "";
  if (!sessions.length) {
    const emptyState = document.createElement("p");
    emptyState.className = "session-meta";
    emptyState.textContent = "No chats yet. Start one below.";
    sessionListElement.appendChild(emptyState);
    return;
  }
  sessions.forEach((session) => {
    const entry = chatCache[session.id];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.dataset.sessionId = session.id;
    const title = (session.goals || `Chat ${session.id}`).slice(0, 60);
    const preview = entry && entry.lastMessagePreview ? entry.lastMessagePreview.slice(0, 90) : "";
    button.innerHTML = `
      <div class="session-title">${escapeHtml(title)}</div>
      ${preview ? `<div class="session-preview">${escapeHtml(preview)}</div>` : ""}
      <div class="session-meta">${escapeHtml(timeAgo(timeOf(session)))}</div>
    `;
    button.addEventListener("click", () => openChatPanel(session.id));
    sessionListElement.appendChild(button);
  });
  setActiveSessionHighlight(currentSessionId);
}

newChatButton.addEventListener("click", () => {
  newChatGoalsInput.value = "";
  showElement(newChatInline);
  newChatGoalsInput.focus();
});
newChatCancelButton.addEventListener("click", () => hideElement(newChatInline));

async function submitNewChat() {
  const goals = newChatGoalsInput.value.trim();
  if (!goals) return;
  try {
    const response = await fetch("/session", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ goals }),
    });
    if (!response.ok) return;
    const data = await response.json();
    const createdChat = { id: data.session_id, goals, created_at: new Date().toISOString() };
    sessions = [createdChat, ...sessions.filter((s) => Number(s.id) !== Number(data.session_id))];
    renderSessionList();
    hideElement(newChatInline);
    openChatPanel(data.session_id, { fresh: true, goals });
    const welcomeText = "New chat started. Ask me anything about this pursuit.";
    addMessageBubble("assistant", welcomeText);
    appendCachedMessage(data.session_id, { role: "assistant", content: welcomeText });
  } catch (error) {
    console.error(error);
  }
}
newChatSubmitButton.addEventListener("click", submitNewChat);

async function startChatFromPrompt(promptText) {
  try {
    const response = await fetch("/session", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ goals: promptText.slice(0, 120) }),
    });
    if (!response.ok) return;
    const data = await response.json();
    const createdChat = { id: data.session_id, goals: promptText.slice(0, 120), created_at: new Date().toISOString() };
    sessions = [createdChat, ...sessions.filter((s) => Number(s.id) !== Number(data.session_id))];
    // Docks exactly like picking a chat from the belt list: focus('belt')
    // then focus('belt-chat'), so closing it lands back on the belt view.
    if (isSceneReady()) MR.scene.focus("belt");
    openChatPanel(data.session_id, { fresh: true, goals: createdChat.goals });
    messageInput.value = promptText;
    await sendMessage();
  } catch (error) {
    console.error(error);
  }
}

const extractAssistantText = (content) => {
  if (typeof content !== "string") return content;
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") || trimmed.indexOf('"assistant_response"') === -1) return content;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed.assistant_response === "string") return parsed.assistant_response;
  } catch (err) {
    /* not actually JSON */
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

const clearChips = () => { chipsContainer.innerHTML = ""; };

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
  if (!Array.isArray(chips) || !chips.length) return;
  chips.forEach((text) => {
    const chip = buildChip(text, () => {
      messageInput.value = text;
      sendMessage();
    });
    if (chip) chipsContainer.appendChild(chip);
  });
};

const clearChatState = () => {
  messageArea.innerHTML = "";
  clearChips();
};

const setSession = (sessionId, { skipHistory = false } = {}) => {
  currentSessionId = sessionId;
  localStorage.setItem(sessionStorageKey, String(sessionId));
  setActiveSessionHighlight(sessionId);
  if (!skipHistory) loadHistory();
  else clearChatState();
};

const handleError = async (response) => {
  const text = await response.text();
  addMessageBubble("assistant", `Error: ${response.status} ${escapeHtml(text)}`);
};

async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text || !currentSessionId) return;
  const sendingSessionId = currentSessionId;
  addMessageBubble("user", escapeHtml(text));
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
      if (sendingSessionId === currentSessionId) return handleError(response);
      return;
    }
    const data = await response.json();
    appendCachedMessage(sendingSessionId, { role: "assistant", content: data.assistant_response });
    if (sendingSessionId === currentSessionId) {
      addMessageBubble("assistant", extractAssistantText(data.assistant_response));
    }

    const radar = await loadCareerRadarForSession(sendingSessionId);
    if (radar) ensureCacheEntry(sendingSessionId).radar = radar;

    if (sendingSessionId === currentSessionId) showSuggestedChips(data.suggested_replies || []);
    loadNorthStar();
    triggerReshuffle("chat:completed");
    if (data.career_radar_updates && data.career_radar_updates.length) triggerReshuffle("radar:changed");
  } catch (error) {
    if (sendingSessionId === currentSessionId) {
      addMessageBubble("assistant", "Unable to reach the server. Please try again.");
    }
    console.error(error);
  }
}
sendButton.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

async function loadCareerRadarForSession(sessionId) {
  if (!sessionId) return null;
  try {
    const response = await fetch(`/career-radar/${sessionId}`, { headers: deviceHeaders() });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload.opportunities || [];
  } catch (error) {
    console.error(error);
    return null;
  }
}

async function loadHistory() {
  const requestedSessionId = currentSessionId;
  const seq = ++chatRequestSeq;
  const isStale = () => seq !== chatRequestSeq || requestedSessionId !== currentSessionId;

  clearChatState();
  if (!requestedSessionId) return;

  const cached = chatCache[requestedSessionId];
  if (cached && cached.messages.length) {
    chatGoalElement.textContent = cached.goals || "—";
    cached.messages.forEach((m) => addMessageBubble(m.role, extractAssistantText(m.content)));
    return;
  }

  try {
    const response = await fetch(`/session/${requestedSessionId}/history`, { headers: deviceHeaders() });
    if (isStale()) return;
    if (!response.ok) return;
    const payload = await response.json();
    if (isStale()) return;
    const goals = (payload.session && payload.session.goals) || "—";
    chatGoalElement.textContent = goals;
    payload.messages.forEach((m) => addMessageBubble(m.role, extractAssistantText(m.content)));
    const radar = await loadCareerRadarForSession(requestedSessionId);
    if (isStale()) return;
    chatCache[requestedSessionId] = {
      goals,
      messages: payload.messages || [],
      radar: radar || [],
      plan: payload.plan || [],
      documentReviews: null,
      lastMessagePreview: (payload.messages || []).length
        ? extractAssistantText(payload.messages[payload.messages.length - 1].content)
        : "",
    };
  } catch (error) {
    console.error(error);
  }
}

/* ============================================================
   Career Radar (moon) - aggregated across every chat, since the
   spec asks for opportunities "mentioned across the student's
   chats" but the backend only exposes radar per session.
   ============================================================ */
let radarItems = []; // flattened, each tagged with _sourceGoals/_sourceSessionId

async function loadRadarAcrossChats() {
  radarListElement.innerHTML = `<div class="radar-empty">Loading your Career Radar...</div>`;
  if (!sessions.length) await loadSessions();
  try {
    const results = await Promise.all(
      sessions.map(async (session) => {
        const opportunities = await loadCareerRadarForSession(session.id);
        return (opportunities || []).map((item) => ({
          ...item,
          _sourceSessionId: session.id,
          _sourceGoals: session.goals || `Chat ${session.id}`,
        }));
      })
    );
    radarItems = results.flat().sort((a, b) => (b.priority_score || 5) - (a.priority_score || 5));
    renderRadar();
  } catch (error) {
    console.error(error);
    radarListElement.innerHTML = `<div class="radar-empty radar-error">Couldn't load your Career Radar. Please try again.</div>`;
  }
}

function renderRadar() {
  radarListElement.innerHTML = "";
  if (!radarItems.length) {
    radarListElement.innerHTML = `<div class="radar-empty">Your Career Radar is still empty. Start a conversation to add opportunities.</div>`;
    return;
  }
  const notes = getOpportunityNotes();
  radarItems.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "radar-card";
    card.draggable = true;
    card.dataset.index = String(index);
    card.innerHTML = `
      <div class="radar-card-header">
        <div>
          <h3>${escapeHtml(item.title || "Untitled opportunity")}</h3>
          <p class="pill">${escapeHtml(item.category || "Other")}</p>
        </div>
        <span class="priority-pill">P${item.priority_score || 5}</span>
      </div>
      <p class="radar-description">${escapeHtml(item.description || "")}</p>
      <p class="radar-reason">${escapeHtml(item.reason_relevant || "")}</p>
      <p class="radar-meta">
        <span>From: ${escapeHtml(item._sourceGoals)}</span>
        <span>Status: ${escapeHtml(item.status || "suggested")}</span>
      </p>
      <textarea class="radar-notes" placeholder="Add a note...">${escapeHtml(notes[item.id] || "")}</textarea>
      <div class="radar-meta">
        ${item.source_url ? `<a href="${item.source_url}" target="_blank" rel="noreferrer">Open source</a>` : "<span></span>"}
        <span class="radar-reorder">
          <button type="button" class="secondary-button radar-move-up" ${index === 0 ? "disabled" : ""}>&uarr;</button>
          <button type="button" class="secondary-button radar-move-down" ${index === radarItems.length - 1 ? "disabled" : ""}>&darr;</button>
        </span>
      </div>
    `;

    card.querySelector(".radar-notes").addEventListener("change", (event) => {
      setOpportunityNote(item.id, event.target.value);
    });
    card.querySelector(".radar-move-up").addEventListener("click", () => moveRadarItem(index, index - 1));
    card.querySelector(".radar-move-down").addEventListener("click", () => moveRadarItem(index, index + 1));

    card.addEventListener("dragstart", (event) => {
      card.classList.add("dragging");
      event.dataTransfer.setData("text/plain", String(index));
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      card.classList.remove("drag-over");
      const fromIndex = Number(event.dataTransfer.getData("text/plain"));
      moveRadarItem(fromIndex, index);
    });

    radarListElement.appendChild(card);
  });
}

async function moveRadarItem(fromIndex, toIndex) {
  if (fromIndex === toIndex || toIndex < 0 || toIndex >= radarItems.length) return;
  const [moved] = radarItems.splice(fromIndex, 1);
  radarItems.splice(toIndex, 0, moved);
  renderRadar();
  await persistRadarOrder();
  triggerReshuffle("radar:changed");
}

async function persistRadarOrder() {
  // No dedicated order column on opportunities - priority_score (1-10,
  // clamped server-side) doubles as the ranking key. Only PATCH items whose
  // target score actually changed.
  const total = radarItems.length;
  const updates = radarItems.map((item, index) => {
    const targetScore = Math.max(1, Math.min(10, total - index));
    return { item, targetScore };
  }).filter(({ item, targetScore }) => (item.priority_score || 5) !== targetScore);

  await Promise.all(
    updates.map(async ({ item, targetScore }) => {
      item.priority_score = targetScore;
      try {
        await fetch(`/opportunities/${item.id}`, {
          method: "PATCH",
          headers: deviceHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ priority_score: targetScore }),
        });
      } catch (error) {
        console.error(error);
      }
    })
  );
}

/* ============================================================
   North Star / Action Plan (star)
   ============================================================ */
document.querySelectorAll('[data-star-tab]').forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.dataset.starTab;
    document.querySelectorAll('[data-star-tab]').forEach((t) => t.classList.toggle("active", t === tab));
    document.getElementById("star-tab-northstar").classList.toggle("hidden", target !== "northstar");
    document.getElementById("star-tab-actionplan").classList.toggle("hidden", target !== "actionplan");
    if (isSceneReady()) MR.scene.setStarMode(target === "actionplan" ? "actionplan" : "northstar");
  });
});

northstarGoalSaveButton.addEventListener("click", () => {
  setNorthStarGoal(northstarGoalInput.value.trim());
  northstarGoalStatus.textContent = "Saved.";
  window.setTimeout(() => { northstarGoalStatus.textContent = ""; }, 2000);
});

const buildActionChip = (text) =>
  buildChip(text, () => {
    openChatsPanel();
    // Land straight in the most recent chat with the suggestion queued.
    if (sessions.length) {
      openChatPanel(sessions[0].id);
      messageInput.value = text;
      sendMessage();
    }
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
  if (chip) el.appendChild(chip);
  return el;
};

const buildNorthStarSection = (label, items) => {
  const block = document.createElement("div");
  block.className = "northstar-section";
  const heading = document.createElement("div");
  heading.className = "panel-header";
  heading.innerHTML = `<div><p class="section-label">${escapeHtml(label)}</p></div>`;
  block.appendChild(heading);
  items.forEach((item) => block.appendChild(buildNorthStarItem(item)));
  return block;
};

const renderNorthStarMeta = (payload) => {
  northstarUpdatedElement.textContent = payload && payload.generated_at ? `Last updated ${timeAgo(payload.generated_at)}` : "";
  const whatsNew = Array.isArray(payload && payload.whats_new) ? payload.whats_new : [];
  if (!whatsNew.length) {
    hideElement(northstarWhatsNewElement);
    northstarWhatsNewElement.innerHTML = "";
    return;
  }
  northstarWhatsNewElement.innerHTML = `<p>What's new</p><ul>${whatsNew.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
  showElement(northstarWhatsNewElement);
};

const renderNorthStar = (payload) => {
  renderNorthStarMeta(payload);
  const noEvidence = !payload || payload.has_evidence === false;
  if (noEvidence) {
    northstarOutputElement.innerHTML = `<div class="radar-empty">Moonreach will build this from everything in your workspace. Add an opportunity on the Career Radar or share a goal in a chat and check back here.</div>`;
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
      ${evidence.length ? `<ul class="northstar-evidence">${evidence.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
      ${alternatives.length ? `<p class="northstar-alts">Alternate paths: ${alternatives.map((a) => `<span class="pill">${escapeHtml(a)}</span>`).join(" ")}</p>` : ""}
    </div>
  `;
  const priorities = Array.isArray(payload.priorities) ? payload.priorities.slice(0, 3) : [];
  if (priorities.length) northstarOutputElement.appendChild(buildNorthStarSection("Top priorities", priorities));
  const risks = Array.isArray(payload.risks) ? payload.risks.slice(0, 3) : [];
  if (risks.length) northstarOutputElement.appendChild(buildNorthStarSection("Risks to watch", risks));
  const upcoming = Array.isArray(payload.upcoming_opportunities) ? payload.upcoming_opportunities.slice(0, 3) : [];
  if (upcoming.length) northstarOutputElement.appendChild(buildNorthStarSection("Upcoming opportunities", upcoming));
};

async function loadNorthStar() {
  if (!profile) return;
  if (cachedNorthStarPayload) renderNorthStar(cachedNorthStarPayload);
  else northstarOutputElement.innerHTML = NORTHSTAR_PLACEHOLDER;

  const seq = ++northstarRequestSeq;
  const isLatest = () => northstarRequestSeq === seq;
  refreshNorthStarButton.disabled = true;
  refreshNorthStarButton.textContent = "Updating…";
  try {
    const response = await fetch("/north-star", { method: "POST", headers: deviceHeaders() });
    if (!response.ok) {
      if (isLatest() && !cachedNorthStarPayload) {
        northstarOutputElement.innerHTML = `<div class="radar-empty radar-error">North Star failed to load (${response.status}). Please try again.</div>`;
      }
      return;
    }
    const payload = await response.json();
    cachedNorthStarPayload = payload;
    try { localStorage.setItem(northstarCacheKey, JSON.stringify(payload)); } catch (e) { /* ignore */ }
    if (isLatest()) renderNorthStar(payload);
  } catch (error) {
    console.error(error);
    if (isLatest() && !cachedNorthStarPayload) {
      northstarOutputElement.innerHTML = `<div class="radar-empty radar-error">North Star failed to load. Please try again.</div>`;
    }
  } finally {
    if (isLatest()) {
      refreshNorthStarButton.disabled = false;
      refreshNorthStarButton.textContent = "Refresh analysis";
    }
  }
}
refreshNorthStarButton.addEventListener("click", () => {
  cachedNorthStarPayload = null;
  loadNorthStar();
});

function populatePlanSessionSelect() {
  const previous = planSessionSelect.value;
  planSessionSelect.innerHTML = "";
  if (!sessions.length) {
    const opt = document.createElement("option");
    opt.textContent = "No chats yet";
    opt.disabled = true;
    planSessionSelect.appendChild(opt);
    return;
  }
  sessions.forEach((session) => {
    const opt = document.createElement("option");
    opt.value = String(session.id);
    opt.textContent = (session.goals || `Chat ${session.id}`).slice(0, 60);
    planSessionSelect.appendChild(opt);
  });
  const preferred = previous || (currentSessionId ? String(currentSessionId) : "") || String(sessions[0].id);
  if ([...planSessionSelect.options].some((o) => o.value === preferred)) {
    planSessionSelect.value = preferred;
  }
  renderPlanForSelectedSession();
}
planSessionSelect.addEventListener("change", renderPlanForSelectedSession);

const normalizePlan = (plan) => {
  if (Array.isArray(plan)) return plan.filter((i) => typeof i === "string" && i.trim()).map((i) => i.trim());
  if (typeof plan === "string") {
    try {
      const parsed = JSON.parse(plan);
      if (Array.isArray(parsed)) return parsed.filter((i) => typeof i === "string" && i.trim()).map((i) => i.trim());
    } catch (err) {
      return plan.split(/\n+/).map((i) => i.trim()).filter(Boolean);
    }
  }
  return [];
};

const PLAN_STATUS_CYCLE = ["not_started", "in_progress", "done"];
const PLAN_STATUS_LABEL = { not_started: "Not started", in_progress: "In progress", done: "Done" };

function renderPlan(sessionId, plan) {
  const items = normalizePlan(plan);
  planList.innerHTML = "";
  if (!items.length) {
    planList.innerHTML = `<li class="radar-empty">No action plan generated yet for this chat. Click "Generate plan" above.</li>`;
    return;
  }
  const statuses = getPlanStatuses(sessionId);
  items.forEach((text, index) => {
    const status = statuses[index] || "not_started";
    const li = document.createElement("li");
    li.className = `plan-item status-${status}`;
    li.innerHTML = `
      <span class="plan-item-text">${escapeHtml(text)}</span>
      <button type="button" class="plan-item-status">${PLAN_STATUS_LABEL[status]}</button>
    `;
    li.querySelector(".plan-item-status").addEventListener("click", () => {
      const current = getPlanStatuses(sessionId)[index] || "not_started";
      const next = PLAN_STATUS_CYCLE[(PLAN_STATUS_CYCLE.indexOf(current) + 1) % PLAN_STATUS_CYCLE.length];
      setPlanStatus(sessionId, index, next);
      renderPlan(sessionId, plan);
      triggerReshuffle("actionplan:changed");
    });
    planList.appendChild(li);
  });
}

function renderPlanForSelectedSession() {
  const sessionId = planSessionSelect.value;
  if (!sessionId) {
    planList.innerHTML = "";
    return;
  }
  const cached = chatCache[sessionId];
  if (cached && cached.plan && cached.plan.length) {
    renderPlan(sessionId, cached.plan);
  } else {
    planList.innerHTML = `<li class="radar-empty">No action plan generated yet for this chat. Click "Generate plan" above.</li>`;
  }
}

planButton.addEventListener("click", async () => {
  const sessionId = planSessionSelect.value;
  if (!sessionId) return;
  try {
    const response = await fetch("/plan", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ session_id: Number(sessionId) }),
    });
    if (!response.ok) return handleError(response);
    const data = await response.json();
    ensureCacheEntry(sessionId).plan = data.plan || [];
    if (planSessionSelect.value === sessionId) renderPlan(sessionId, data.plan);
    triggerReshuffle("actionplan:changed");
  } catch (error) {
    console.error(error);
  }
});

/* ============================================================
   Boot
   ============================================================ */
onboardingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const university = document.getElementById("onboarding-university").value.trim();
  const major = document.getElementById("onboarding-major").value.trim();
  const year = document.getElementById("onboarding-year").value.trim();
  if (!university || !major || !year) return;
  try {
    const response = await fetch("/profile", {
      method: "POST",
      headers: deviceHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ university, major, year }),
    });
    if (!response.ok) return;
    const data = await response.json();
    profile = data.profile;
    hideOnboarding();
    await loadSessions();
  } catch (error) {
    console.error(error);
  }
});

profileForm.addEventListener("submit", saveProfileForm);

async function bootstrap() {
  wireSceneEvents();
  try {
    const response = await fetch("/profile", { headers: deviceHeaders() });
    if (!response.ok) {
      showOnboarding();
      return;
    }
    const data = await response.json();
    profile = data.profile;
    await loadSessions();
    if (isSceneReady()) MR.scene.reshuffleStars(pickRandomPromptIds(5));
  } catch (error) {
    console.error(error);
    showOnboarding();
  }
}

bootstrap();
