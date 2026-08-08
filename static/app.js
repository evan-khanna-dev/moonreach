const sessionStorageKey = "moonreach_session_id";
const onboardingSection = document.getElementById("onboarding");
const workspaceSection = document.getElementById("workspace-container");
const messageArea = document.getElementById("message-area");
const chipsContainer = document.getElementById("chips");
const sessionIdElement = document.getElementById("session-id");
const planSection = document.getElementById("plan-output");
const planList = document.getElementById("plan-list");
const radarListElement = document.getElementById("radar-list");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-message");
const planButton = document.getElementById("generate-plan");
const resetButton = document.getElementById("reset-session");
const newSessionButton = document.getElementById("new-session-button");
const sessionListElement = document.getElementById("session-list");
const sessionContextElement = document.getElementById("session-context");

let currentSessionId = localStorage.getItem(sessionStorageKey);
let sessions = [];

const getRequestHeaders = (extraHeaders = {}) => ({
  ...extraHeaders,
});

const showElement = (element) => element.classList.remove("hidden");
const hideElement = (element) => element.classList.add("hidden");

const showOnboarding = () => {
  hideElement(workspaceSection);
  showElement(onboardingSection);
};

const showWorkspace = () => {
  hideElement(onboardingSection);
  showElement(workspaceSection);
};

const addMessageBubble = (role, content) => {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.innerHTML = `<div class="meta">${role === "user" ? "You" : "Coach"}</div><div>${content}</div>`;
  messageArea.appendChild(bubble);
  messageArea.scrollTop = messageArea.scrollHeight;
};

const clearChatState = () => {
  messageArea.innerHTML = "";
  clearChips();
  planList.innerHTML = "";
  hideElement(planSection);
  radarListElement.innerHTML = "";
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
    emptyState.textContent = "No saved sessions yet.";
    sessionListElement.appendChild(emptyState);
    return;
  }

  sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.dataset.sessionId = session.id;
    button.innerHTML = `
      <div class="session-title">${session.university || `Session ${session.id}`}</div>
      <div class="session-meta">${[session.major, session.year].filter(Boolean).join(" • ")}</div>
    `;
    button.addEventListener("click", () => {
      setSession(session.id);
    });
    sessionListElement.appendChild(button);
  });
  setActiveSession(currentSessionId);
};

const renderSessionContext = (session) => {
  if (!session) {
    sessionContextElement.innerHTML = "";
    sessionContextElement.classList.add("hidden");
    return;
  }

  sessionContextElement.classList.remove("hidden");
  sessionContextElement.innerHTML = `
    <h2>Student profile</h2>
    <div class="profile-grid">
      <div class="profile-row">
        <span class="profile-label">University</span>
        <span class="profile-value">${session.university || "—"}</span>
      </div>
      <div class="profile-row">
        <span class="profile-label">Major</span>
        <span class="profile-value">${session.major || "—"}</span>
      </div>
      <div class="profile-row">
        <span class="profile-label">Year / Level</span>
        <span class="profile-value">${session.year || "—"}</span>
      </div>
      <div class="profile-row">
        <span class="profile-label">Career Goal</span>
        <span class="profile-value">${session.goals || "—"}</span>
      </div>
    </div>
    <p class="profile-note">This is the context the AI remembers and uses to personalize your coaching.</p>
  `;
};

const setSession = (sessionId, { skipHistory = false } = {}) => {
  currentSessionId = sessionId;
  localStorage.setItem(sessionStorageKey, String(sessionId));
  sessionIdElement.textContent = String(sessionId);
  setActiveSession(sessionId);
  showWorkspace();
  if (!skipHistory) {
    loadHistory();
  }
};

const clearChips = () => {
  chipsContainer.innerHTML = "";
};

const showSuggestedChips = (chips) => {
  clearChips();
  if (!Array.isArray(chips) || !chips.length) {
    return;
  }
  chips.forEach((text) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = text;
    chip.addEventListener("click", () => {
      messageInput.value = text;
      sendMessage();
    });
    chipsContainer.appendChild(chip);
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
    planList.innerHTML = "";
    hideElement(planSection);
    return;
  }

  planList.innerHTML = "";
  normalizedPlan.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    planList.appendChild(li);
  });
  showElement(planSection);
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

