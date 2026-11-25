const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body instanceof FormData ? {} : {"Content-Type": "application/json"}), ...(options.headers || {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function toast(message, error = false) {
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.textContent = message;
  $("#toastRegion").append(node);
  setTimeout(() => node.remove(), 3500);
}
function setBusy(button, busy, label = "Please wait…") {
  if (!button) return;
  if (busy) { button.dataset.original = button.innerHTML; button.disabled = true; button.textContent = label; }
  else { button.disabled = false; if (button.dataset.original) button.innerHTML = button.dataset.original; }
}

// Reveal elements every time they enter the viewport, including when scrolling back upward.
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
if ("IntersectionObserver" in window && !reduceMotion) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) entry.target.classList.add("is-visible");
      else entry.target.classList.remove("is-visible");
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -35px 0px" });
  $$(".reveal").forEach(el => observer.observe(el));
} else {
  $$(".reveal").forEach(el => el.classList.add("is-visible"));
}

const header = $(".site-header");
function updateHeader() { header.classList.toggle("scrolled", window.scrollY > 12); }
window.addEventListener("scroll", updateHeader, { passive: true }); updateHeader();

const menuToggle = $("#menuToggle"), mainNav = $("#mainNav");
menuToggle.addEventListener("click", () => {
  const open = mainNav.classList.toggle("open");
  menuToggle.setAttribute("aria-expanded", String(open));
});
$$(".main-nav a").forEach(link => link.addEventListener("click", () => {
  mainNav.classList.remove("open"); menuToggle.setAttribute("aria-expanded", "false");
}));
const sections = $$("main section[id]");
if ("IntersectionObserver" in window) {
  const navObserver = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      $$(".main-nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === `#${entry.target.id}`));
    }
  }), { rootMargin: "-35% 0px -55% 0px" });
  sections.forEach(s => navObserver.observe(s));
}

// Authentication modal and session state.
let authMode = "register";
const modal = $("#authModal");
function openAuth(mode) {
  authMode = mode; modal.classList.remove("hidden");
  $$(".auth-tab").forEach(t => t.classList.toggle("active", t.dataset.mode === mode));
  $("#authTitle").textContent = mode === "register" ? "Create your account." : "Welcome back.";
  $("#authSubtitle").textContent = mode === "register" ? "Save your work and track the materials you reuse." : "Log in to continue your creative loop.";
  $("#nameField").classList.toggle("hidden", mode === "login");
  $("#nameField input").required = mode === "register";
  $("#authForm [name=password]").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("#authSubmit").textContent = mode === "register" ? "Create account →" : "Log in →";
  $("#authMessage").textContent = "";
}
$("#loginOpen").addEventListener("click", () => openAuth("login"));
$("#registerOpen").addEventListener("click", () => openAuth("register"));
$("#modalClose").addEventListener("click", () => modal.classList.add("hidden"));
modal.addEventListener("click", e => { if (e.target === modal) modal.classList.add("hidden"); });
$$(".auth-tab").forEach(tab => tab.addEventListener("click", () => openAuth(tab.dataset.mode)));

