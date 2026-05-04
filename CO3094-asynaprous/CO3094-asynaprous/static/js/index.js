document.getElementById("logoutBtn").addEventListener("click", logout);
document.getElementById("channelBtn").addEventListener("click", createChannel);
document.getElementById("sendAllBtn").addEventListener("click", sendAllMessages);

const composerInput = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const onlineListEl = document.getElementById("onlineList");
const chatList = document.getElementById("chatList");
const topUserEl = document.getElementById("topUser");

sendBtn.addEventListener("click", sendMessage);
composerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

let currentName = null;
let currentChannel = null;
const selectedUsers = new Set();
const channelInfo = {};
let peerRegistry = [];

// --- INIT SESSION FROM COOKIE ---
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(';').shift();
    }
    return null;
}

function updateUserLabels(name) {
    if (topUserEl) {
        topUserEl.textContent = `Signed in as: ${name}`;
    }
}

function initializeUserSession() {
    const loggedInUser = getCookie('account');

    if (loggedInUser) {
        currentName = loggedInUser;
        updateUserLabels(currentName);
        pushNotify(`Welcome back, ${currentName}!`, 3000);
        registerPeer();
        refreshPeerList();
    } else if (topUserEl) {
        topUserEl.textContent = "Signed in as: Guest";
    }
}

async function registerPeer() {
    if (!currentName) return;
    const payload = {
        name: currentName,
        ip: window.location.hostname,
        // port is the Python server's own port, let the server fill it in via own_port
        // We still send it so the tracker knows which port to use for P2P
        port: window.location.port || 8001
    };
    try {
        const res = await fetch("/submit-info", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        console.log("[Peer] Registered:", data);
    } catch (err) {
        console.error("[Peer] Registration error:", err);
    }
}

async function refreshPeerList() {
    if (!currentName) return;
    try {
        const res = await fetch("/get-list", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (data.code === 1 && Array.isArray(data.peers)) {
            peerRegistry = data.peers;
        }
    } catch (err) {
        // Ignore discovery errors.
    }
}

initializeUserSession();

async function sendAllMessages() {
    const channelIDs = Object.keys(channelInfo);
    if (channelIDs.length === 0) {
        pushNotify("No channels to send yet.", 2500);
        return;
    }

    const text = composerInput.value.trim();
    if (!text) return;
    composerInput.value = "";

    const nmsg = {
        from: currentName,
        content: text,
        time: Date.now()
    };

    for (const chID of channelIDs) {
        const ch = channelInfo[chID];
        if (!ch) continue;

        const msgId = Date.now().toString() + "_" + Math.floor(Math.random() * 1000);
        ch.messages[msgId] = nmsg;

        updateChannel(chID);

        const payload = {
            from: currentName,
            message: {
                type: "channel_message",
                id: chID,
                content: channelInfo[chID],
                nmsg: nmsg,
                from: currentName
            }
        };

        try {
            await fetch("/broadcast-peer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } catch (e) {
            console.error("Broadcast error", e);
        }
    }

    if (currentChannel) loadMessages(currentChannel);
}

async function sendMessage() {
    if (!currentChannel) {
        pushNotify("Select a channel first.", 2000);
        return;
    }

    const text = composerInput.value.trim();
    if (!text) return;

    composerInput.value = "";

    const ch = channelInfo[currentChannel];
    if (!ch) return;

    const nmsg = {
        from: currentName,
        content: text,
        time: Date.now()
    };

    const msgId = Date.now().toString() + "_" + Math.floor(Math.random() * 1000);
    ch.messages[msgId] = nmsg;

    loadMessages(currentChannel);
    updateChannel(currentChannel);

    const payloadTemplate = {
        type: "channel_message",
        id: currentChannel,
        content: channelInfo[currentChannel],
        nmsg: nmsg,
        from: currentName
    };

    channelInfo[currentChannel].members.forEach(memberName => {
        if (memberName === currentName) return;
        
        fetch("/send-peer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                from: currentName,
                to: memberName,
                message: payloadTemplate
            })
        }).catch(e => console.error("Send error to", memberName, e));
    });
}

