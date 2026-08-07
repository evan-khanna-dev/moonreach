const sessionStorageKey = "moonreach_session_id";
const onboardingSection = document.getElementById("onboarding");
const chatSection = document.getElementById("chat-container");
const messageArea = document.getElementById("message-area");
const chipsContainer = document.getElementById("chips");
const sessionIdElement = document.getElementById("session-id");
const planSection = document.getElementById("plan-output");
const planList = document.getElementById("plan-list");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-message");
const planButton = document.getElementById("generate-plan");
const resetButton = document.getElementById("reset-session");

let currentSessionId = localStorage.getItem(sessionStorageKey);

const showElement = (element) => element.classList.remove("hidden");
const hideElement = (element) => element.classList.add("hidden");

const showOnboarding = () => {
  hideElement(chatSection);
  showElement(onboardingSection);
};

const showChat = () => {
  hideElement(onboardingSection);
  showElement(chatSection);
};

const addMessageBubble = (role, content) => {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.innerHTML = `<div class="meta">${role === "user" ? "You" : "Coach"}</div><div>${content}</div>`;
  messageArea.appendChild(bubble);
  messageArea.scrollTop = messageArea.scrollHeight;
};

const setSession = (sessionId) => {
  currentSessionId = sessionId;
  localStorage.setItem(sessionStorageKey, String(sessionId));
  sessionIdElement.textContent = String(sessionId);
  showChat();
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

const handleError = async (response) => {
  const text = await response.text();
  addMessageBubble("assistant", `Error: ${response.status} ${text}`);
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: Number(currentSessionId), message: text }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    addMessageBubble("assistant", data.assistant_response);
    showSuggestedChips(data.suggested_replies || []);
  } catch (error) {
    addMessageBubble("assistant", "Unable to reach the server. Please try again.");
    console.error(error);
  }
};

const loadHistory = async () => {
  if (!currentSessionId) {
    showOnboarding();
    return;
  }
  try {
    const response = await fetch(`/session/${currentSessionId}/history`);
    if (!response.ok) {
      localStorage.removeItem(sessionStorageKey);
      currentSessionId = null;
      return showOnboarding();
    }
    const payload = await response.json();
    sessionIdElement.textContent = String(currentSessionId);
    messageArea.innerHTML = "";
    payload.messages.forEach((message) => {
      addMessageBubble(message.role, message.content);
    });
    showChat();
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ university, major, year, goals }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    setSession(data.session_id);
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: Number(currentSessionId) }),
    });
    if (!response.ok) {
      return handleError(response);
    }
    const data = await response.json();
    planList.innerHTML = "";
    data.plan.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      planList.appendChild(li);
    });
    showElement(planSection);
  } catch (error) {
    addMessageBubble("assistant", "Unable to generate a plan. Please try again.");
    console.error(error);
  }
};

const resetSession = () => {
  localStorage.removeItem(sessionStorageKey);
  currentSessionId = null;
  messageArea.innerHTML = "";
  clearChips();
  planList.innerHTML = "";
  hideElement(planSection);
  showOnboarding();
};

document.getElementById("onboarding-form").addEventListener("submit", createSession);
sendButton.addEventListener("click", sendMessage);
planButton.addEventListener("click", generatePlan);
resetButton.addEventListener("click", resetSession);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

if (currentSessionId) {
  loadHistory();
} else {
  showOnboarding();
}
