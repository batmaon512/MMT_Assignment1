/**
 * AsynapRous Chat — index.js
 * Hybrid P2P Chat Client
 *
 * Architecture (Task 2.3):
 *   Initialization phase  : Client-Server (Tracker) for peer registration & discovery
 *   Chat phase            : Peer-to-Peer (direct TCP via /send-peer)
 *   Non-blocking backend  : asyncio coroutine (Python)
 *   Auth                  : RFC 2617 Basic Auth + RFC 6265 Cookies
 */

"use strict";

/* ──────────────────────────────
   State
────────────────────────────── */
let currentName = null;
let currentChannel = null;
const selectedUsers = new Set();   // peers chosen for channel creation
const channelInfo = {};          // { channelId -> { id, name, members, host, messages } }

/* ──────────────────────────────
   DOM refs
────────────────────────────── */
const onlineListEl = document.getElementById("onlineList");
const onlineCountEl = document.getElementById("onlineCount");
const chatListEl = document.getElementById("chatList");
const channelCountEl = document.getElementById("channelCount");
const topUserEl = document.getElementById("topUser");
const composerEl = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const channelBtn = document.getElementById("channelBtn");
const clearSelBtn = document.getElementById("clearSelBtn");
const channelNameInput = document.getElementById("channelNameInput");
const createChannelPanel = document.getElementById("createChannelPanel");
const selectedCountEl = document.getElementById("selectedCount");
const channelTitleEl = document.getElementById("channelTitle");
const channelMembersEl = document.getElementById("channelMembers");
const conversationEl = document.getElementById("conversation");
const emptyStateEl = document.getElementById("emptyState");
const connectionStatusEl = document.getElementById("connectionStatus");

/* ──────────────────────────────
   Helpers
────────────────────────────── */
function getCookie(name) {
    const val = `; ${document.cookie}`;
    const parts = val.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
}

function pushNotify(message, timeout = 3000, isError = false) {
    const note = document.createElement("div");
    note.className = "notify" + (isError ? " error" : "");
    note.textContent = message;
    document.getElementById("notifyBox").appendChild(note);
    setTimeout(() => {
        note.classList.add("hide");
        setTimeout(() => note.remove(), 400);
    }, timeout);
}

function formatTime(ts) {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ──────────────────────────────
   Session Initialization
   (Task 2.2 – Cookie-based auth)
────────────────────────────── */
function initializeUserSession() {
    const loggedInUser = getCookie("account");
    if (loggedInUser) {
        currentName = loggedInUser;
        topUserEl.textContent = currentName;
        sendBtn.disabled = false;
        pushNotify(`Welcome, ${currentName}!`, 3000);
        // Phase 1: Register with Tracker
        registerPeer();
    } else {
        topUserEl.textContent = "Guest";
        window.location.href = "/login.html";
    }
}

/* ──────────────────────────────
   Phase 1: Initialization
   (Client-Server — Tracker)
────────────────────────────── */

/**
 * Peer registration: submit IP & port to the centralized Tracker.
 * The backend uses own_port (server-side) for the actual P2P port.
 */
async function registerPeer() {
    if (!currentName) return;
    try {
        const res = await fetch("/submit-info", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: currentName,
                ip: window.location.hostname,
                port: parseInt(window.location.port) || 8001
            })
        });
        const data = await res.json();
        if (data.code === 1) {
            console.log("[Peer] Registered with tracker");
        } else {
            console.warn("[Peer] Registration issue:", data);
        }
    } catch (err) {
        console.error("[Peer] Registration error:", err);
    }
}

/**
 * Peer discovery: poll /online to get active peers & update online list UI.
 * Also updates tracker status indicator.
 */
async function updateOnlineList() {
    if (!currentName) return;
    try {
        const res = await fetch("/online", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: currentName })
        });
        const data = await res.json();

        // Update tracker status
        const dot = connectionStatusEl.querySelector(".dot");
        if (data.code === 1) {
            dot.className = "dot online";
        } else {
            dot.className = "dot offline";
        }

        const onlineNames = (data.code === 1 && Array.isArray(data.online))
            ? data.online.filter(n => n !== currentName)
            : [];

        onlineCountEl.textContent = onlineNames.length;
        renderOnlineList(onlineNames);
    } catch {
        connectionStatusEl.querySelector(".dot").className = "dot offline";
    }
}