function handleData(dataObj) {
    if (dataObj.type) {
        switch (dataObj.type) {
            case "notify":
                pushNotify(dataObj.content, 2500);
                break;
            case "channel_message":
                const incoming = dataObj.content;
                const id = dataObj.id;

                if (!incoming || !id) break;

                if ("nmsg" in dataObj) {
                    pushNotify(`${dataObj.nmsg.from}: ${dataObj.nmsg.content}`);
                }

                if (!channelInfo[id]) {
                    channelInfo[id] = incoming;
                    updateChannel(id);
                    break;
                }

                const local = channelInfo[id] || { messages: {} };
                const incomingMessages = incoming.messages || {};
                const localMessages = local.messages || {};

                const mergedMessages = {
                    ...localMessages,
                    ...incomingMessages
                };

                channelInfo[id] = {
                    ...local,
                    ...incoming,
                    messages: mergedMessages,
                };
                updateChannel(id);
                if (currentChannel === id) loadMessages(id);
                break;
            case "ping":
                break;
            case "pong":
                break;
            default:
                console.log("Default handler:", dataObj);
        }
    } else {
        console.log("Data received:", dataObj);
    }
}

async function createChannel() {
    if (selectedUsers.size === 0) {
        console.log("No members selected.");
        return;
    }

    const members = Array.from(selectedUsers);
    members.push(currentName);
    selectedUsers.clear();
    
    // Update UI selected state
    document.querySelectorAll('.online-box.selected').forEach(box => {
        box.classList.remove('selected');
    });

    const owner = currentName;
    const channelId = "ch_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
    const channelName = members.join(", ");

    channelInfo[channelId] = {
        id: channelId,
        name: channelName,
        members: members,
        host: owner,
        messages: {}
    };

    updateChannel(channelId);
    pushNotify("Channel created.", 1500);
}

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
                if (msg.message) {
                    handleData(msg.message);
                }
            }
        }
    } catch (err) {
        // Ignore polling errors.
    }
}

setInterval(pollMessages, 1000);

function pushNotify(message, timeout = 3000) {
    const box = document.getElementById("notifyBox");

    const note = document.createElement("div");
    note.className = "notify";
    note.textContent = message;

    box.appendChild(note);

    setTimeout(() => {
        note.classList.add("hide");
        setTimeout(() => note.remove(), 500);
    }, timeout);
}

async function updateOnlineList() {
    if (!currentName) {
        return;
    }
    try {
        const res = await fetch("/online", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: currentName })
        });

        const data = await res.json();
        let onlineNames = [];
        if (data.code === 1 && Array.isArray(data.online)) {
            onlineNames = data.online;
        } else if (peerRegistry.length) {
            onlineNames = peerRegistry.map(peer => peer.name).filter(Boolean);
        } else {
            return;
        }

        onlineListEl.innerHTML = "";

        onlineNames.forEach(fullName => {
            if (fullName === currentName) return;

            const short = fullName.charAt(0).toUpperCase();
            const displayName =
                fullName.length > 6 ? fullName.slice(0, 6) + "..." : fullName;

            const box = document.createElement("div");
            box.className = "online-box";
            box.dataset.username = fullName;

            if (selectedUsers.has(fullName)) {
                box.classList.add("selected");
            }

            const avatar = document.createElement("div");
            avatar.className = "avatar";
            avatar.textContent = short;

            const nameDiv = document.createElement("div");
            nameDiv.className = "user-name";
            nameDiv.textContent = displayName;

            box.appendChild(avatar);
            box.appendChild(nameDiv);

            box.addEventListener("click", () => {
                if (selectedUsers.has(fullName)) {
                    selectedUsers.delete(fullName);
                    box.classList.remove("selected");
                } else {
                    selectedUsers.add(fullName);
                    box.classList.add("selected");
                    fetch("/connect-peer", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ target: fullName })
                    }).then(r => r.json()).then(data => {
                        if (data.code === 1) {
                            pushNotify(`Connected to ${fullName}`);
                        } else {
                            pushNotify(`Could not connect to ${fullName}`);
                        }
                    }).catch(e => console.error(e));
                }
            });

            onlineListEl.appendChild(box);
        });
    } catch (err) {
        onlineListEl.innerHTML = "";
    }
}

setInterval(updateOnlineList, 1000);
setInterval(refreshPeerList, 5000);

async function logout() {
    if (!currentName) {
        window.location.href = '/login.html';
        return;
    }

    try {
        const res = await fetch("/api/logout", { method: "POST" });
        if (res.redirected) {
            window.location.href = res.url;
        } else {
            window.location.href = '/login.html';
        }
    } catch (err) {
        window.location.href = '/login.html';
    }
}

