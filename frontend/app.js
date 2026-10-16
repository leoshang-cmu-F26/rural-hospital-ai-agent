let chatHistory = [];
let currentFacility = null;
let comparisonFacilities = [];
const MAX_HISTORY_MESSAGES = 6;
const MAX_HISTORY_CHARS = 2000;

const chatBox = document.getElementById("chat-box");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");


async function sendMessage() {
    const message = messageInput.value.trim();

    if (!message || sendButton.disabled) {
        return;
    }

    let nextFacility = currentFacility;
    let nextComparison = comparisonFacilities;
    const evidence = new Map();
    // 1. Show user message in chat
    addMessage(message, "user");

    // Clear input
    messageInput.value = "";

    // 2. Show loading state
    setLoading(true);
    startProgress();

    try {
        // 3. Send request to FastAPI
        const response = await fetch("/agent/chat/stream", {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                message: message,
                history: chatHistory,
                current_facility: currentFacility,
                comparison_facilities: comparisonFacilities
            })
        });

        // If backend returns error status
        if (!response.ok) {
            let errorMessage = "Agent request failed.";

            try {
                const errorData = await response.json();

                if (errorData.detail) {
                    errorMessage = errorData.detail;
                }
            } catch {
                // Keep default error message
            }

            throw new Error(errorMessage);
        }

        if (!response.body) throw new Error("Streaming is unavailable.");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let completed = false;
        function consume(line) {
            if (!line.trim()) return;
            const event = JSON.parse(line);
            if (event.type === "evidence") {
                for (const section of event.sections || []) evidence.set(section.key, section);
            }
            if (event.type === "context") { nextFacility = event.current_facility; nextComparison = []; }
            if (event.type === "comparison_context") {
                nextComparison = (event.comparison_facilities || []).slice(0, 2);
                nextFacility = null;
            }
            if (event.type === "progress") updateProgress(event.message);
            if (event.type === "error") throw new Error(event.message);
            if (event.type === "result") {
                if (completed) return;
                completed = true;
                currentFacility = nextFacility;
                comparisonFacilities = nextComparison;
                chatHistory.push(
                    { role: "user", content: compactHistory(message) },
                    { role: "assistant", content: compactHistory(event.response) }
                );
                chatHistory = chatHistory.slice(-MAX_HISTORY_MESSAGES);
                stopProgress();
                const reply = addMessage(event.response, "agent");
                renderEvidence(reply, Array.from(evidence.values()));
                updateCurrentFacility();
            }
        }
        try {
            while (true) {
                const { value, done } = await reader.read();
                buffer += decoder.decode(value, { stream: !done });
                const lines = buffer.split("\n");
                buffer = lines.pop();
                lines.forEach(consume);
                if (done) break;
            }
            if (buffer.trim()) consume(buffer);
            if (!completed) throw new Error("Connection ended before the answer was received.");
        } finally {
            await reader.cancel().catch(() => {});
            reader.releaseLock();
        }

    } catch (error) {
        console.error("Error:", error);

        addMessage(
            `Sorry, something went wrong while contacting the AI Agent.\n\n${error.message}`,
            "agent"
        );

    } finally {
        // 6. Restore button
        stopProgress();
        setLoading(false);

        // Put cursor back in textarea
        messageInput.focus();
    }
}


function addMessage(text, type) {
    const messageDiv = document.createElement("div");

    messageDiv.classList.add(
        "message",
        type === "user"
            ? "user-message"
            : "agent-message"
    );


    const labelDiv = document.createElement("div");

    labelDiv.classList.add("message-label");

    labelDiv.textContent =
        type === "user"
            ? "You"
            : "AI Agent";


    const contentDiv = document.createElement("div");

    contentDiv.classList.add("message-content");

    // For now, display Agent text safely as plain text.
    // white-space: pre-wrap in CSS preserves line breaks.
    if (type === "agent" && typeof renderMarkdown === "function") {
        contentDiv.classList.add("markdown-content");
        renderMarkdown(text, contentDiv);
    } else {
        contentDiv.textContent = text;
    }


    messageDiv.appendChild(labelDiv);
    messageDiv.appendChild(contentDiv);

    chatBox.appendChild(messageDiv);

    scrollToBottom();
    return messageDiv;
}


function setLoading(isLoading) {
    sendButton.disabled = isLoading;
    messageInput.disabled = isLoading;

    if (isLoading) {
        sendButton.textContent = "Thinking...";
    } else {
        sendButton.textContent = "Send";
    }
}


function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}


function useExample(text) {
    if (sendButton.disabled) {
        return;
    }

    messageInput.value = text;
    messageInput.focus();
}