/**
 * Render the online peer list in the sidebar.
 * Click to select/deselect for channel creation.
 */
function renderOnlineList(names) {
    onlineListEl.innerHTML = "";

    if (names.length === 0) {
        const msg = document.createElement("div");
        msg.style.cssText = "padding:12px 8px;font-size:13px;color:#94a3b8;text-align:center;";
        msg.textContent = "No other peers online";
        onlineListEl.appendChild(msg);
        return;
    }

    names.forEach(fullName => {
        const box = document.createElement("div");
        box.className = "online-box" + (selectedUsers.has(fullName) ? " selected" : "");
        box.dataset.username = fullName;

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = fullName.charAt(0).toUpperCase();

        const nameDiv = document.createElement("div");
        nameDiv.className = "user-name";
        nameDiv.textContent = fullName;

        const check = document.createElement("span");
        check.className = "check-icon";
        check.textContent = "✓";

        box.appendChild(avatar);
        box.appendChild(nameDiv);
        box.appendChild(check);

        box.addEventListener("click", () => togglePeerSelection(fullName, box));
        onlineListEl.appendChild(box);
    });
}

/**
 * Connection setup: toggle peer selection; on first select, call /connect-peer
 * to fetch & cache the peer's IP:Port locally (P2P cache).
 */
function togglePeerSelection(fullName, box) {
    if (selectedUsers.has(fullName)) {
        selectedUsers.delete(fullName);
        box.classList.remove("selected");
    } else {
        selectedUsers.add(fullName);
        box.classList.add("selected");
        // Pre-connect: cache the peer's address for direct P2P
        fetch("/connect-peer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target: fullName })
        }).then(r => r.json()).then(data => {
            if (data.code === 1) {
                console.log(`[P2P] Connected to ${fullName}:`, data.peer);
            } else {
                pushNotify(`Could not resolve ${fullName}`, 2500, true);
            }
        }).catch(e => console.error("[P2P] connect-peer error:", e));
    }
    updateSelectionUI();
}

function updateSelectionUI() {
    const count = selectedUsers.size;
    selectedCountEl.textContent = count;
    if (count > 0) {
        createChannelPanel.classList.remove("hidden");
    } else {
        createChannelPanel.classList.add("hidden");
    }
}

/* ──────────────────────────────
   Channel Management
────────────────────────────── */

/**
 * Create a new channel with selected peers.
 * The channel is broadcast to all members via /send-peer.
 */
function createChannel() {
    if (selectedUsers.size === 0) {
        pushNotify("Select at least one peer first.", 2000, true);
        return;
    }

    const members = [currentName, ...Array.from(selectedUsers)];
    const customName = channelNameInput.value.trim();
    const channelName = customName || members.join(", ");
    const channelId = "ch_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7);

    channelInfo[channelId] = {
        id: channelId,
        name: channelName,
        members: members,
        host: currentName,
        messages: {}
    };

    // Clear selection state
    selectedUsers.clear();
    channelNameInput.value = "";
    createChannelPanel.classList.add("hidden");
    document.querySelectorAll(".online-box.selected")
        .forEach(b => b.classList.remove("selected"));

    renderChannelItem(channelId);
    selectChannel(channelId);
    pushNotify(`Channel "${channelName}" created.`, 2000);

    // Announce new channel to all members immediately
    syncChannelToPeers(channelId);
}

/**
 * Render (or update) a channel item in the Channels sidebar.
 */
function renderChannelItem(id) {
    const ch = channelInfo[id];
    if (!ch) return;

    let item = chatListEl.querySelector(`.chat-item[data-chat-id="${id}"]`);
    if (!item) {
        item = document.createElement("div");
        item.className = "chat-item";
        item.dataset.chatId = id;

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = ch.name.charAt(0).toUpperCase();
        item.appendChild(avatar);

        const meta = document.createElement("div");
        meta.className = "meta";

        const nameDiv = document.createElement("div");
        nameDiv.className = "name";
        meta.appendChild(nameDiv);

        const snippetDiv = document.createElement("div");
        snippetDiv.className = "snippet";
        meta.appendChild(snippetDiv);

        item.appendChild(meta);

        const timeDiv = document.createElement("div");
        timeDiv.className = "time";
        item.appendChild(timeDiv);

        item.addEventListener("click", () => selectChannel(id));
        chatListEl.appendChild(item);
    }

    // Update content
    const msgs = Object.values(ch.messages || {});
    const last = msgs.sort((a, b) => a.time - b.time).pop();

    item.querySelector(".name").textContent =
        ch.name.length > 22 ? ch.name.slice(0, 22) + "…" : ch.name;
    item.querySelector(".snippet").textContent =
        last ? `${last.from}: ${last.content.slice(0, 28)}${last.content.length > 28 ? "…" : ""}` : "No messages yet";
    item.querySelector(".time").textContent = last ? formatTime(last.time) : "";
    item.classList.toggle("active", currentChannel === id);

    // Update channel count badge
    channelCountEl.textContent = Object.keys(channelInfo).length;
}