function updateChannel(ID) {
    const channel = channelInfo[ID];
    if (!channel) return;

    const name = channel.name;
    const messages = channel.messages;
    const msgList = Object.values(messages);

    const lastMsg = msgList.length > 0
        ? msgList.reduce((latest, msg) =>
            !latest || msg.time > latest.time ? msg : latest
        , null)
        : null;

    let item = chatList.querySelector(`.chat-item[data-chat-id='${ID}']`);
    if (!item) {
        item = document.createElement("div");
        item.className = "chat-item";
        item.dataset.chatId = ID;

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = name.charAt(0).toUpperCase();

        const meta = document.createElement("div");
        meta.className = "meta";

        const nameDiv = document.createElement("div");
        nameDiv.className = "name";
        nameDiv.textContent = name.length > 15 ? name.slice(0, 15) + "..." : name;

        const snippetDiv = document.createElement("div");
        snippetDiv.className = "snippet";

        meta.appendChild(nameDiv);
        meta.appendChild(snippetDiv);

        const timeDiv = document.createElement("div");
        timeDiv.className = "time";

        item.appendChild(avatar);
        item.appendChild(meta);
        item.appendChild(timeDiv);

        chatList.appendChild(item);

        item.addEventListener("mouseenter", () => {
            if (currentChannel !== ID) item.style.backgroundColor = "#f7f9fb";
        });
        item.addEventListener("mouseleave", () => {
            if (currentChannel !== ID) item.style.backgroundColor = "white";
        });

        item.addEventListener("click", () => {
            currentChannel = ID;

            chatList.querySelectorAll(".chat-item").forEach(ci => {
                ci.style.backgroundColor = ci.dataset.chatId == currentChannel 
                    ? "#fce7f3" 
                    : "white";
            });

            loadMessages(ID, false);
        });
    }

    const snippet = lastMsg
        ? (lastMsg.content.length > 20 ? lastMsg.content.slice(0, 20) + "..." : lastMsg.content)
        : "No messages yet";

    item.querySelector(".snippet").textContent = snippet;

    item.querySelector(".time").textContent = lastMsg
        ? new Date(lastMsg.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : "";

    item.style.backgroundColor = (currentChannel === ID) ? "#fce7f3" : "white";
}

function startChannelUpdater() {
    setInterval(() => {
        if (currentChannel) loadMessages(currentChannel, true);
        for (const id in channelInfo) {
            updateChannel(id);

            const channel = channelInfo[id];

            if (!channel || !channel.members) continue;

            const payloadTemplate = {
                type: "channel_message",
                id: id,
                content: channel,
                from: currentName
            };

            channel.members.forEach(memberName => {
                if (memberName === currentName) return;
                fetch("/send-peer", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        from: currentName,
                        to: memberName,
                        message: payloadTemplate
                    })
                }).catch(e => console.error("Channel update error to", memberName, e));
            });
        }
    }, 1000);
}

startChannelUpdater();

function loadMessages(chID, keepScroll = false) {
    const box = document.getElementById("conversation");
    const ch = channelInfo[chID];
    if (!box || !ch) return;

    const oldPos = box.scrollTop;
    const isBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 5;

    box.innerHTML = "";

    const msgList = Object.values(ch.messages || {});
    msgList.sort((a, b) => a.time - b.time);

    for (const msg of msgList) {
        const wrapper = document.createElement("div");
        const isMe = msg.from === currentName;

        wrapper.className = "msg-wrapper " + (isMe ? "me" : "other");

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = msg.from.charAt(0).toUpperCase();

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        const nameEl = document.createElement("div");
        nameEl.className = "sender-name";
        nameEl.textContent = msg.from;

        const textEl = document.createElement("div");
        textEl.className = "text";
        textEl.innerHTML = msg.content.replace(/\n/g, "<br>");

        const timeEl = document.createElement("div");
        timeEl.className = "time";
        timeEl.textContent = new Date(msg.time).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit"
        });

        bubble.appendChild(nameEl);
        bubble.appendChild(textEl);
        bubble.appendChild(timeEl);

        if (isMe) {
            wrapper.appendChild(bubble);
            wrapper.appendChild(avatar);
        } else {
            wrapper.appendChild(avatar);
            wrapper.appendChild(bubble);
        }

        box.appendChild(wrapper);
    }

    if (!keepScroll || isBottom) {
        box.scrollTop = box.scrollHeight;
    } else {
        box.scrollTop = oldPos;
    }
}
