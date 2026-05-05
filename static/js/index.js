"use strict";

/* ── State ── */
let currentName = null, currentChannel = null;
const selectedUsers = new Set();
const addMemberSel = new Set();
const channelInfo = {};
const declinedChannels = new Set(); // Track channels user declined or failed password
let pendingInvite = null;
let currentOnlineNames = [];

/* ── DOM ── */
const $ = id => document.getElementById(id);
const onlineListEl = $("onlineList"), onlineCountEl = $("onlineCount");
const chatListEl = $("chatList"), channelCountEl = $("channelCount");
const topUserEl = $("topUser"), composerEl = $("composer"), sendBtn = $("sendBtn");
const channelBtn = $("channelBtn"), clearSelBtn = $("clearSelBtn");
const channelNameInput = $("channelNameInput"), channelPasswordEl = $("channelPassword");
const createChannelPanel = $("createChannelPanel"), selectedCountEl = $("selectedCount");
const channelTitleEl = $("channelTitle"), channelMembersEl = $("channelMembers");
const conversationEl = $("conversation"), connectionStatusEl = $("connectionStatus");
const addMemberBtn = $("addMemberBtn");
const passwordModal = $("passwordModal"), passwordModalInput = $("passwordModalInput");
const passwordModalOk = $("passwordModalOk"), passwordModalCancel = $("passwordModalCancel");
const passwordModalTitle = $("passwordModalTitle"), passwordModalDesc = $("passwordModalDesc");
const addMemberModal = $("addMemberModal"), addMemberList = $("addMemberList");
const addMemberOk = $("addMemberOk"), addMemberCancel = $("addMemberCancel");

/* ── Peer panel (debug) ── */
const peerPanelBtn = document.createElement('button');
peerPanelBtn.id = 'showPeersBtn';
peerPanelBtn.textContent = 'Show peers';
peerPanelBtn.style.cssText = 'margin-left:8px;padding:6px 8px;border-radius:6px;border:1px solid #cbd5e1;background:white;cursor:pointer;font-size:12px';
connectionStatusEl.parentNode.insertBefore(peerPanelBtn, connectionStatusEl.nextSibling);

const peerPanel = document.createElement('div');
peerPanel.id = 'peerPanel';
peerPanel.style.cssText = 'position:fixed;right:12px;bottom:12px;width:300px;max-height:240px;overflow:auto;background:white;border:1px solid #e2e8f0;padding:8px;border-radius:8px;box-shadow:0 6px 18px rgba(2,6,23,0.08);display:none;z-index:9999;font-size:13px';
document.body.appendChild(peerPanel);

async function fetchAndRenderPeers() {
    try {
        const r = await fetch('/peers', { method: 'POST', headers: {'Content-Type':'application/json'} });
        const d = await r.json();
        if (d.code !== 1 || !Array.isArray(d.peers)) { peerPanel.innerHTML = '<div style="color:#ef4444">No peers</div>'; return; }
        if (!d.peers.length) { peerPanel.innerHTML = '<div style="color:#64748b">No cached peers</div>'; return; }
        peerPanel.innerHTML = '<div style="font-weight:700;margin-bottom:6px">Known peers</div>' + d.peers.map(p=>`<div style="padding:6px;border-radius:6px;border:1px solid #f1f5f9;margin-bottom:6px"><div style="font-weight:600">${p.name}</div><div style="color:#64748b;font-size:12px">${p.ip}:${p.port}</div></div>`).join('');
    } catch (e) {
        peerPanel.innerHTML = '<div style="color:#ef4444">Error fetching peers</div>';
    }
}

let peerPanelInterval = null;
peerPanelBtn.addEventListener('click', () => {
    if (peerPanel.style.display === 'none') {
        peerPanel.style.display = 'block';
        fetchAndRenderPeers();
        peerPanelInterval = setInterval(() => { if (peerPanel.style.display==='block') fetchAndRenderPeers(); }, 5000);
        peerPanelBtn.textContent = 'Hide peers';
    } else {
        peerPanel.style.display = 'none';
        clearInterval(peerPanelInterval); peerPanelInterval = null;
        peerPanelBtn.textContent = 'Show peers';
    }
});