function selectChannel(id) {
    currentChannel = id;
    const ch = channelInfo[id];
    if (!ch) return;

    channelTitleEl.textContent = ch.name;
    channelMembersEl.textContent = ch.members.join(" · ");

    chatListEl.querySelectorAll(".chat-item").forEach(el => {
        el.classList.toggle("active", el.dataset.chatId === id);
    });

    loadMessages(id);
}

/* ──────────────────────────────
   Phase 2: P2P Chat
────────────────────────────── */

/**
 * Send a message to the current channel.
 * Saves locally and sends to each member via /send-peer (direct P2P TCP).
 */
async function sendMessage() {
    if (!currentChannel) {
        pushNotify("Please select a channel first.", 2000, true);
        return;
    }
    const text = composerEl.value.trim();
    if (!text) return;

    composerEl.value = "";
    autoResizeTextarea();

    const ch = channelInfo[currentChannel];
    if (!ch) return;

    const msgId = Date.now() + "_" + Math.random().toString(36).slice(2, 6);
    const nmsg = { from: currentName, content: text, time: Date.now() };
    ch.messages[msgId] = nmsg;

    loadMessages(currentChannel);
    renderChannelItem(currentChannel);

    // Build P2P payload (channel_message protocol)
    const payload = {
        type: "channel_message",
        id: currentChannel,
        content: channelInfo[currentChannel],
        nmsg: nmsg,
        from: currentName
    };

    // Broadcast connection: send to every channel member (P2P, no Tracker)
    const targets = ch.members.filter(m => m !== currentName);
    await Promise.allSettled(targets.map(memberName =>
        fetch("/send-peer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ from: currentName, to: memberName, message: payload })
        }).catch(e => console.error("[P2P] send error to", memberName, e))
    ));
}

/**
 * Incoming message handler — called for each polled message.
 * Processes channel_message protocol packets.
 */
function handleData(dataObj) {
    if (!dataObj || !dataObj.type) return;

    switch (dataObj.type) {
        case "channel_message": {
            const incoming = dataObj.content;
            const id = dataObj.id;
            if (!incoming || !id) break;

            if (!channelInfo[id]) {
                // New channel received from peer → join it
                channelInfo[id] = incoming;
                renderChannelItem(id);
                pushNotify(`You were added to "${incoming.name}"`);
                break;
            }

            // Merge messages (immutable — no edit/delete)
            const local = channelInfo[id];
            channelInfo[id] = {
                ...local,
                ...incoming,
                messages: {
                    ...local.messages,
                    ...(incoming.messages || {})
                }
            };

            // Notification for new message
            if (dataObj.nmsg && dataObj.nmsg.from !== currentName) {
                const isActiveChannel = (currentChannel === id);
                if (!isActiveChannel) {
                    pushNotify(`${dataObj.nmsg.from} → ${channelInfo[id].name}: ${dataObj.nmsg.content.slice(0, 50)}`);
                }
            }

            renderChannelItem(id);
            if (currentChannel === id) loadMessages(id);
            break;
        }
        case "notify":
            pushNotify(dataObj.content, 3000);
            break;
        default:
            console.log("[handleData] unknown type:", dataObj.type, dataObj);
    }
}

/**
 * Poll /poll-messages from the backend (messages received via P2P TCP).
 * Runs every second — non-blocking (async JS fetch).
 */