function updateAuthUI(user) {
  const loggedIn = Boolean(user);
  $("#userLabel").textContent = loggedIn ? `Hi, ${user.name}` : "";
  $("#loginOpen").classList.toggle("hidden", loggedIn);
  $("#registerOpen").classList.toggle("hidden", loggedIn);
  $("#logoutBtn").classList.toggle("hidden", !loggedIn);
  $("#impactMessage").textContent = loggedIn ? "Your reuse records are saved to your account." : "Log in to save and view your personal reuse history.";
  if (loggedIn) loadImpact({ showTotals: false });
  else resetImpactPreview();
}
async function loadMe() {
  try { const data = await api("/api/me"); updateAuthUI(data.user); }
  catch { updateAuthUI(null); }
}
$("#authForm").addEventListener("submit", async e => {
  e.preventDefault();
  const formElement = e.currentTarget;
  if (formElement.dataset.submitting === "true") return;
  formElement.dataset.submitting = "true";
  const form = new FormData(formElement);
  const payload = Object.fromEntries(form.entries());
  const button = $("#authSubmit"); setBusy(button, true);
  try {
    const data = await api(authMode === "register" ? "/api/register" : "/api/login", { method: "POST", body: JSON.stringify(payload) });
    modal.classList.add("hidden"); formElement.reset(); updateAuthUI(data.user);
    toast(data.message || "You're signed in.");
  } catch (err) { $("#authMessage").textContent = err.message; }
  finally { setBusy(button, false); formElement.dataset.submitting = "false"; }
});
$("#logoutBtn").addEventListener("click", async () => {
  try { const data = await api("/api/logout", { method: "POST", body: "{}" }); updateAuthUI(null); toast(data.message); }
  catch (err) { toast(err.message, true); }
});

// Fabric upload: drag/drop, preview and API analysis.
const fileInput = $("#fabricImage"), uploadZone = $("#uploadZone");
fileInput.addEventListener("change", () => {
  $("#selectedFile").textContent = fileInput.files[0] ? `Selected: ${fileInput.files[0].name}` : "";
});
["dragenter", "dragover"].forEach(evt => uploadZone.addEventListener(evt, e => { e.preventDefault(); uploadZone.classList.add("dragover"); }));
["dragleave", "drop"].forEach(evt => uploadZone.addEventListener(evt, e => { e.preventDefault(); uploadZone.classList.remove("dragover"); }));
uploadZone.addEventListener("drop", e => {
  const file = e.dataTransfer.files[0];
  if (file) { const transfer = new DataTransfer(); transfer.items.add(file); fileInput.files = transfer.files; fileInput.dispatchEvent(new Event("change")); }
});
$("#analyzeForm").addEventListener("submit", async e => {
  e.preventDefault();
  if (!fileInput.files[0]) return toast("Choose an image first.", true);
  const button = $("#analyzeBtn"); setBusy(button, true, "Analysing…");
  const body = new FormData(); body.append("image", fileInput.files[0]);
  try {
    const data = await api("/api/analyze", { method: "POST", body });
    const result = $("#analysisResult");
    result.classList.remove("hidden");
    const ai = data.fabric_ai;
    const aiPanel = ai ? `
      <div class="fabric-ai-result">
        <h4>AI visual fabric estimate</h4>
        <p><b>Likely appearance:</b> ${escapeHTML(ai.probable_fabric_type)}</p>
        <p><b>Possible fibre:</b> ${escapeHTML(ai.likely_fibre)}</p>
        <p><b>Confidence:</b> ${escapeHTML(ai.confidence)} <span class="muted">(visual estimate, not a calibrated probability)</span></p>
        <p><b>Why:</b> ${escapeHTML(ai.confidence_reason)}</p>
        <p><b>Construction:</b> ${escapeHTML(ai.construction)} · <b>Condition:</b> ${escapeHTML(ai.condition)}</p>
        <h4>Visible details</h4><ul>${(ai.visible_features || []).map(x => `<li>${escapeHTML(x)}</li>`).join("")}</ul>
        <h4>Projects that may suit it</h4><ul>${(ai.project_recommendations || []).map(r => `<li><b>${escapeHTML(r.title)}</b> (${escapeHTML(r.level)}) · ${escapeHTML(r.detail)}</li>`).join("")}</ul>
        <small>${escapeHTML(ai.limitations || "Photo-based estimate only.")}</small>
      </div>` : `<p><b>AI fabric type:</b> Not identified.</p><p>${escapeHTML(data.ai_notice)}</p>`;
    result.innerHTML = `<h4>Fabric analysis</h4>
      <p><span class="result-colour" style="background:${data.dominant_colour}"></span><b>${escapeHTML(data.dominant_colour)}</b> average colour</p>
      <p>Brightness: <b>${data.brightness}</b> · Contrast: <b>${data.contrast}</b> · Edge score: <b>${data.texture_score}</b></p>
      <img src="${data.image_url}" alt="Uploaded fabric" style="width:100%;max-height:150px;object-fit:cover;border-radius:9px">
      ${aiPanel}
      <h4>Basic image metrics</h4><small>${escapeHTML(data.notice)}</small>
      ${!ai ? `<h4>General reuse ideas</h4><ul>${data.recommendations.map(r => `<li><b>${escapeHTML(r.title)}</b> · ${escapeHTML(r.detail)}</li>`).join("")}</ul>` : ""}
      <p class="analysis-caution"><b>Important:</b> A photograph cannot confirm exact fibre content or percentages. Check the care label or use a textile test for verification.</p>`;
    toast("Fabric image analysed.");
  } catch (err) { toast(err.message, true); }
  finally { setBusy(button, false); }
});