/* ── Helpers ── */
const getCookie = name => { const v = `; ${document.cookie}`.split(`; ${name}=`); return v.length===2?v.pop().split(';').shift():null; };
const formatTime = ts => new Date(ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const stripPwd = ch => { const {password,...safe}=ch; return safe; };

function pushNotify(text, t=2000, sticky=false) {
    const n = document.createElement('div');
    n.className = 'notify';
    n.textContent = text;
    const box = document.getElementById('notifyBox') || document.body;
    box.appendChild(n);
    if (!sticky) {
        setTimeout(() => { n.classList.add('hide'); setTimeout(()=>n.remove(), 400); }, t);
    }
}

function saveState() {
    localStorage.setItem('chatapp_channels', JSON.stringify(channelInfo));
}

function loadState() {
    const saved = localStorage.getItem('chatapp_channels');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            Object.assign(channelInfo, data);
            Object.keys(channelInfo).forEach(id => renderChannelItem(id));
        } catch (e) { console.error("Failed to load state", e); }
    }
}

function addSystemMessage(chId, text) {
    const ch = channelInfo[chId]; if (!ch) return;
    ch.messages['sys_'+Date.now()] = { from:'__system__', content:text, time:Date.now(), system:true };
    if (currentChannel===chId) loadMessages(chId);
    renderChannelItem(chId);
    saveState();
}

/* ── Session ── */
function initializeUserSession() {
    const user = getCookie('account');
    if (user) { currentName=user; topUserEl.textContent=user; sendBtn.disabled=false; pushNotify(`Welcome, ${user}!`); registerPeer(); }
    else { window.location.href='/login.html'; }
}

// Fetch authoritative username from server (avoid stale cookie issues)
async function fetchCurrentUser() {
    try {
        const res = await fetch('/api/me');
        if (!res.ok) { window.location.href = '/login.html'; return; }
        const data = await res.json();
        const username = data.username || null;
        if (!username) { window.location.href = '/login.html'; return; }
        currentName = username;
        topUserEl.textContent = username;
        sendBtn.disabled = false;
        pushNotify(`Welcome, ${username}!`);
        // Immediately register with tracker using authoritative name
        await registerPeer();
    } catch (e) { window.location.href = '/login.html'; }
}

/* ── Phase 1: Tracker ── */
async function registerPeer() {
    if (!currentName) return;
    try { await fetch('/submit-info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:currentName,ip:window.location.hostname,port:parseInt(window.location.port)||8001})}); } catch {}
}

async function updateOnlineList() {
    if (!currentName) return;
    try {
        const res = await fetch('/online',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:currentName})});
        const data = await res.json();
        connectionStatusEl.querySelector('.dot').className = 'dot '+(data.code===1?'online':'offline');
        currentOnlineNames = data.code===1&&Array.isArray(data.online) ? data.online.filter(n=>n!==currentName) : [];
        onlineCountEl.textContent = currentOnlineNames.length;
        renderOnlineList(currentOnlineNames);
    } catch { connectionStatusEl.querySelector('.dot').className='dot offline'; }
}

function renderOnlineList(names) {
    onlineListEl.innerHTML = '';
    if (!names.length) { onlineListEl.innerHTML='<div style="padding:12px;font-size:13px;color:#94a3b8;text-align:center">No other peers online</div>'; return; }
    names.forEach(name => {
        const box = document.createElement('div');
        box.className = 'online-box'+(selectedUsers.has(name)?' selected':'');
        box.innerHTML = `<div class="avatar">${name[0].toUpperCase()}</div><div class="user-name">${name}</div><span class="check-icon">✓</span>`;
        box.addEventListener('click', () => togglePeerSel(name, box));
        onlineListEl.appendChild(box);
    });
}