function clearChat() {
    if (sendButton.disabled) return;
    chatHistory = [];
    currentFacility = null;
    comparisonFacilities = [];
    updateCurrentFacility();
    chatBox.innerHTML = "";

    addMessage(
        "Ask about a hospital by name, state, or county. " +
        "You can use either a hospital name or a CMS CCN.",
        "agent"
    );

    messageInput.focus();
}


// Press Enter to send.
// Shift + Enter creates a new line.
messageInput.addEventListener("keydown", function (event) {
    if (
        event.key === "Enter" &&
        !event.shiftKey
    ) {
        event.preventDefault();
        sendMessage();
    }
});


// Focus input when page loads
window.addEventListener("DOMContentLoaded", function () {
    messageInput.focus();
});

let progressNode = null;
let progressTimer = null;
let progressStarted = 0;
let progressMessage = "";

function startProgress() {
    stopProgress();
    progressStarted = Date.now();
    progressNode = document.createElement("div");
    progressNode.className = "agent-progress";
    progressNode.setAttribute("role", "status");
    progressNode.setAttribute("aria-live", "polite");
    const stage = document.createElement("div");
    stage.className = "progress-stage";
    const elapsed = document.createElement("small");
    elapsed.className = "progress-elapsed";
    elapsed.setAttribute("aria-hidden", "true");
    progressNode.append(stage, elapsed);
    chatBox.appendChild(progressNode);
    chatBox.setAttribute("aria-busy", "true");
    updateProgress("Connecting to the agent…");
    progressTimer = setInterval(() => {
        if (!progressNode) return;
        const seconds = Math.floor((Date.now() - progressStarted) / 1000);
        elapsed.textContent = `${seconds}s elapsed` +
            (seconds >= 30 ? " · Data sources may take a little longer. Please keep this page open." : "");
    }, 1000);
}

function updateProgress(message) {
    if (!progressNode) return;
    progressMessage = message;
    progressNode.querySelector(".progress-stage").textContent = message;
    scrollToBottom();
}

function stopProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    if (progressNode) progressNode.remove();
    progressNode = null;
    chatBox.setAttribute("aria-busy", "false");
}


function compactHistory(text) {
    if (text.length <= MAX_HISTORY_CHARS) return text;
    return text.slice(0, MAX_HISTORY_CHARS - 20) + "\n[Earlier text cut]";
}


function updateCurrentFacility() {
    const card = document.getElementById("current-facility");
    if (!card) return;
    if (comparisonFacilities.length === 2) {
        card.hidden = false;
        card.textContent = "Comparing: " + comparisonFacilities.map(
            f => `${f.facility_name} (CCN ${f.facility_id})`).join(" ↔ ");
        return;
    }
    card.hidden = !currentFacility;
    if (!currentFacility) { card.textContent = ""; return; }
    const parts = [currentFacility.facility_name];
    if (currentFacility.facility_id) parts.push(`CCN ${currentFacility.facility_id}`);
    if (currentFacility.city) parts.push(currentFacility.city);
    if (currentFacility.state) parts.push(currentFacility.state);
    card.textContent = "Current facility: " + parts.join(" · ");
}

function renderEvidence(reply, sections) {
    if (!sections.length) return;
    const panel = document.createElement("details"); panel.className = "evidence-panel";
    const summary = document.createElement("summary");
    const gaps = sections.filter(s => s.status !== "available").length;
    summary.textContent = "Data sources & coverage" + (gaps ? ` · ${gaps} section(s) with gaps` : "");
    panel.appendChild(summary);
    panel.open = gaps > 0;
    for (const section of sections) {
        const item = document.createElement("div"); item.className = "evidence-item";
        const title = document.createElement("strong"); title.textContent = section.label;
        const badge = document.createElement("span");
        const status = ["available", "partial", "unavailable"].includes(section.status) ? section.status : "unavailable";
        badge.className = "evidence-badge " + status;
        badge.textContent = {available:"Available",partial:"Partial data",unavailable:"Unavailable"}[status];
        const source = document.createElement("div"); source.textContent = "Source: " + section.source;
        item.append(title, badge, source);
        if (section.period) {
            const period = document.createElement("div"); period.textContent = "Report year(s): " + section.period; item.appendChild(period);
        }
        if (section.fiscal_period) {
            const fiscal = document.createElement("div"); fiscal.textContent = "Fiscal period: " + section.fiscal_period; item.appendChild(fiscal);
        }
        if (section.details) {
            const detail = document.createElement("div"); detail.className = "evidence-detail";
            detail.textContent = section.details; item.appendChild(detail);
        }
        panel.appendChild(item);
    }
    reply.appendChild(panel);
    scrollToBottom();
}