async function pollMessages() {
    if (!currentName) return;
    try {
        const res = await fetch("/poll-messages", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const data = await res.json();
        if (data.code === 1 && Array.isArray(data.messages)) {
            for (const msg of data.messages) {
                if (msg.message) handleData(msg.message);
            }
        }
    } catch { /* Ignore polling errors — offline is fine */ }
}

/**
 * Sync a channel's full state to all its members.
 * Used on channel creation or when a peer may have missed messages.
 */
async function syncChannelToPeers(chId) {
    const ch = channelInfo[chId];
    if (!ch || !ch.members) return;

    const payload = {
        type: "channel_message",
        id: chId,
        content: ch,
        from: currentName
    };

    const targets = ch.members.filter(m => m !== currentName);
    await Promise.allSettled(targets.map(memberName =>
        fetch("/send-peer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ from: currentName, to: memberName, message: payload })
        }).catch(e => console.error("[P2P] sync error:", memberName, e))
    ));
}

/* ──────────────────────────────
   Message Rendering
────────────────────────────── */
function loadMessages(chId) {
    const ch = channelInfo[chId];
    if (!ch) return;

    const msgs = Object.values(ch.messages || {})
        .sort((a, b) => a.time - b.time);

    const isAtBottom = conversationEl.scrollHeight - conversationEl.scrollTop
        <= conversationEl.clientHeight + 60;

    conversationEl.innerHTML = "";
    emptyStateEl && emptyStateEl.remove();

    if (msgs.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "margin:auto;text-align:center;color:#94a3b8;font-size:14px;";
        empty.textContent = "No messages yet. Say hello! 👋";
        conversationEl.appendChild(empty);
        return;
    }

    let lastDate = null;
    msgs.forEach(msg => {
        const msgDate = new Date(msg.time).toLocaleDateString();
        if (msgDate !== lastDate) {
            const sep = document.createElement("div");
            sep.style.cssText = "text-align:center;font-size:11px;color:#94a3b8;margin:8px 0;";
            sep.textContent = msgDate;
            conversationEl.appendChild(sep);
            lastDate = msgDate;
        }

        const isMe = msg.from === currentName;
        const wrapper = document.createElement("div");
        wrapper.className = "msg-wrapper " + (isMe ? "me" : "other");

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = msg.from.charAt(0).toUpperCase();
        avatar.title = msg.from;

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        if (!isMe) {
            const senderEl = document.createElement("div");
            senderEl.className = "sender-name";
            senderEl.textContent = msg.from;
            bubble.appendChild(senderEl);
        }

        const textEl = document.createElement("div");
        textEl.className = "bubble-text";
        textEl.textContent = msg.content; // safe text (no innerHTML)
        bubble.appendChild(textEl);

        const timeEl = document.createElement("div");
        timeEl.className = "bubble-time";
        timeEl.textContent = formatTime(msg.time);
        bubble.appendChild(timeEl);

        wrapper.appendChild(avatar);
        wrapper.appendChild(bubble);
        conversationEl.appendChild(wrapper);
    });

    if (isAtBottom) conversationEl.scrollTop = conversationEl.scrollHeight;
}

/* ──────────────────────────────
   Logout
────────────────────────────── */
async function logout() {
    try {
        await fetch("/api/logout", { method: "POST" });
    } catch { }
    window.location.href = "/login.html";
}

/* ──────────────────────────────
   Textarea auto-resize
────────────────────────────── */
function autoResizeTextarea() {
    composerEl.style.height = "auto";
    composerEl.style.height = Math.min(composerEl.scrollHeight, 140) + "px";
}

/* ──────────────────────────────
   Event Listeners
────────────────────────────── */
sendBtn.addEventListener("click", sendMessage);

composerEl.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

composerEl.addEventListener("input", autoResizeTextarea);

channelBtn.addEventListener("click", createChannel);

clearSelBtn.addEventListener("click", () => {
    selectedUsers.clear();
    document.querySelectorAll(".online-box.selected")
        .forEach(b => b.classList.remove("selected"));
    createChannelPanel.classList.add("hidden");
});

document.getElementById("logoutBtn").addEventListener("click", logout);

/* ──────────────────────────────
   Periodic Tasks
────────────────────────────── */

// Peer discovery: poll online list every 2 seconds
setInterval(updateOnlineList, 2000);

// Poll incoming P2P messages every 1 second
setInterval(pollMessages, 1000);

// Sync channels to peers every 5 seconds (keep members in sync)
setInterval(() => {
    Object.keys(channelInfo).forEach(syncChannelToPeers);
}, 5000);

/* ──────────────────────────────
   Bootstrap
────────────────────────────── */
initializeUserSession();
sendBtn.disabled = true;