async function connectToPeer(name) {
    try { const r=await fetch('/connect-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:name})}); const d=await r.json(); return d.code===1; } catch { return false; }
}

function togglePeerSel(name, box) {
    if (selectedUsers.has(name)) { selectedUsers.delete(name); box.classList.remove('selected'); }
    else { selectedUsers.add(name); box.classList.add('selected'); connectToPeer(name).then(ok=>{ if(!ok) pushNotify(`Could not resolve ${name}`,2500,true); }); }
    selectedCountEl.textContent = selectedUsers.size;
    createChannelPanel.classList.toggle('hidden', selectedUsers.size===0);
}

/* ── Access toggle ── */
document.querySelectorAll("input[name='channelAccess']").forEach(r => {
    r.addEventListener('change', () => {
        const priv = $('accessPrivate').checked;
        channelPasswordEl.classList.toggle('hidden', !priv);
        if (!priv) channelPasswordEl.value = '';
    });
});

/* ── Channel Creation ── */
function createChannel() {
    if (!selectedUsers.size) { pushNotify('Select at least one peer.',2000,true); return; }
    const isPriv = $('accessPrivate').checked;
    const pwd = channelPasswordEl.value.trim();
    if (isPriv && !pwd) { pushNotify('Enter a password.',2000,true); channelPasswordEl.focus(); return; }

    const members = [currentName, ...Array.from(selectedUsers)];
    const chName = channelNameInput.value.trim() || members.join(', ');
    const chId = 'ch_'+Date.now()+'_'+Math.random().toString(36).slice(2,7);
    channelInfo[chId] = { id:chId, name:chName, members, host:currentName, messages:{}, access:isPriv?'private':'public', password:isPriv?pwd:null };

    selectedUsers.clear(); channelNameInput.value=''; channelPasswordEl.value='';
    channelPasswordEl.classList.add('hidden'); $('accessPublic').checked=true;
    createChannelPanel.classList.add('hidden');
    document.querySelectorAll('.online-box.selected').forEach(b=>b.classList.remove('selected'));

    renderChannelItem(chId); selectChannel(chId);
    saveState();
    pushNotify(`Channel "${chName}" created (${isPriv?'🔒 Private':'🌐 Public'}).`, 2500);
    members.filter(m=>m!==currentName).forEach(m=>sendInvite(chId,m));
}

async function sendInvite(chId, target) {
    const ch = channelInfo[chId]; if (!ch) return;
    const payload = { type:'channel_invite', id:chId, name:ch.name, access:ch.access, host:ch.host, members:ch.members, from:currentName, channel_data: ch.access==='private'?null:stripPwd(ch) };
    await fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:target,message:payload})}).catch(()=>{});
}

/* ── Render Channel ── */
function renderChannelItem(id) {
    const ch = channelInfo[id]; if (!ch) return;
    const isPriv = ch.access==='private';
    let item = chatListEl.querySelector(`.chat-item[data-chat-id="${id}"]`);
    if (!item) {
        item = document.createElement('div');
        item.className = 'chat-item'+(isPriv?' private-channel':'');
        item.dataset.chatId = id;
        item.innerHTML = `<div class="avatar">${isPriv?'🔒':ch.name[0].toUpperCase()}</div><div class="meta"><div class="name"></div><div class="snippet"></div></div><div class="time"></div>`;
        item.addEventListener('click', ()=>selectChannel(id));
        chatListEl.appendChild(item);
    }
    const msgs = Object.values(ch.messages||{}).filter(m=>!m.system).sort((a,b)=>a.time-b.time);
    const last = msgs[msgs.length-1];
    item.querySelector('.name').textContent = (isPriv?'🔒 ':'')+ch.name.slice(0,20)+(ch.name.length>20?'…':'');
    // Private channels: hide message content from sidebar preview
    item.querySelector('.snippet').textContent = isPriv ? '🔒 Messages hidden' : (last?`${last.from}: ${last.content.slice(0,28)}${last.content.length>28?'…':''}`:'No messages yet');
    item.querySelector('.time').textContent = last?formatTime(last.time):'';
    item.classList.toggle('active', currentChannel===id);
    channelCountEl.textContent = Object.keys(channelInfo).length;
}

function selectChannel(id) {
    currentChannel=id; const ch=channelInfo[id]; if (!ch) return;
    channelTitleEl.textContent = (ch.access==='private'?'🔒 ':'')+ch.name;
    channelMembersEl.textContent = ch.members.join(' · ');
    chatListEl.querySelectorAll('.chat-item').forEach(el=>el.classList.toggle('active',el.dataset.chatId===id));
    addMemberBtn.classList.remove('hidden');
    loadMessages(id);
}

/* ── Add Member Modal ── */
function openAddMemberModal() {
    if (!currentChannel) return;
    const ch = channelInfo[currentChannel]; if (!ch) return;
    addMemberSel.clear(); addMemberList.innerHTML = '';
    const eligible = currentOnlineNames.filter(n=>!ch.members.includes(n));
    if (!eligible.length) { addMemberList.innerHTML='<div style="padding:12px;font-size:13px;color:#94a3b8;text-align:center">No online peers to add.</div>'; }
    else eligible.forEach(name => {
        const item = document.createElement('div');
        item.className = 'add-member-item';
        item.innerHTML = `<div class="avatar">${name[0].toUpperCase()}</div><span style="font-weight:600;font-size:13px">${name}</span>`;
        item.addEventListener('click', () => { addMemberSel.has(name)?(addMemberSel.delete(name),item.classList.remove('selected')):(addMemberSel.add(name),item.classList.add('selected')); });
        addMemberList.appendChild(item);
    });
    addMemberModal.classList.remove('hidden');
}