// Prompt generator.
$("#promptForm").addEventListener("submit", async e => {
  e.preventDefault(); const button = $("button[type=submit]", e.currentTarget); setBusy(button, true, "Creating…");
  const payload = Object.fromEntries(new FormData(e.currentTarget).entries());
  try {
    const data = await api("/api/artwork/prompt", { method: "POST", body: JSON.stringify(payload) });
    const panel = $("#promptResult"); panel.classList.remove("hidden");
    panel.innerHTML = `<h4>Your artwork concept prompt</h4><p class="generated-prompt">${escapeHTML(data.prompt)}</p><small>${escapeHTML(data.notice)}</small><div class="prompt-actions"><button type="button" class="btn btn-outline btn-small copy-prompt">Copy prompt</button><a class="btn btn-primary btn-small" href="https://www.bing.com/images/create" target="_blank" rel="noopener noreferrer">Open image creator ↗</a></div><small class="prompt-help">Copy the prompt first, then paste it into the image creator.</small>`;
    $(".copy-prompt", panel).addEventListener("click", async () => {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(data.prompt);
        else { const temp = document.createElement("textarea"); temp.value = data.prompt; document.body.append(temp); temp.select(); document.execCommand("copy"); temp.remove(); }
        toast("Prompt copied. Paste it into the image creator.");
      } catch { toast("Select and copy the prompt text manually.", true); }
    });
  } catch (err) { toast(err.message, true); }
  finally { setBusy(button, false); }
});

// Tutorials and community gallery.
const tutorialIcons = ["✂", "▧", "✳", "⌁"];
async function loadTutorials() {
  try {
    const data = await api("/api/tutorials");
    $("#tutorialGrid").innerHTML = data.tutorials.map((t, i) => `
      <article class="tutorial-card reveal is-visible"><div class="tutorial-art">${tutorialIcons[i % tutorialIcons.length]}</div>
      <div class="tutorial-meta"><span>${escapeHTML(t.category)}</span><span>· ${escapeHTML(t.level)}</span><span>· ${escapeHTML(t.time)}</span></div>
      <h3>${escapeHTML(t.title)}</h3><details><summary>View steps</summary><ol>${t.steps.map(s => `<li>${escapeHTML(s)}</li>`).join("")}</ol></details></article>`).join("");
  } catch (err) { $("#tutorialGrid").textContent = err.message; }
}
async function loadGallery() {
  try {
    const data = await api("/api/gallery");
    $("#galleryGrid").innerHTML = data.items.length ? data.items.map(item => `
      <article class="gallery-item"><img src="${item.image_url}" alt="${escapeHTML(item.title)}" loading="lazy">
      <div class="gallery-item-copy"><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.description || "A community textile reuse project.")}</p><small>BY ${escapeHTML(item.creator)}</small></div></article>`).join("") : `<div class="loading-note">No projects shared yet. Be the first to add one.</div>`;
  } catch (err) { $("#galleryGrid").textContent = err.message; }
}
$("#galleryForm").addEventListener("submit", async e => {
  e.preventDefault(); const formElement = e.currentTarget;
  if (formElement.dataset.submitting === "true") return;
  formElement.dataset.submitting = "true";
  const button = $("button[type=submit]", formElement); setBusy(button, true, "Sharing…");
  try {
    const data = await api("/api/gallery", { method: "POST", body: new FormData(formElement) });
    formElement.reset(); await loadGallery(); toast(data.message);
  } catch (err) { if (err.message.toLowerCase().includes("log in")) openAuth("login"); else toast(err.message, true); }
  finally { setBusy(button, false); formElement.dataset.submitting = "false"; }
});

