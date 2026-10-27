// Browser-owned conversation state: only compact identities and recent text.
// Progress frames, evidence cards and full tool payloads are never replayed.
let chatHistory = [];
let currentFacility = null;
let comparisonFacilities = [];
const MAX_HISTORY_MESSAGES = 6;
const MAX_HISTORY_CHARS = 2000;

// Bind UI controls once; every request owns its temporary progress/evidence.
const chatBox = document.getElementById("chat-box");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");


// Send one request, consume ordered stream frames, and commit context on success.
async function sendMessage() {
    const message = messageInput.value.trim();

    if (!message || sendButton.disabled) {
        return;
    }

    // Stage identity updates until a final answer arrives; failed requests do not commit them.
    let nextFacility = currentFacility;
    let nextComparison = comparisonFacilities;
    const evidence = new Map();
    const warnings = new Map();
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

        // Read newline-delimited events across arbitrary network chunk boundaries.
        if (!response.body) {
            throw new Error("Streaming is unavailable.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let completed = false;
        function consume(line) {
            if (!line.trim()) {
                return;
            }
            const event = JSON.parse(line);
            if (event.type === "evidence") {
                for (const section of event.sections || []) {
                    evidence.set(section.key, section);
                }
            }
            if (event.type === "warnings") {
                for (const warning of event.warnings || []) {
                    const key = [warning.facility_id, warning.facility_name, warning.code, warning.metric, warning.report_year].join(":");
                    warnings.set(key, warning);
                }
            }
            // A selected single facility and a comparison pair are mutually exclusive.
            if (event.type === "context") {
                nextFacility = event.current_facility;
                nextComparison = [];
            }
            if (event.type === "comparison_context") {
                nextComparison = (event.comparison_facilities || []).slice(0, 2);
                nextFacility = null;
            }
            if (event.type === "progress") {
                updateProgress(event.message);
            }
            if (event.type === "error") {
                throw new Error(event.message);
            }
            if (event.type === "result") {
                if (completed) {
                    return;
                }
                // Store only successful dialogue; cap both history count and message size.
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
                renderWarnings(reply, Array.from(warnings.values()));
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
                for (const line of lines) {
                    consume(line);
                }
                if (done) {
                    break;
                }
            }
            if (buffer.trim()) {
                consume(buffer);
            }
            if (!completed) {
                throw new Error("Connection ended before the answer was received.");
            }
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
        // Always remove the pending indicator and restore input, including on errors.
        stopProgress();
        setLoading(false);

        // Put cursor back in textarea
        messageInput.focus();
    }
}


// Render user text literally and agent Markdown through the safe DOM renderer.
function addMessage(text, type) {
    const messageDiv = document.createElement("div");

    messageDiv.classList.add("message");
    if (type === "user") {
        messageDiv.classList.add("user-message");
    } else {
        messageDiv.classList.add("agent-message");
    }


    const labelDiv = document.createElement("div");

    labelDiv.classList.add("message-label");

    if (type === "user") {
        labelDiv.textContent = "You";
    } else {
        labelDiv.textContent = "AI Agent";
    }


    const contentDiv = document.createElement("div");

    contentDiv.classList.add("message-content");

    // Markdown uses explicit DOM nodes; untrusted HTML is never interpolated.
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


// Reset rendered dialogue and both identity modes together, never mid-request.
function clearChat() {
    if (sendButton.disabled) {
        return;
    }
    chatHistory = [];
    currentFacility = null;
    comparisonFacilities = [];
    updateCurrentFacility();
    chatBox.innerHTML = "";

    addMessage(
        "Ask about a hospital by name, state and county, or use its CMS CCN. " +
        "Request a full investigation or focus on finances, trends or healthcare access.",
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

// Progress lifecycle: one visible stage and elapsed timer per pending request.
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
        if (!progressNode) {
            return;
        }
        const seconds = Math.floor((Date.now() - progressStarted) / 1000);
        elapsed.textContent = `${seconds}s elapsed`;
        if (seconds >= 30) {
            elapsed.textContent += " · Data sources may take a little longer. Please keep this page open.";
        }
    }, 1000);
}

function updateProgress(message) {
    if (!progressNode) {
        return;
    }
    progressMessage = message;
    progressNode.querySelector(".progress-stage").textContent = message;
    scrollToBottom();
}

function stopProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    if (progressNode) {
        progressNode.remove();
    }
    progressNode = null;
    chatBox.setAttribute("aria-busy", "false");
}


// Apply a per-message size cap in addition to the recent-message count limit.
function compactHistory(text) {
    if (text.length <= MAX_HISTORY_CHARS) {
        return text;
    }
    return text.slice(0, MAX_HISTORY_CHARS - 20) + "\n[Earlier text cut]";
}


// Display the active comparison pair or single facility from successful tool results.
function updateCurrentFacility() {
    const card = document.getElementById("current-facility");
    if (!card) {
        return;
    }
    if (comparisonFacilities.length === 2) {
        card.hidden = false;
        const labels = [];
        for (const facility of comparisonFacilities) {
            labels.push(`${facility.facility_name} (CCN ${facility.facility_id})`);
        }
        card.textContent = "Comparing: " + labels.join(" ↔ ");
        return;
    }
    card.hidden = !currentFacility;
    if (!currentFacility) {
        card.textContent = "";
        return;
    }
    const parts = [currentFacility.facility_name];
    if (currentFacility.facility_id) {
        parts.push(`CCN ${currentFacility.facility_id}`);
    }
    if (currentFacility.city) {
        parts.push(currentFacility.city);
    }
    if (currentFacility.state) {
        parts.push(currentFacility.state);
    }
    card.textContent = "Current facility: " + parts.join(" · ");
}

// Evidence cards come from structured tool metadata, not generated prose.
function renderEvidence(reply, sections) {
    if (!sections.length) {
        return;
    }

    // 1. Open coverage details automatically when at least one section has gaps.
    const panel = document.createElement("details");
    panel.className = "evidence-panel";
    const summary = document.createElement("summary");
    let gaps = 0;
    for (const section of sections) {
        if (section.status !== "available") {
            gaps++;
        }
    }
    summary.textContent = "Data sources & coverage";
    if (gaps) {
        summary.textContent += ` · ${gaps} section(s) with gaps`;
    }
    panel.appendChild(summary);
    panel.open = gaps > 0;

    // 2. Render each source independently; missing evidence is not a zero finding.
    for (const section of sections) {
        const item = document.createElement("div");
        item.className = "evidence-item";
        const title = document.createElement("strong");
        title.textContent = section.label;

        let status = "unavailable";
        if (["available", "partial", "unavailable"].includes(section.status)) {
            status = section.status;
        }
        const labels = {
            available: "Available",
            partial: "Partial data",
            unavailable: "Unavailable",
        };
        const badge = document.createElement("span");
        badge.className = "evidence-badge " + status;
        badge.textContent = labels[status];

        const source = document.createElement("div");
        source.textContent = "Source: " + section.source;
        item.append(title, badge, source);

        // Dataset years and fiscal periods stay separate to avoid false alignment.
        if (section.period) {
            const period = document.createElement("div");
            period.textContent = "Report year(s): " + section.period;
            item.appendChild(period);
        }
        if (section.fiscal_period) {
            const fiscal = document.createElement("div");
            fiscal.textContent = "Fiscal period: " + section.fiscal_period;
            item.appendChild(fiscal);
        }
        if (section.details) {
            const detail = document.createElement("div");
            detail.className = "evidence-detail";
            detail.textContent = section.details;
            item.appendChild(detail);
        }
        panel.appendChild(item);
    }

    // 3. Attach coverage to its own answer; never add these cards to chatHistory.
    reply.appendChild(panel);
    scrollToBottom();
}


// Data-quality notices stay visible outside the collapsible source details.
function renderWarnings(message, warnings) {
    if (!warnings.length) {
        return;
    }
    const panel = document.createElement("section");
    panel.className = "quality-notices";
    panel.setAttribute("aria-label", "Data quality and interpretation notices");
    const title = document.createElement("h3");
    title.textContent = "Before interpreting these results";
    panel.appendChild(title);
    const list = document.createElement("ul");
    for (const warning of warnings) {
        const item = document.createElement("li");
        item.className = "quality-notice";
        if (warning.severity === "info") {
            item.classList.add("quality-info");
        }
        const text = document.createElement("strong");
        let label = "";
        if (warning.facility_name) {
            label = warning.facility_name + ": ";
        }
        text.textContent = label + warning.message;
        item.appendChild(text);
        if (warning.action) {
            const action = document.createElement("p");
            action.textContent = warning.action;
            item.appendChild(action);
        }
        list.appendChild(item);
    }
    panel.appendChild(list);
    message.insertBefore(panel, message.querySelector(".message-content"));
}
