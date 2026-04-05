const API_URL = "https://agente.adianterecursos.com.br/extension/analyze";

document.getElementById("analyzeBtn").addEventListener("click", async () => {
  const btn = document.getElementById("analyzeBtn");
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  const slackUserId = document.getElementById("slackUserId").value.trim();

  btn.disabled = true;
  status.className = "status loading";
  status.textContent = "Capturando perfil da página...";
  result.style.display = "none";

  try {
    // Get the current tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab.url.includes("linkedin.com")) {
      status.className = "status error";
      status.textContent = "Esta página não é do LinkedIn. Abra um perfil do LinkedIn primeiro.";
      btn.disabled = false;
      return;
    }

    // Extract text content from the page
    const [{ result: pageText }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        // Get the main profile content
        const selectors = [
          ".pv-top-card",
          ".pv-about-section",
          ".experience-section",
          ".education-section",
          ".pv-skill-categories-section",
          '[class*="artdeco-card"]',
          "main",
        ];

        let text = "";
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) text += el.innerText + "\n\n";
        }

        // Fallback: get all main content
        if (!text.trim()) {
          const main = document.querySelector("main") || document.body;
          text = main.innerText;
        }

        // Clean up excessive whitespace
        return text.replace(/\n{3,}/g, "\n\n").trim().substring(0, 5000);
      },
    });

    if (!pageText || pageText.length < 50) {
      status.className = "status error";
      status.textContent = "Não consegui extrair texto do perfil. Tente rolar a página e clicar novamente.";
      btn.disabled = false;
      return;
    }

    status.textContent = "Enviando para análise... ⏳";

    // Send to our API
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_text: pageText,
        linkedin_url: tab.url,
        slack_user_id: slackUserId || null,
      }),
    });

    if (!response.ok) {
      throw new Error(`Erro ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    status.className = "status success";
    status.textContent = "Análise concluída! Resultado enviado ao Slack.";

    result.style.display = "block";
    result.textContent = data.analysis;

  } catch (err) {
    status.className = "status error";
    status.textContent = `Erro: ${err.message}`;
  }

  btn.disabled = false;
});

// Load saved Slack User ID
chrome.storage?.local?.get("slackUserId", (data) => {
  if (data?.slackUserId) {
    document.getElementById("slackUserId").value = data.slackUserId;
  }
});

// Save Slack User ID on change
document.getElementById("slackUserId").addEventListener("change", (e) => {
  chrome.storage?.local?.set({ slackUserId: e.target.value });
});