const handleError = async (response) => {
  const text = await response.text();
  addMessageBubble("assistant", `Error: ${response.status} ${text}`);
};

const loadSessions = async () => {
  try {
    const response = await fetch("/sessions", { headers: getRequestHeaders() });
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
  addMessageBubble("user", text);
  messageInput.value = "";
  clearChips();
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: getRequestHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ session_id: Number(currentSessionId), message: text }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    addMessageBubble("assistant", data.assistant_response);
    await loadCareerRadar();
    showSuggestedChips(data.suggested_replies || []);
  } catch (error) {
    addMessageBubble("assistant", "Unable to reach the server. Please try again.");
    console.error(error);
  }
};

const loadCareerRadar = async () => {
  if (!currentSessionId) {
    return;
  }
  try {
    const response = await fetch(`/career-radar/${currentSessionId}`, { headers: getRequestHeaders() });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderRadar(payload.opportunities || []);
  } catch (error) {
    console.error(error);
  }
};

const loadHistory = async () => {
  clearChatState();
  if (!currentSessionId) {
    showOnboarding();
    return;
  }
  try {
    const response = await fetch(`/session/${currentSessionId}/history`, { headers: getRequestHeaders() });
    if (!response.ok) {
      localStorage.removeItem(sessionStorageKey);
      currentSessionId = null;
      setActiveSession(null);
      return showOnboarding();
    }
    const payload = await response.json();
    sessionIdElement.textContent = String(currentSessionId);
    renderSessionContext(payload.session);
    payload.messages.forEach((message) => {
      addMessageBubble(message.role, message.content);
    });
    renderPlan(payload.plan);
    await loadCareerRadar();
    showWorkspace();
  } catch (error) {
    console.error(error);
    showOnboarding();
  }
};

const createSession = async (event) => {
  event.preventDefault();
  const university = document.getElementById("university").value.trim();
  const major = document.getElementById("major").value.trim();
  const year = document.getElementById("year").value.trim();
  const goals = document.getElementById("goals").value.trim();

  if (!university || !major || !year || !goals) {
    return;
  }

  try {
    const response = await fetch("/session", {
      method: "POST",
      headers: getRequestHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ university, major, year, goals }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    const createdSession = { id: data.session_id, university, major, year, goals };
    sessions = [createdSession, ...sessions.filter((session) => Number(session.id) !== Number(data.session_id))];
    renderSessionList();
    setSession(data.session_id, { skipHistory: true });
    await loadHistory();
    addMessageBubble("assistant", "Session started. Ask me anything about career opportunities, internships, or next steps.");
  } catch (error) {
    addMessageBubble("assistant", "Unable to create a session. Please try again.");
    console.error(error);
  }
};

const generatePlan = async () => {
  if (!currentSessionId) {
    return;
  }
  try {
    const response = await fetch("/plan", {
      method: "POST",
      headers: getRequestHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ session_id: Number(currentSessionId) }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    renderPlan(data.plan);
  } catch (error) {
    addMessageBubble("assistant", "Unable to generate a plan. Please try again.");
    console.error(error);
  }
};

const resetSession = () => {
  localStorage.removeItem(sessionStorageKey);
  currentSessionId = null;
  clearChatState();
  sessionIdElement.textContent = "";
  renderSessionContext(null);
  setActiveSession(null);
  showOnboarding();
};

document.getElementById("onboarding-form").addEventListener("submit", createSession);
sendButton.addEventListener("click", sendMessage);
planButton.addEventListener("click", generatePlan);
resetButton.addEventListener("click", resetSession);
newSessionButton.addEventListener("click", resetSession);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

loadSessions();
if (currentSessionId) {
  setSession(currentSessionId, { skipHistory: true });
  loadHistory();
} else {
  showOnboarding();
}
