async function fetchCurrentUser() {
    const label = document.getElementById("userLabel");
    const badge = document.getElementById("userBadge");
    try {
        const res = await fetch("/api/me");
        if (!res.ok) {
            window.location.href = "/login.html";
            return;
        }
        const data = await res.json();
        const username = data.username || "User";
        label.textContent = username;
        badge.textContent = username.charAt(0).toUpperCase();
    } catch (err) {
        window.location.href = "/login.html";
    }
}

async function logout() {
    try {
        await fetch("/api/logout", { method: "POST" });
    } catch (err) {
        // Ignore network errors on logout.
    }
    window.location.href = "/login.html";
}

function bindActions() {
    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", logout);
    }

    const sendBtn = document.getElementById("sendBtn");
    const input = document.getElementById("messageInput");
    const chatBody = document.getElementById("chatBody");

    if (!sendBtn || !input || !chatBody) {
        return;
    }

    sendBtn.addEventListener("click", () => {
        const text = input.value.trim();
        if (!text) {
            return;
        }

        const msg = document.createElement("div");
        msg.className = "msg me";
        msg.innerHTML = "<div class=\"msg-author\">You</div><div class=\"msg-text\"></div>";
        msg.querySelector(".msg-text").textContent = text;

        chatBody.appendChild(msg);
        chatBody.scrollTop = chatBody.scrollHeight;
        input.value = "";
    });
}

fetchCurrentUser();
bindActions();