// Personal reuse tracker. The page opens with preview values; after a successful
// save, show the user's actual totals. Existing database records are never deleted.
function resetImpactPreview() {
  $("#totalKg").textContent = "0.00";
  $("#totalPieces").textContent = "0";
  $("#totalKgLabel").textContent = "kg reused · preview";
  $("#totalPiecesLabel").textContent = "pieces · preview";
  $("#impactMessage").textContent = "Preview starts at zero. Save a record to update your totals. Your previous records remain stored.";
}
async function loadImpact({ showTotals = false } = {}) {
  try {
    const data = await api("/api/sustainability/history");
    if (showTotals) {
      $("#totalKg").textContent = Number(data.total_kg || 0).toFixed(2);
      $("#totalPieces").textContent = String(data.total_pieces || 0);
      $("#totalKgLabel").textContent = "kg material reused";
      $("#totalPiecesLabel").textContent = "pieces repurposed";
      $("#impactMessage").textContent = data.notice;
    } else {
      resetImpactPreview();
    }
  } catch (err) {
    if (!err.message.toLowerCase().includes("log in")) $("#impactMessage").textContent = err.message;
  }
}
$("#impactForm").addEventListener("submit", async e => {
  e.preventDefault();
  const formElement = e.currentTarget;
  if (formElement.dataset.submitting === "true") return;
  formElement.dataset.submitting = "true";
  const button = $("button[type=submit]", formElement);
  setBusy(button, true, "Saving record…");
  const payload = Object.fromEntries(new FormData(formElement).entries());
  try {
    const data = await api("/api/sustainability", { method: "POST", body: JSON.stringify(payload) });
    formElement.reset();
    await loadImpact({ showTotals: true });
    toast(data.message || "Reuse record saved.");
  } catch (err) {
    if (err.message.toLowerCase().includes("log in")) openAuth("login");
    else toast(err.message, true);
  } finally {
    setBusy(button, false);
    formElement.dataset.submitting = "false";
  }
});

// Loom Bot: AI responses when configured, with a built-in textile knowledge fallback.
$("#botForm").addEventListener("submit", async e => {
  e.preventDefault(); const button = $("button[type=submit]", e.currentTarget); setBusy(button, true, "Thinking…");
  const question = new FormData(e.currentTarget).get("question");
  try {
    const data = await api("/api/loom-bot", { method: "POST", body: JSON.stringify({ question }) });
    const answer = $("#botAnswer");
    const modeLabel = data.mode === "ai" ? "AI ASSISTANT" : "TEXTILE KNOWLEDGE MODE";
    answer.innerHTML = `<span class="bot-mode">${escapeHTML(modeLabel)}</span><p>${escapeHTML(data.answer).replace(/\n/g, "<br>")}</p><small>${escapeHTML(data.notice || "")}</small>`;
    answer.classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
  finally { setBusy(button, false); }
});


$$('.product-ask').forEach(button => button.addEventListener('click', () => {
  const botInput = $('#botForm [name="question"]');
  if (!botInput) return;
  botInput.value = button.dataset.botQuestion || "Help me reuse textile scraps.";
  $('#loom-bot').scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
  window.setTimeout(() => botInput.focus(), reduceMotion ? 0 : 450);
  toast("Question added to Loom Bot. Press Ask to get suggestions.");
}));

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}
$("#year").textContent = new Date().getFullYear();
loadMe(); loadTutorials(); loadGallery();