async function confirmAddMembers() {
    if (!addMemberSel.size) { pushNotify('Select at least one peer.',2000,true); return; }
    const ch = channelInfo[currentChannel]; if (!ch) return;
    addMemberModal.classList.add('hidden');
    const newMembers = Array.from(addMemberSel); addMemberSel.clear();
    for (const name of newMembers) {
        await connectToPeer(name);
        if (!ch.members.includes(name)) ch.members.push(name);
        await sendInvite(currentChannel, name);
        const notifyPayload = { type:'member_added', id:currentChannel, newMember:name, from:currentName };
        await Promise.allSettled(ch.members.filter(m=>m!==currentName&&m!==name).map(m=>
            fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:m,message:notifyPayload})}).catch(()=>{})
        ));
    }
    channelMembersEl.textContent = ch.members.join(' · ');
    renderChannelItem(currentChannel);
    addSystemMessage(currentChannel, `${newMembers.join(', ')} invited by ${currentName}.`);
    pushNotify(`Invited: ${newMembers.join(', ')}`);
}

/* ── Invite Toast (Accept / Decline) ── */
function showInviteToast(invite) {
    const {id, name, access, host, members, from, channel_data} = invite;
    const isPriv = access === 'private';

    const toast = document.createElement('div');
    toast.className = 'notify invite-toast';
    toast.innerHTML = `
        <div style="font-weight:700;margin-bottom:4px">${isPriv?'🔒':'🌐'} Invite: "${name}"</div>
        <div style="font-size:12px;margin-bottom:8px;opacity:.8">From <b>${from}</b>${isPriv?' · Private channel':''}</div>
        <div style="display:flex;gap:6px">
            <button class="inv-accept" style="flex:1;padding:5px;border:none;border-radius:6px;background:#22c55e;color:white;font-weight:700;cursor:pointer">Accept</button>
            <button class="inv-decline" style="flex:1;padding:5px;border:none;border-radius:6px;background:#ef4444;color:white;font-weight:700;cursor:pointer">Decline</button>
        </div>`;

    toast.style.pointerEvents = 'all';
    $('notifyBox').appendChild(toast);

    const dismiss = () => { toast.classList.add('hide'); setTimeout(()=>toast.remove(), 400); };

    toast.querySelector('.inv-accept').addEventListener('click', () => {
        dismiss();
        if (isPriv) {
            // Private: ask for password
            pendingInvite = invite;
            passwordModalTitle.textContent = `Join "${name}"`;
            passwordModalDesc.textContent = `${from} invited you. Enter password:`;
            passwordModalInput.value = '';
            passwordModal.classList.remove('hidden');
            setTimeout(()=>passwordModalInput.focus(), 100);
        } else {
            // Public: join immediately with the channel data
            channelInfo[id] = channel_data || {id, name, members, host, messages:{}, access:'public', password:null};
            renderChannelItem(id);
            selectChannel(id);
            pushNotify(`Joined "${name}"!`);
            members.filter(m=>m!==currentName).forEach(m=>connectToPeer(m));
        }
    });

    toast.querySelector('.inv-decline').addEventListener('click', () => {
        dismiss();
        declinedChannels.add(id); // Mark locally
        // Notify host to remove me from members list
        fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:from,message:{type:'invite_declined',id,from:currentName}})}).catch(()=>{});
        pushNotify(`Declined invite to "${name}".`, 2000);
    });

    // Auto-dismiss after 15 seconds
    setTimeout(dismiss, 15000);
}

