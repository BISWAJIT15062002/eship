const chatToggle = document.getElementById("chatToggle");
const chatClose = document.getElementById("chatClose");
const chatPanel = document.getElementById("chatPanel");
const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");

function setChatOpen(open) {
  chatPanel.classList.toggle("is-open", open);
  chatPanel.setAttribute("aria-hidden", String(!open));
  chatToggle.setAttribute("aria-expanded", String(open));
  if (open) {
    chatInput.focus();
  }
}

function addMessage(text, sender) {
  const message = document.createElement("div");
  message.className = `chat-message ${sender}`;
  message.textContent = text;
  chatMessages.appendChild(message);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function askChatbot(message) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    throw new Error("Chat request failed");
  }

  return response.json();
}

chatToggle.addEventListener("click", () => {
  setChatOpen(!chatPanel.classList.contains("is-open"));
});

chatClose.addEventListener("click", () => {
  setChatOpen(false);
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    return;
  }

  chatInput.value = "";
  addMessage(message, "user");
  addMessage("Searching ship data...", "bot pending");

  try {
    const data = await askChatbot(message);
    chatMessages.querySelector(".pending")?.remove();
    addMessage(data.reply, "bot");
  } catch (error) {
    chatMessages.querySelector(".pending")?.remove();
    addMessage("Chat is not available right now. Please try again.", "bot error");
  }
});
