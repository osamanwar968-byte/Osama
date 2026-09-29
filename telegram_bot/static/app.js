const sessionStorageKey = "arabic-assistant-session";
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");
const imageForm = document.getElementById("imageForm");
const imagePrompt = document.getElementById("imagePrompt");
const imagePreview = document.getElementById("imagePreview");
const toast = document.getElementById("toast");

let sessionId = window.localStorage.getItem(sessionStorageKey) || "";
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 4500);
}

function addMessage(role, text) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "أ" : "م";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  const time = document.createElement("time");
  time.textContent = "الآن";

  bubble.append(paragraph, time);
  wrapper.append(avatar, bubble);
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setFormLoading(form, loading) {
  form.classList.toggle("is-loading", loading);
  const button = form.querySelector("button");
  if (button) button.disabled = loading;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  addMessage("user", message);
  chatInput.value = "";
  setFormLoading(chatForm, true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "تعذر إرسال الرسالة.");
    sessionId = data.session_id;
    window.localStorage.setItem(sessionStorageKey, sessionId);
    addMessage("assistant", data.reply);
  } catch (error) {
    showToast(error.message || "حدث خطأ غير متوقع.");
  } finally {
    setFormLoading(chatForm, false);
    chatInput.focus();
  }
});

imageForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = imagePrompt.value.trim();
  if (!prompt) return;

  setFormLoading(imageForm, true);
  const button = imageForm.querySelector("button span:last-child");
  const originalButtonText = button.textContent;
  button.textContent = "جارٍ إنشاء الصورة...";

  try {
    const response = await fetch("/api/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || "تعذر إنشاء الصورة.");
    }

    const blob = await response.blob();
    const imageUrl = URL.createObjectURL(blob);
    imagePreview.classList.add("has-image");
    imagePreview.replaceChildren();
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = prompt;
    imagePreview.appendChild(image);
  } catch (error) {
    showToast(error.message || "حدث خطأ غير متوقع.");
  } finally {
    button.textContent = originalButtonText;
    setFormLoading(imageForm, false);
  }
});