/* ── Incoming Handler ── */
function handleData(d) {
    if (!d?.type) return;
    switch (d.type) {
        case 'channel_message': {
            const {content:inc, id, nmsg} = d; if (!inc||!id) break;
            if (!channelInfo[id]) {
                // Only auto-add if user hasn't explicitly declined or failed password
                if (declinedChannels.has(id)) break;
                channelInfo[id]=inc; renderChannelItem(id); pushNotify(`Synced channel "${inc.name}"`); break;
            }
            const local = channelInfo[id];
            channelInfo[id] = {...local,...inc, password:local.password, messages:{...local.messages,...(inc.messages||{})}};
            if (nmsg&&nmsg.from!==currentName&&currentChannel!==id) pushNotify(`${nmsg.from}: ${nmsg.content.slice(0,60)}`);
            renderChannelItem(id); if (currentChannel===id) loadMessages(id);
            saveState();
            break;
        }
        case 'channel_invite': {
            const invite = d; const {id,name,access,from} = invite;
            if (!id || channelInfo[id]) break; // already a member, skip
            // Both public and private: show Accept/Decline toast (don't auto-join)
            showInviteToast(invite);
            break;
        }
        case 'join_request': {
            const {id,from,password} = d; const ch=channelInfo[id]; if (!ch) break;
            if (ch.password===password) {
                fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:from,message:{type:'channel_message',id,content:stripPwd(ch),from:currentName}})}).catch(()=>{});
                if (!ch.members.includes(from)) {
                    ch.members.push(from); renderChannelItem(id);
                    if (currentChannel===id) channelMembersEl.textContent=ch.members.join(' · ');
                    addSystemMessage(id,`${from} joined.`);
                    const notif={type:'member_added',id,newMember:from,from:currentName};
                    ch.members.filter(m=>m!==currentName&&m!==from).forEach(m=>fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:m,message:notif})}).catch(()=>{}));
                }
            } else {
                fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:from,message:{type:'join_denied',id,from:currentName}})}).catch(()=>{});
            }
            break;
        }
        case 'join_denied': { declinedChannels.add(d.id); pushNotify(`Wrong password. Access denied.`,4000,true); break; }
        case 'invite_declined': {
            const {id, from:decliner} = d; const ch=channelInfo[id];
            if (ch && ch.host===currentName) {
                ch.members = ch.members.filter(m=>m!==decliner);
                renderChannelItem(id);
                if (currentChannel===id) channelMembersEl.textContent=ch.members.join(' · ');
                addSystemMessage(id, `${decliner} declined the invite.`);
            }
            break;
        }
        case 'member_added': {
            const {id,newMember} = d; const ch=channelInfo[id]; if (!ch||ch.members.includes(newMember)) break;
            ch.members.push(newMember); connectToPeer(newMember);
            renderChannelItem(id); if (currentChannel===id) channelMembersEl.textContent=ch.members.join(' · ');
            addSystemMessage(id,`${newMember} joined the channel.`);
            break;
        }
        case 'notify': pushNotify(d.content,3000); break;
        default: console.log('[handleData]',d.type,d);
    }
}

/* ── Password Modal submit ── */
function submitPasswordModal() {
    if (!pendingInvite) return;
    const pwd = passwordModalInput.value.trim(); if (!pwd) { passwordModalInput.focus(); return; }
    const {id,name,members,from} = pendingInvite; pendingInvite=null;
    passwordModal.classList.add('hidden');
    fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:from,message:{type:'join_request',id,name,from:currentName,password:pwd}})})
        .then(()=>{ pushNotify('Waiting for approval...'); members.filter(m=>m!==currentName).forEach(m=>connectToPeer(m)); })
        .catch(()=>pushNotify('Failed to send.',3000,true));
    passwordModalInput.value='';
}

/* ── Send message ── */
async function sendMessage() {
    if (!currentChannel) { pushNotify('Select a channel first.',2000,true); return; }
    const text = composerEl.value.trim(); if (!text) return;
    composerEl.value=''; autoResizeTextarea();
    const ch = channelInfo[currentChannel]; if (!ch) return;
    const msgId = Date.now()+'_'+Math.random().toString(36).slice(2,6);
    const nmsg = { from:currentName, content:text, time:Date.now() };
    ch.messages[msgId] = nmsg; loadMessages(currentChannel); renderChannelItem(currentChannel);
    const payload = { type:'channel_message', id:currentChannel, content:stripPwd(ch), nmsg, from:currentName };
    await Promise.allSettled(ch.members.filter(m=>m!==currentName).map(m=>
        fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:m,message:payload})}).catch(()=>{})
    ));
}

/* ── Poll ── */
async function pollMessages() {
    if (!currentName) return;
    try { const r=await fetch('/poll-messages',{method:'POST',headers:{'Content-Type':'application/json'}}); const d=await r.json(); if(d.code===1&&Array.isArray(d.messages)) d.messages.forEach(m=>m.message&&handleData(m.message)); } catch {}
}

