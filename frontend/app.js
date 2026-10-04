const chatBox = document.getElementById("chat-box");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");


async function sendMessage() {
    const message = messageInput.value.trim();

    if (!message) {
        return;
    }

    // 1. Show user message in chat
    addMessage(message, "user");

    // Clear input
    messageInput.value = "";

    // 2. Show loading state
    setLoading(true);

    try {
        // 3. Send request to FastAPI
        const response = await fetch("/agent/chat", {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                message: message
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

        // 4. Read Agent response
        const data = await response.json();

        if (!data.response) {
            throw new Error("Agent returned an empty response.");
        }

        // 5. Display Agent response
        addMessage(data.response, "agent");

    } catch (error) {
        console.error("Error:", error);

        addMessage(
            `Sorry, something went wrong while contacting the AI Agent.\n\n${error.message}`,
            "agent"
        );

    } finally {
        // 6. Restore button
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
    contentDiv.textContent = text;


    messageDiv.appendChild(labelDiv);
    messageDiv.appendChild(contentDiv);

    chatBox.appendChild(messageDiv);

    scrollToBottom();
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
    chatBox.innerHTML = "";

    addMessage(
        "Ask me about a hospital's financial condition. " +
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