/* ── Sync channel to peers ── */
async function syncChannelToPeers(chId) {
    const ch=channelInfo[chId]; if (!ch?.members) return;
    const payload={type:'channel_message',id:chId,content:stripPwd(ch),from:currentName};
    await Promise.allSettled(ch.members.filter(m=>m!==currentName).map(m=>
        fetch('/send-peer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:currentName,to:m,message:payload})}).catch(()=>{})
    ));
}

/* ── Load Messages ── */
function loadMessages(chId) {
    const ch=channelInfo[chId]; if (!ch) return;
    const msgs=Object.values(ch.messages||{}).sort((a,b)=>a.time-b.time);
    const atBottom=conversationEl.scrollHeight-conversationEl.scrollTop<=conversationEl.clientHeight+60;
    conversationEl.innerHTML='';
    if (!msgs.length) { conversationEl.innerHTML='<div style="margin:auto;text-align:center;color:#94a3b8;font-size:14px">No messages yet. Say hello! 👋</div>'; return; }
    let lastDate=null;
    msgs.forEach(msg=>{
        const date=new Date(msg.time).toLocaleDateString();
        if (date!==lastDate) { const sep=document.createElement('div'); sep.style.cssText='text-align:center;font-size:11px;color:#94a3b8;margin:8px 0'; sep.textContent=date; conversationEl.appendChild(sep); lastDate=date; }
        if (msg.system) { const s=document.createElement('div'); s.className='system-msg'; s.textContent=msg.content; conversationEl.appendChild(s); return; }
        const isMe=msg.from===currentName;
        const wrap=document.createElement('div'); wrap.className='msg-wrapper '+(isMe?'me':'other');
        const av=document.createElement('div'); av.className='avatar'; av.textContent=msg.from[0].toUpperCase(); av.title=msg.from;
        const bbl=document.createElement('div'); bbl.className='bubble';
        if (!isMe) { const sn=document.createElement('div'); sn.className='sender-name'; sn.textContent=msg.from; bbl.appendChild(sn); }
        const tx=document.createElement('div'); tx.className='bubble-text'; tx.textContent=msg.content; bbl.appendChild(tx);
        const ti=document.createElement('div'); ti.className='bubble-time'; ti.textContent=formatTime(msg.time); bbl.appendChild(ti);
        wrap.appendChild(av); wrap.appendChild(bbl); conversationEl.appendChild(wrap);
    });
    if (atBottom) conversationEl.scrollTop=conversationEl.scrollHeight;
}

/* ── Auto-resize textarea ── */
function autoResizeTextarea() { composerEl.style.height='auto'; composerEl.style.height=Math.min(composerEl.scrollHeight,140)+'px'; }

/* ── Logout ── */
async function logout() { try { await fetch('/api/logout',{method:'POST'}); } catch {} window.location.href='/login.html'; }

/* ── Event Listeners ── */
sendBtn.addEventListener('click', sendMessage);
composerEl.addEventListener('keydown', e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();} });
composerEl.addEventListener('input', autoResizeTextarea);
channelBtn.addEventListener('click', createChannel);
clearSelBtn.addEventListener('click', ()=>{ selectedUsers.clear(); document.querySelectorAll('.online-box.selected').forEach(b=>b.classList.remove('selected')); createChannelPanel.classList.add('hidden'); });
$('logoutBtn').addEventListener('click', logout);
addMemberBtn.addEventListener('click', openAddMemberModal);
addMemberOk.addEventListener('click', confirmAddMembers);
addMemberCancel.addEventListener('click', ()=>{ addMemberModal.classList.add('hidden'); addMemberSel.clear(); });
passwordModalOk.addEventListener('click', submitPasswordModal);
passwordModalCancel.addEventListener('click', ()=>{ passwordModal.classList.add('hidden'); pendingInvite=null; });
passwordModalInput.addEventListener('keydown', e=>{ if(e.key==='Enter') submitPasswordModal(); if(e.key==='Escape'){passwordModal.classList.add('hidden');pendingInvite=null;} });

/* ── Bootstrap ── */
setInterval(updateOnlineList, 2000);
setInterval(pollMessages, 1000);
setInterval(()=>Object.keys(channelInfo).forEach(syncChannelToPeers), 5000);
loadState();
fetchCurrentUser();
sendBtn.disabled = true;
