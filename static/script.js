let currentConvId = localStorage.getItem('last_conversation_id') || null;
let isStreaming = false;
let abortController = null;
let sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
let contextMode = 'all';
let contextParamM = 0;
let contextParamN = 10;
let contextPreviewActive = false;
let currentSystemPrompt = localStorage.getItem('activeSystemPrompt') || null;
let allSystemPrompts = [];
let webSearchEnabled = false;
let uploadedImages = [];
let sttMethod = null;
let availableSTTMethods = [];
let micRecorder = null;
let mediaStream = null;
let audioChunks = [];
let silenceTimeout = null;
let silenceThreshold = -50;
let isRecording = false;
let currentSpeechUtterance = null;

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (window.innerWidth < 1024) {
        sidebar.classList.toggle('open');
    } else {
        sidebarCollapsed = !sidebarCollapsed;
        sidebar.style.width = sidebarCollapsed ? '0' : '16rem';
        sidebar.style.overflow = sidebarCollapsed ? 'hidden' : 'auto';
        localStorage.setItem('sidebarCollapsed', sidebarCollapsed);
    }
}

function toggleContextWindow(show) {
    const modal = document.getElementById('context-modal');
    if (show === undefined) {
        modal.classList.toggle('hidden');
    } else if (show) {
        modal.classList.remove('hidden');
    } else {
        modal.classList.add('hidden');
    }
}

function updateContextMode() {
    const selected = document.querySelector('input[name="context"]:checked').value;
    contextMode = selected;
    document.getElementById('ctx-last-group').style.opacity = selected === 'last_n' ? '1' : '0.4';
    document.getElementById('ctx-both-group').style.opacity = selected === 'first_m_last_n' ? '1' : '0.4';
    if (selected === 'last_n') {
        contextParamN = parseInt(document.getElementById('ctx-n').value);
    } else if (selected === 'first_m_last_n') {
        contextParamM = parseInt(document.getElementById('ctx-m').value);
        contextParamN = parseInt(document.getElementById('ctx-n2').value);
    }
    if (contextPreviewActive) {
        highlightContextMessages();
    }
}

function updateContextDisplay(which) {
    if (which === 'n') {
        const val = document.getElementById('ctx-n').value;
        document.getElementById('ctx-n-display').textContent = val;
        contextParamN = parseInt(val);
    } else if (which === 'm') {
        const val = document.getElementById('ctx-m').value;
        document.getElementById('ctx-m-display').textContent = val;
        contextParamM = parseInt(val);
    } else if (which === 'n2') {
        const val = document.getElementById('ctx-n2').value;
        document.getElementById('ctx-n2-display').textContent = val;
        contextParamN = parseInt(val);
    }
    if (contextPreviewActive) {
        highlightContextMessages();
    }
}

function toggleContextPreview() {
    contextPreviewActive = !contextPreviewActive;
    if (contextPreviewActive) {
        highlightContextMessages();
    } else {
        clearContextHighlight();
    }
}

function highlightContextMessages() {
    clearContextHighlight();
    if (contextMode === 'all') return;
    const messages = document.querySelectorAll('#chat-container > div');
    const totalMessages = messages.length;
    let highlightIndices = [];
    if (contextMode === 'last_n') {
        const n = contextParamN;
        for (let i = Math.max(0, totalMessages - n); i < totalMessages; i++) {
            highlightIndices.push(i);
        }
    } else if (contextMode === 'first_m_last_n') {
        const m = contextParamM;
        const n = contextParamN;
        for (let i = 0; i < Math.min(m, totalMessages); i++) {
            highlightIndices.push(i);
        }
        for (let i = Math.max(m, totalMessages - n); i < totalMessages; i++) {
            if (!highlightIndices.includes(i)) {
                highlightIndices.push(i);
            }
        }
    }
    messages.forEach((msg, idx) => {
        if (highlightIndices.includes(idx)) {
            msg.style.borderLeft = '3px solid #3b82f6';
            msg.style.paddingLeft = '12px';
        } else {
            msg.style.opacity = '0.5';
        }
    });
}

function clearContextHighlight() {
    document.querySelectorAll('#chat-container > div').forEach(msg => {
        msg.style.borderLeft = 'none';
        msg.style.paddingLeft = '0';
        msg.style.opacity = '1';
    });
}

function toggleWebSearch() {
    webSearchEnabled = !webSearchEnabled;
    const btn = document.getElementById('web-search-btn');
    btn.classList.toggle('active', webSearchEnabled);
    btn.classList.toggle('opacity-50', !webSearchEnabled);
}

async function updateTokenCounter() {
    const textEl = document.getElementById('token-text');
    const barEl = document.getElementById('token-bar');

    if (!currentConvId) {
        textEl.textContent = '0 tokens';
        barEl.innerHTML = '';
        return;
    }

    try {
        const response = await fetch(`/conversations/${currentConvId}/tokens`);
        if (!response.ok) return;
        const data = await response.json();
        const tokensUsed = data.tokens_used || {};
        const total = Object.values(tokensUsed).reduce((a, b) => a + b, 0);

        textEl.textContent = total > 0 ? `${total.toLocaleString()} tokens` : '0 tokens';
        barEl.innerHTML = '';

        if (total === 0) return;

        const colorShades = [
            '#4B5563', '#5A6B7F', '#6B7A8F', '#7A899F', '#8998AF',
            '#64748B', '#475569', '#334155', '#1E293B', '#0F172A', '#71717A'
        ];

        const getModelColor = (modelName) => {
            let hash = 0;
            for (let i = 0; i < modelName.length; i++) {
                hash = ((hash << 5) - hash) + modelName.charCodeAt(i);
                hash |= 0;
            }
            return colorShades[Math.abs(hash) % colorShades.length];
        };

        Object.entries(tokensUsed).forEach(([model, tokens]) => {
            const percentage = (tokens / total) * 100;
            const seg = document.createElement('div');
            seg.style.width = percentage + '%';
            seg.style.height = '100%';
            seg.style.backgroundColor = getModelColor(model);
            seg.setAttribute('data-tooltip', `${model}: ${tokens.toLocaleString()} tokens`);
            
            seg.addEventListener('mouseenter', (e) => {
                showTokenTooltip(e, seg);
            });
            seg.addEventListener('mouseleave', () => {
                hideTokenTooltip();
            });
            
            barEl.appendChild(seg);
        });
    } catch (err) {
        console.error('Error updating token counter:', err);
    }
}

let tokenTooltip = null;
let tokenArrow = null;

function showTokenTooltip(event, segment) {
    const text = segment.getAttribute('data-tooltip');
    
    if (!tokenTooltip) {
        tokenTooltip = document.createElement('div');
        tokenTooltip.style.cssText = `
            position: fixed;
            background-color: rgba(0, 0, 0, 0.95);
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            white-space: nowrap;
            font-size: 12px;
            font-weight: 500;
            z-index: 9999;
            border: 1px solid rgba(255, 255, 255, 0.3);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
            pointer-events: none;
        `;
        document.body.appendChild(tokenTooltip);
    }
    
    if (!tokenArrow) {
        tokenArrow = document.createElement('div');
        tokenArrow.style.cssText = `
            position: fixed;
            width: 0;
            height: 0;
            border: 6px solid transparent;
            border-bottom-color: rgba(0, 0, 0, 0.95);
            z-index: 9999;
            pointer-events: none;
        `;
        document.body.appendChild(tokenArrow);
    }
    
    tokenTooltip.textContent = text;
    tokenTooltip.style.display = 'block';
    tokenArrow.style.display = 'block';
    
    const rect = segment.getBoundingClientRect();
    const barRect = segment.parentElement.getBoundingClientRect();
    
    const tooltipLeft = barRect.left + barRect.width / 2;
    
    tokenTooltip.style.left = tooltipLeft + 'px';
    tokenTooltip.style.top = '50px';
    tokenTooltip.style.transform = 'translateX(-50%)';
    
    tokenArrow.style.left = tooltipLeft + 'px';
    tokenArrow.style.top = '44px';
    tokenArrow.style.transform = 'translateX(-50%)';
}

function hideTokenTooltip() {
    if (tokenTooltip) tokenTooltip.style.display = 'none';
    if (tokenArrow) tokenArrow.style.display = 'none';
}

setInterval(updateTokenCounter, 1000);

function toggleSystemPromptDropdown(show) {
    const dropdown = document.getElementById('system-prompt-dropdown');
    if (show === undefined) {
        dropdown.classList.toggle('hidden');
    } else if (show) {
        dropdown.classList.remove('hidden');
        loadSystemPrompts();
    } else {
        dropdown.classList.add('hidden');
    }
}

async function loadSystemPrompts() {
    try {
        const res = await fetch('/system-prompts');
        allSystemPrompts = await res.json();
        renderSystemPromptList();
    } catch (error) {
        console.error('Error loading system prompts:', error);
    }
}

function renderSystemPromptList() {
    const list = document.getElementById('system-prompt-list');
    list.innerHTML = '';
    const grouped = {};
    allSystemPrompts.forEach(prompt => {
        if (!grouped[prompt.category]) grouped[prompt.category] = [];
        grouped[prompt.category].push(prompt);
    });
    Object.entries(grouped).forEach(([category, prompts]) => {
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'border-b border-slate-200 dark:border-grayBorder pb-2 mb-2';
        prompts.forEach(prompt => {
            const btn = document.createElement('button');
            btn.className = `w-full text-left text-xs p-2 rounded hover:bg-slate-200 dark:hover:bg-slate-700 flex justify-between items-center group ${
                currentSystemPrompt === prompt.name ? 'bg-slate-200 dark:bg-slate-700 font-bold' : ''
            }`;
            btn.innerHTML = `<span>${prompt.name}</span>`;
            btn.onclick = (e) => {
                e.stopPropagation();
                selectSystemPrompt(prompt.name);
            };
            const actions = document.createElement('div');
            actions.className = 'flex gap-1 opacity-0 group-hover:opacity-100';
            const editBtn = document.createElement('button');
            editBtn.textContent = '✏️';
            editBtn.className = 'text-xs px-1';
            editBtn.onclick = (e) => {
                e.stopPropagation();
                editSystemPrompt(prompt);
            };
            const delBtn = document.createElement('button');
            delBtn.textContent = '🗑️';
            delBtn.className = 'text-xs px-1 text-red-500';
            delBtn.onclick = (e) => {
                e.stopPropagation();
                deleteSystemPrompt(prompt.name);
            };
            actions.appendChild(editBtn);
            actions.appendChild(delBtn);
            btn.appendChild(actions);
            categoryDiv.appendChild(btn);
        });
        list.appendChild(categoryDiv);
    });
}

function selectSystemPrompt(name) {
    currentSystemPrompt = name;
    localStorage.setItem('activeSystemPrompt', name);
    document.getElementById('system-prompt-btn').textContent = name ? `Behavior: ${name}` : 'Default';
    document.getElementById('system-prompt-dropdown').classList.add('hidden');
    renderSystemPromptList();
}

function openCustomPromptModal() {
    document.getElementById('custom-prompt-name').value = '';
    document.getElementById('custom-prompt-category').value = '';
    document.getElementById('custom-prompt-content').value = '';
    document.getElementById('custom-prompt-modal').classList.remove('hidden');
}

function closeCustomPromptModal() {
    document.getElementById('custom-prompt-modal').classList.add('hidden');
}

async function saveCustomPrompt() {
    const name = document.getElementById('custom-prompt-name').value.trim();
    const category = document.getElementById('custom-prompt-category').value.trim() || name;
    const content = document.getElementById('custom-prompt-content').value.trim();
    if (!name || !content) {
        alert('Name and Prompt are required');
        return;
    }
    try {
        const res = await fetch('/system-prompts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, category, content})
        });
        if (res.ok) {
            closeCustomPromptModal();
            loadSystemPrompts();
        } else {
            const err = await res.json();
            alert(err.detail || 'Error saving custom prompt');
        }
    } catch (error) {
        console.error('Error saving custom prompt:', error);
    }
}

async function editSystemPrompt(prompt) {
    document.getElementById('custom-prompt-name').value = prompt.name;
    document.getElementById('custom-prompt-category').value = prompt.category;
    document.getElementById('custom-prompt-content').value = prompt.content;
    document.getElementById('custom-prompt-modal').classList.remove('hidden');
}

async function deleteSystemPrompt(name) {
    if (!confirm(`Delete "${name}"?`)) return;
    try {
        const res = await fetch(`/system-prompts/${name}`, {method: 'DELETE'});
        if (res.ok) {
            if (currentSystemPrompt === name) {
                currentSystemPrompt = null;
                localStorage.removeItem('activeSystemPrompt');
                document.getElementById('system-prompt-btn').textContent = 'Default';
            }
            loadSystemPrompts();
        }
    } catch (error) {
        console.error('Error deleting system prompt:', error);
    }
}

async function toggleTheme() {
    document.documentElement.classList.toggle('dark');
}

function toggleSettings(show) {
    document.getElementById('settings-modal').classList.toggle('hidden', !show);
    if(show) loadSettings();
}

async function loadSettings() {
    const res = await fetch('/settings/provider_configs');
    const data = await res.json();
    const container = document.getElementById('providers-container');
    container.innerHTML = '';
    const configs = data.value ? JSON.parse(data.value) : [];
    if(configs.length === 0) addProviderRow();
    else configs.forEach(cfg => addProviderRow(cfg));
}

function addProviderRow(data = {provider: 'OpenAI', api_key: '', models: [], max_tokens: 4096}) {
    const container = document.getElementById('providers-container');
    const div = document.createElement('div');
    div.className = "p-4 rounded-xl border border-slate-200 dark:border-grayBorder bg-slate-50 dark:bg-zinc-900/50 relative group";
    div.innerHTML = `
        <button onclick="this.parentElement.remove()" class="absolute top-2 right-2 text-red-500 opacity-0 group-hover:opacity-100 text-xs">Remove</button>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
                <label class="block text-[10px] uppercase opacity-50 mb-1">Provider</label>
                <select onchange="updateKeyPlaceholder(this)" class="prov-type w-full p-2 rounded bg-white dark:bg-black border border-slate-300 dark:border-grayBorder text-sm outline-none">
                    <option value="OpenAI" ${data.provider==='OpenAI'?'selected':''}>OpenAI</option>
                    <option value="Anthropic" ${data.provider==='Anthropic'?'selected':''}>Anthropic</option>
                    <option value="Ollama" ${data.provider==='Ollama'?'selected':''}>Ollama</option>
                    <option value="DeepSeek" ${data.provider==='DeepSeek'?'selected':''}>DeepSeek</option>
                    <option value="Gemini" ${data.provider==='Gemini'?'selected':''}>Gemini</option>
                </select>
            </div>
            <div class="md:col-span-2">
                <label class="block text-[10px] uppercase opacity-50 mb-1">API Key / Endpoint</label>
                <input type="${data.provider==='Ollama'?'text':'password'}" value="${data.api_key}" placeholder="${data.provider==='Ollama'?'http://localhost:11434':'sk-...'}" class="prov-key w-full p-2 rounded bg-white dark:bg-black border border-slate-300 dark:border-grayBorder text-sm outline-none">
            </div>
        </div>
        <div class="mt-4">
            <label class="block text-[10px] uppercase opacity-50 mb-1">Models (comma separated)</label>
            <input type="text" value="${data.models.join(', ')}" placeholder="gpt-4o, gpt-3.5-turbo" class="prov-models w-full p-2 rounded bg-white dark:bg-black border border-slate-300 dark:border-grayBorder text-sm outline-none">
        </div>
        <div class="mt-4">
            <label class="block text-[10px] uppercase opacity-50 mb-2">Max Tokens: <span class="prov-tokens-display font-bold">${data.max_tokens}</span></label>
            <div class="flex gap-2">
                <input type="range" min="256" max="8192" step="256" value="${data.max_tokens}" class="prov-tokens-slider flex-1" oninput="updateTokenDisplay(this)">
                <input type="number" min="256" max="10000" value="${data.max_tokens}" class="prov-tokens-input w-20 p-2 rounded bg-white dark:bg-black border border-slate-300 dark:border-grayBorder text-sm outline-none" oninput="syncTokenSlider(this)">
            </div>
        </div>
        <div class="mt-4">
            <label class="block text-[10px] uppercase opacity-50 mb-1">Voice Models (comma separated)</label>
            <input type="text" value="${data.voice_models ? data.voice_models.join(', ') : ''}" placeholder="whisper-1" class="prov-voice-models w-full p-2 rounded bg-white dark:bg-black border border-slate-300 dark:border-grayBorder text-sm outline-none">
        </div>
    `;
    container.appendChild(div);
}

function updateTokenDisplay(slider) {
    const display = slider.parentElement.parentElement.querySelector('.prov-tokens-display');
    const input = slider.parentElement.parentElement.querySelector('.prov-tokens-input');
    const value = Math.min(parseInt(slider.value), 8192);
    display.textContent = value;
    input.value = value;
}

function syncTokenSlider(input) {
    const value = Math.min(parseInt(input.value) || 256, 10000);
    const slider = input.parentElement.parentElement.querySelector('.prov-tokens-slider');
    const display = input.parentElement.parentElement.querySelector('.prov-tokens-display');
    slider.value = Math.min(value, 8192);
    display.textContent = value;
    input.value = value;
}

function updateKeyPlaceholder(select) {
    const row = select.closest('div').parentElement;
    const keyInput = row.querySelector('.prov-key');
    keyInput.type = select.value === 'Ollama' ? 'text' : 'password';
    keyInput.placeholder = select.value === 'Ollama' ? 'http://localhost:11434' : 'sk-...';
}

async function saveAllSettings() {
    const providerRows = document.querySelectorAll('#providers-container > div');
    const configs = [];
    providerRows.forEach(row => {
        configs.push({
            provider: row.querySelector('.prov-type').value,
            api_key: row.querySelector('.prov-key').value,
            models: row.querySelector('.prov-models').value.split(',').map(s => s.trim()).filter(s => s),
            voice_models: row.querySelector('.prov-voice-models').value.split(',').map(s => s.trim()).filter(s => s),
            max_tokens: parseInt(row.querySelector('.prov-tokens-input').value) || 4096
        });
    });
    await fetch('/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: 'provider_configs', value: JSON.stringify(configs)})
    });
    await refreshModelDropdown();
    toggleSettings(false);
}

async function refreshModelDropdown() {
    const res = await fetch('/models');
    const models = await res.json();
    const select = document.getElementById('model-select');
    select.innerHTML = models.map(m => `<option value="${m.model}">${m.model} (${m.provider})</option>`).join('');
}

async function loadConversations() {
    const res = await fetch('/conversations');
    const convs = await res.json();
    const groupsRes = await fetch('/groups');
    const groupsData = await groupsRes.json();
    const allGroups = groupsData.groups || [];
    const list = document.getElementById('history-list');
    
    const grouped = {};
    const ungrouped = [];
    
    allGroups.forEach(g => {
        grouped[g] = [];
    });
    
    convs.forEach(c => {
        if (c.group_name && grouped[c.group_name]) {
            grouped[c.group_name].push(c);
        } else if (!c.group_name) {
            ungrouped.push(c);
        }
    });

    let html = '';
    Object.keys(grouped).sort().forEach(groupName => {
        const chats = grouped[groupName];
        const isGroupActive = chats.some(c => c.id === currentConvId);
        const activeClass = isGroupActive ? 'group-active' : '';

        html += `
            <div class="mt-3">
                <div class="flex items-center justify-between px-2 py-1 text-xs font-bold text-slate-600 dark:text-slate-400 ${activeClass}">
                    <div class="flex items-center gap-2 flex-1 cursor-pointer hover:bg-slate-200 dark:hover:bg-zinc-800 rounded px-1 py-1" onclick="showGroupChatList('${groupName}')">
                        <span id="group-toggle-${groupName}" class="cursor-pointer" onclick="event.stopPropagation(); toggleGroupArrow('${groupName}')">▶</span>
                        <span>${groupName}</span>
                        <span class="text-xs opacity-50">(${chats.length})</span>
                    </div>
                    <div class="opacity-0 hover:opacity-100">
                        <button onclick="showGroupContextMenu(event, '${groupName}')" class="text-slate-500 hover:text-slate-700 text-xs p-1">⋯</button>
                    </div>
                </div>
                <div id="group-${groupName}" class="space-y-1 hidden">
        `;
        chats.forEach(c => {
            html += renderChatItem(c);
        });
        html += `
                </div>
            </div>
        `;
    });

    if (ungrouped.length > 0) {
        html += '<div class="mt-2">';
        ungrouped.forEach(c => {
            html += renderChatItem(c, true);
        });
        html += '</div>';
    }
    list.innerHTML = html;
}

function renderChatItem(c, isUngrouped = false) {
    const indent = isUngrouped ? '' : 'ml-4';
    // Escape the chat name to prevent XSS and garbled text
    const safeName = document.createElement('div');
    safeName.textContent = c.name;
    return `
        <div class="group relative flex items-center justify-between p-2 text-sm rounded-lg cursor-pointer hover:bg-slate-200 dark:hover:bg-zinc-800 truncate ${indent} ${currentConvId === c.id ? 'bg-slate-200 dark:bg-zinc-800 font-bold' : ''}">
            <div onclick="selectConversation('${c.id}')" class="truncate pr-6 flex-1">
                ${safeName.innerHTML}
            </div>
            <button onclick="showMoveMenu(event, '${c.id}', '${c.group_name || ''}')" class="absolute right-2 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-slate-700 text-xs">⋯</button>
        </div>
    `;
}

async function showGroupChatList(groupName) {
    const res = await fetch('/conversations');
    const convs = await res.json();
    const chatsInGroup = convs.filter(c => c.group_name === groupName);
    const container = document.getElementById('chat-container');
    
    container.innerHTML = `
        <div class="min-h-full flex flex-col p-6">
            <div class="flex items-center justify-between mb-6">
                <h2 class="text-2xl font-bold">${groupName}</h2>
                <button onclick="newChat()" class="text-sm px-3 py-1 rounded bg-accent text-accentText font-bold hover:opacity-90">← Back</button>
            </div>
            <div class="space-y-2">
                <button onclick="createNewChatInGroup('${groupName}')" class="w-full p-3 rounded-lg border-2 border-dashed border-slate-300 dark:border-grayBorder hover:bg-slate-100 dark:hover:bg-zinc-900 font-bold text-sm mb-4">
                    + New Chat
                </button>
                
                ${chatsInGroup.map(c => {
                    const safeName = document.createElement('div');
                    safeName.textContent = c.name;
                    return `
                    <div class="p-3 rounded-lg hover:bg-slate-200 dark:hover:bg-zinc-800 border border-slate-200 dark:border-grayBorder flex items-center justify-between group relative">
                        <span onclick="selectConversation('${c.id}')" class="chat-name-display cursor-pointer flex-1">${safeName.innerHTML}</span>
                        
                        <input type="text" class="chat-name-input hidden flex-1 p-1 rounded bg-transparent outline-none text-sm" 
                               value="${c.name}" 
                               data-conv-id="${c.id}" 
                               onblur="saveEditChatName(this)" 
                               onkeydown="if(event.key==='Enter') this.blur()">
                        
                        <button onclick="startEditChatName('${c.id}', this.parentElement.querySelector('.chat-name-display'))" 
                                class="ml-2 p-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity hover:scale-110" title="Rename">
                               ✏️
                        </button>
                    </div>
                `;
                }).join('')}
            </div>
        </div>
    `;
}

function startEditChatName(convId, displayElement) {
    const parent = displayElement.parentElement;
    const input = parent.querySelector('.chat-name-input');
    const span = parent.querySelector('.chat-name-display');
    
    span.classList.add('hidden');
    input.classList.remove('hidden');
    input.focus();
    input.select();
}

async function saveEditChatName(inputElement) {
    const convId = inputElement.getAttribute('data-conv-id');
    const newName = inputElement.value.trim();
    const parent = inputElement.parentElement;
    const span = parent.querySelector('.chat-name-display');
    
    if (newName && newName !== span.textContent) {
        try {
            const response = await fetch(`/conversations/${convId}/name?name=${encodeURIComponent(newName)}`, {
                method: 'PUT'
            });
            if (response.ok) {
                span.textContent = newName;
            }
        } catch (err) {
            console.error('Error renaming chat:', err);
        }
    }
    
    inputElement.classList.add('hidden');
    span.classList.remove('hidden');
}

function toggleGroupArrow(groupName) {
    const group = document.getElementById(`group-${groupName}`);
    const toggle = document.getElementById(`group-toggle-${groupName}`);
    group.classList.toggle('hidden');
    toggle.textContent = group.classList.contains('hidden') ? '▶' : '▼';
}

function openCreateGroupModal() {
    document.getElementById('create-group-modal').classList.remove('hidden');
    document.getElementById('group-name-input').focus();
}

function closeCreateGroupModal() {
    document.getElementById('create-group-modal').classList.add('hidden');
    document.getElementById('group-name-input').value = '';
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('create-group-modal').classList.contains('hidden') === false) {
        createGroup();
    }
    if (e.key === 'Escape' && document.getElementById('create-group-modal').classList.contains('hidden') === false) {
        closeCreateGroupModal();
    }
});

async function createGroup() {
    const name = document.getElementById('group-name-input').value.trim();
    if (!name) {
        alert('Group name cannot be empty');
        return;
    }
    try {
        const res = await fetch(`/groups?name=${encodeURIComponent(name)}`, {
            method: 'POST'
        });
        if (res.ok) {
            closeCreateGroupModal();
            loadConversations();
        } else {
            const error = await res.json();
            alert(error.detail || 'Error creating group');
        }
    } catch (error) {
        console.error('Error creating group:', error);
    }
}

async function renameGroup(event, groupName) {
    event.stopPropagation();
    const newName = prompt(`Rename group "${groupName}":`, groupName);
    if (newName && newName.trim() && newName !== groupName) {
        try {
            const res = await fetch(`/groups/${encodeURIComponent(groupName)}?new_name=${encodeURIComponent(newName)}`, {
                method: 'PUT'
            });
            if (res.ok) {
                loadConversations();
            } else {
                const error = await res.json();
                alert(error.detail || 'Error renaming group');
            }
        } catch (error) {
            console.error('Error renaming group:', error);
        }
    }
}

async function deleteGroupMenu(event, groupName) {
    event.stopPropagation();
    const menu = document.createElement('div');
    menu.className = 'fixed bg-white dark:bg-grayPanel border border-slate-300 dark:border-grayBorder rounded shadow-lg z-50 text-xs min-w-max';
    menu.style.top = (event.clientY) + 'px';
    menu.style.left = (event.clientX - 100) + 'px';
    menu.innerHTML = `
        <button class="w-full text-left px-3 py-2 hover:bg-red-200 dark:hover:bg-red-900 text-red-600" onclick="confirmDeleteGroup(event, '${groupName}', 'delete')">Delete Group & Chats</button>
        <button class="w-full text-left px-3 py-2 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="confirmDeleteGroup(event, '${groupName}', 'move')">Delete Group Only (Move Chats Out)</button>
        <button class="w-full text-left px-3 py-2 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="event.stopPropagation(); event.target.closest('div').remove();">Cancel</button>
    `;
    document.body.appendChild(menu);
    setTimeout(() => {
        document.addEventListener('click', function closeMenu(e) {
            if (menu.parentElement && !menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        });
    }, 0);
}

async function confirmDeleteGroup(event, groupName, action) {
    event.stopPropagation();
    try {
        const res = await fetch(`/groups/${encodeURIComponent(groupName)}?action=${action}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            loadConversations();
        }
    } catch (error) {
        console.error('Error deleting group:', error);
    }
}

function showGroupContextMenu(event, groupName) {
    event.preventDefault();
    event.stopPropagation();
    const menu = document.createElement('div');
    menu.className = 'fixed bg-white dark:bg-grayPanel border border-slate-300 dark:border-grayBorder rounded shadow-lg z-50 text-xs';
    menu.style.top = event.clientY + 'px';
    menu.style.left = event.clientX + 'px';
    menu.innerHTML = `
        <button class="w-full text-left px-3 py-2 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="renameGroup(event, '${groupName}')">Rename</button>
        <button class="w-full text-left px-3 py-2 hover:bg-red-200 dark:hover:bg-red-900 text-red-600" onclick="deleteGroupMenu(event, '${groupName}')">Delete</button>
    `;
    document.body.appendChild(menu);
    setTimeout(() => {
        document.addEventListener('click', function closeMenu() {
            if (menu.parentElement) menu.remove();
            document.removeEventListener('click', closeMenu);
        });
    }, 0);
}

function showMoveMenu(event, chatId, currentGroup) {
    event.stopPropagation();
    const menu = document.createElement('div');
    menu.className = 'fixed bg-white dark:bg-grayPanel border border-slate-300 dark:border-grayBorder rounded shadow-lg z-50 text-xs min-w-max';
    menu.style.top = (event.clientY) + 'px';
    menu.style.left = (event.clientX - 100) + 'px';
    let html = `
        <button class="w-full text-left px-3 py-2 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="renameConversation(event, '${chatId}')">Rename</button>
        <div style="border-top: 1px solid #ccc; margin: 2px 0;"></div>
        <div style="padding: 4px 0;">
            <div style="padding: 4px 8px; font-weight: bold; color: #666;">Move to:</div>
            <button class="w-full text-left px-3 py-1 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="moveChat(event, '${chatId}', null)">Outside Groups</button>
    `;
    fetch('/groups')
        .then(r => r.json())
        .then(data => {
            data.groups.forEach(g => {
                if (g !== currentGroup) {
                    html += `<button class="w-full text-left px-3 py-1 hover:bg-slate-200 dark:hover:bg-slate-700" onclick="moveChat(event, '${chatId}', '${g}')">${g}</button>`;
                }
            });
            html += `</div>`;
            html += `<div style="border-top: 1px solid #ccc; margin: 2px 0;"></div>`;
            html += `<button class="w-full text-left px-3 py-2 hover:bg-red-200 dark:hover:bg-red-900 text-red-600" onclick="deleteConversation(event, '${chatId}')">Delete Chat</button>`;
            menu.innerHTML = html;
        });
    menu.innerHTML = html;
    document.body.appendChild(menu);
    setTimeout(() => {
        document.addEventListener('click', function closeMenu(e) {
            if (menu.parentElement && !menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        });
    }, 0);
}

async function renameConversation(event, chatId) {
    event.stopPropagation();
    let currentName = "New Chat";
    const nameElement = Array.from(document.querySelectorAll(`[onclick*="selectConversation('${chatId}')"]`))[0];
    if (nameElement) currentName = nameElement.textContent.trim();
    const newName = prompt(`Rename chat:`, currentName);
    if (newName && newName.trim() && newName !== currentName) {
        try {
            const res = await fetch(`/conversations/${chatId}/name?name=${encodeURIComponent(newName)}`, {
                method: 'PUT'
            });
            if (res.ok) {
                loadConversations();
            } else {
                alert("Failed to rename chat");
            }
        } catch (error) {
            console.error('Error renaming chat:', error);
        }
    }
}

function moveChat(event, chatId, groupName) {
    event.stopPropagation();
    try {
        fetch(`/conversations/${chatId}/move-to-group?group_name=${groupName || ''}`, {
            method: 'POST'
        }).then(r => {
            if (r.ok) {
                loadConversations();
            }
        });
    } catch (error) {
        console.error('Error moving chat:', error);
    }
}

async function deleteConversation(event, id) {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this conversation?")) return;
    const res = await fetch(`/conversations/${id}`, { method: 'DELETE' });
    if (res.ok) {
        if (currentConvId === id) newChat();
        loadConversations();
    }
}

async function selectConversation(id) {
    currentConvId = id;
    localStorage.setItem('last_conversation_id', id);
    updateTokenCounter();
    const res = await fetch(`/history/${id}`);
    const messages = await res.json();
    const container = document.getElementById('chat-container');
    container.innerHTML = '';
    messages.forEach(m => {
        const msgDiv = appendMessage(m.role, m.content);
        const contentDiv = msgDiv.contentDiv;
        // Remove thinking tags and render markdown
        const finalContent = m.role === 'assistant' 
            ? m.content.replace(/<thinking>[\s\S]*?<\/thinking>/, '').trim()
            : m.content;
        contentDiv.innerHTML = marked.parse(finalContent);
        const msgElement = msgDiv.element;
        msgElement.querySelectorAll('pre').forEach((pre) => {
            if (!pre.querySelector('.copy-btn-code')) {
                const code = pre.querySelector('code');
                const copyBtn = document.createElement('button');
                copyBtn.className = 'copy-btn-code absolute top-2 right-2 text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-white opacity-0 hover:opacity-100 transition-opacity';
                copyBtn.textContent = 'Copy';
                copyBtn.onclick = () => {
                    const text = code ? code.innerText : pre.innerText;
                    navigator.clipboard.writeText(text).then(() => {
                        const orig = copyBtn.textContent;
                        copyBtn.textContent = 'Copied!';
                        setTimeout(() => copyBtn.textContent = orig, 2000);
                    });
                };
                pre.style.position = 'relative';
                pre.appendChild(copyBtn);
            }
        });
        msgElement.querySelectorAll('pre code').forEach((el) => { hljs.highlightElement(el); });
        if (window.renderMathInElement) {
            renderMathInElement(contentDiv, { delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false},
                {left: '\\[', right: '\\]', display: true}
            ]});
        }
    });
    loadConversations();
}

function newChat() {
    currentConvId = null;
    localStorage.removeItem('last_conversation_id');
    const container = document.getElementById('chat-container');
    container.innerHTML = `
        <div id="welcome-screen" class="min-h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 transition-opacity duration-500">
            <h1 class="text-3xl font-light italic opacity-60">Let's Get it Done!</h1>
            <p class="text-sm opacity-40 mt-2">Select a model and start chatting</p>
        </div>
    `;
    loadConversations();
}

function appendMessage(role, content) {
    const container = document.getElementById('chat-container');
    const div = document.createElement('div');
    div.className = `flex ${role === 'user' ? 'justify-end' : 'justify-start'}`;
    const messageId = 'msg-' + Math.random().toString(36).substr(2, 9);
    
    let thinking = null;
    let finalContent = content;
    
    if (role === 'assistant') {
        const thinkingMatch = content.match(/<thinking>([\s\S]*?)<\/thinking>/);
        thinking = thinkingMatch ? thinkingMatch[1].trim() : null;
        finalContent = content.replace(/<thinking>[\s\S]*?<\/thinking>/, '').trim();
    }
    
    div.innerHTML = `
        <div class="max-w-3xl p-4 rounded-2xl ${role === 'user' ? 'bg-slate-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100' : 'bg-slate-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100'} group relative">
            <div class="text-xs opacity-70 mb-1 font-bold">${role.toUpperCase()}</div>
            
            ${thinking && role === 'assistant' ? `
            <div class="mb-3 p-2 rounded bg-slate-200/50 dark:bg-zinc-900/50 border-l-2 border-blue-500">
                <button onclick="toggleThinking(this)" class="text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline">▼ Thinking</button>
                <div class="thinking-content hidden text-xs mt-2 opacity-70 whitespace-pre-wrap">
                    ${thinking}
                </div>
            </div>
            ` : ''}

            <div id="${messageId}" class="markdown-content prose prose-slate dark:prose-invert max-w-none">${finalContent}</div>
            
            <div class="absolute top-2 right-2 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                ${role === 'assistant' ? 
                    `<button id="speak-btn-${messageId}" onclick="speakMessage('${messageId}')" class="msg-action-btn text-xs px-2 py-1 rounded bg-black/20 hover:bg-black/40">🔊</button>` : '' 
                }
                <button onclick="copyToClipboard('${messageId}')" class="msg-action-btn text-xs px-2 py-1 rounded bg-black/20 hover:bg-black/40">Copy</button>
            </div>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    
    const contentDiv = div.querySelector(`#${messageId}`);
    return {element: div, contentDiv: contentDiv, finalContent: finalContent};
}

function toggleThinking(button) {
    const content = button.parentElement.querySelector('.thinking-content');
    content.classList.toggle('hidden');
    button.textContent = content.classList.contains('hidden') ? '▼ Thinking' : '▲ Thinking';
}

function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    const text = element.innerText;
    navigator.clipboard.writeText(text).then(() => {}).catch(() => {
        console.error('Failed to copy');
    });
}

function handleDragOver(event) {
    event.preventDefault();
    event.target.classList.add('over');
}

function handleDragLeave(event) {
    event.target.classList.remove('over');
}

function handleDrop(event) {
    event.preventDefault();
    event.target.classList.remove('over');
    
    const files = event.dataTransfer.files;
    if (files.length > 0) {
        const file = files[0];
        const mockEvent = {
            target: {
                files: files
            }
        };
        handleFileUpload(mockEvent);
    }
}

async function handleFileUpload(event) {
    const files = event.target.files || event.dataTransfer.files;
    if (!files || files.length === 0) return;

    const file = files[0];
    const isImage = file.type.startsWith('image/');
    const isText = ['text/plain', 'text/markdown'].includes(file.type);
    const isPdf = file.type === 'application/pdf';

    const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
    const MAX_TEXT_SIZE = 5 * 1024 * 1024;

    if (isImage && file.size > MAX_IMAGE_SIZE) {
        alert('Image must be smaller than 10 MB');
        return;
    }
    if ((isText || isPdf) && file.size > MAX_TEXT_SIZE) {
        alert('File must be smaller than 5 MB');
        return;
    }

    if (isImage) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result;
            uploadedImages.push(base64);
            const input = document.getElementById('user-input');
            input.placeholder = `📎 ${uploadedImages.length} image(s) attached`;
            document.getElementById('file-input').value = '';
        };
        reader.readAsDataURL(file);
    } else if (isText) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target.result;
            const input = document.getElementById('user-input');
            input.value = `[File: ${file.name}]\n\n${content}`;
            document.getElementById('file-input').value = '';
        };
        reader.readAsText(file);
    } else if (isPdf) {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const arrayBuffer = e.target.result;
            try {
                const text = await extractTextFromPDF(arrayBuffer);
                const input = document.getElementById('user-input');
                input.value = `[PDF file: ${file.name}]\n\n${text}`;
                document.getElementById('file-input').value = '';
            } catch (error) {
                console.error('PDF extraction failed:', error);
                const input = document.getElementById('user-input');
                input.value = `[PDF file: ${file.name} - could not extract text]\n\nPlease analyze this PDF file.`;
                document.getElementById('file-input').value = '';
            }
        };
        reader.readAsArrayBuffer(file);
    }
}

async function extractTextFromPDF(arrayBuffer) {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
    document.head.appendChild(script);
    
    return new Promise((resolve, reject) => {
        script.onload = async () => {
            try {
                const pdfjsLib = window['pdfjs-dist/build/pdf'];
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                
                const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
                let fullText = '';
                
                for (let i = 1; i <= pdf.numPages; i++) {
                    const page = await pdf.getPage(i);
                    const textContent = await page.getTextContent();
                    const pageText = textContent.items.map(item => item.str).join(' ');
                    fullText += `\n--- Page ${i} ---\n${pageText}`;
                }
                
                resolve(fullText);
            } catch (error) {
                reject(error);
            }
        };
        script.onerror = () => reject(new Error('Failed to load PDF.js'));
    });
}

function stopGeneration() {
    if (abortController) {
        abortController.abort();
        isStreaming = false;
        document.getElementById('send-btn').disabled = false;
        document.getElementById('btn-icon').textContent = '↑';
        document.getElementById('stop-btn').classList.add('hidden');
    }
}

async function sendMessage() {
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const text = input.value.trim();
    
    if (!text || isStreaming) return;
    
    const welcomeScreen = document.getElementById('welcome-screen');
    if (welcomeScreen) {
        document.getElementById('chat-container').innerHTML = '';
    }

    const model = document.getElementById('model-select').value;
    input.value = '';
    input.style.height = 'auto';
    isStreaming = true;
    sendBtn.disabled = true;
    abortController = new AbortController();
    document.getElementById('stop-btn').classList.remove('hidden');
    document.getElementById('btn-icon').textContent = '◯';
    
    appendMessage('user', text);
    
    const userMsgDivs = document.querySelectorAll('#chat-container > div');
    if (userMsgDivs.length > 0) {
        const lastUserMsg = userMsgDivs[userMsgDivs.length - 1];
        const contentDiv = lastUserMsg.querySelector('.markdown-content');
        if (contentDiv) {
            contentDiv.innerHTML = marked.parse(text);
            lastUserMsg.querySelectorAll('pre').forEach((pre) => {
                if (!pre.querySelector('.copy-btn-code')) {
                    const code = pre.querySelector('code');
                    const copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn-code absolute top-2 right-2 text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-white opacity-0 hover:opacity-100 transition-opacity';
                    copyBtn.textContent = 'Copy';
                    copyBtn.onclick = () => {
                        const text = code ? code.innerText : pre.innerText;
                        navigator.clipboard.writeText(text).then(() => {
                            const orig = copyBtn.textContent;
                            copyBtn.textContent = 'Copied!';
                            setTimeout(() => copyBtn.textContent = orig, 2000);
                        });
                    };
                    pre.style.position = 'relative';
                    pre.appendChild(copyBtn);
                }
            });
            lastUserMsg.querySelectorAll('pre code').forEach((el) => { hljs.highlightElement(el); });
        }
    }

    const history = currentConvId ? await (await fetch(`/history/${currentConvId}`)).json() : [];
    const userMessage = {
        role: 'user', 
        content: text
    };
    
    if (uploadedImages.length > 0) {
        userMessage.images = uploadedImages;
    }
    
    const messages = [...history, userMessage];
    
    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ 
                model, 
                messages, 
                conversation_id: currentConvId,
                context_mode: contextMode,
                context_param_m: contextParamM,
                context_param_n: contextParamN,
                system_prompt: currentSystemPrompt,
                enable_web_search: webSearchEnabled
            }),
            signal: abortController.signal
        });

        if (!response.ok) {
            const error = await response.json();
            appendMessage('assistant', `Error: ${error.detail || 'Request failed'}`);
            isStreaming = false;
            sendBtn.disabled = false;
            return;
        }

        const convIdFromHeader = response.headers.get('X-Conversation-ID');
        if (convIdFromHeader) {
            currentConvId = convIdFromHeader;
            localStorage.setItem('last_conversation_id', convIdFromHeader);
            
            const nextChatGroup = localStorage.getItem('nextChatGroup');
            if (nextChatGroup) {
                await fetch(`/conversations/${currentConvId}/move-to-group?group_name=${encodeURIComponent(nextChatGroup)}`, {
                    method: 'POST'
                });
                localStorage.removeItem('nextChatGroup');
            }
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let msgObj = appendMessage('assistant', '');
        const contentDiv = msgObj.contentDiv;
        let fullText = "";
        let buffer = "";
        let done = false;

        while (!done) {
            const { value, done: streamDone } = await reader.read();

            if (streamDone) break;

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split("\n\n");
            buffer = events.pop() || "";

            for (const event of events) {

                if (event.includes("event: error")) {
                    const errorLine = event
                        .split("\n")
                        .find(line => line.startsWith("data:"));

                    contentDiv.innerHTML =
                        `<div class="text-red-500">
                            Error: ${errorLine?.slice(5) || "Unknown error"}
                        </div>`;

                    done = true;
                    break;
                }
                if (event.includes("data: [DONE]")) {
                    done = true;
                    break;
                }
                const dataLine = event
                    .split("\n")
                    .find(line => line.startsWith("data:"));
                if (dataLine) {
                    // IMPORTANT: do not add spaces/newlines here
                    const chunk = dataLine.substring(5);
                    fullText += chunk;
                    contentDiv.textContent = fullText;
                    document.getElementById('chat-container').scrollTop =
                        document.getElementById('chat-container').scrollHeight;
                }
            }
        }
        
        if (fullText) {
            const finalContent = fullText.replace(/<thinking>[\s\S]*?<\/thinking>/, '').trim();
            contentDiv.innerHTML = marked.parse(finalContent);
            contentDiv.querySelectorAll('pre').forEach((pre) => {
                if (!pre.querySelector('.copy-btn-code')) {
                    const code = pre.querySelector('code');
                    const copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn-code absolute top-2 right-2 text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-white opacity-0 hover:opacity-100 transition-opacity';
                    copyBtn.textContent = 'Copy';
                    copyBtn.onclick = () => {
                        const text = code ? code.innerText : pre.innerText;
                        navigator.clipboard.writeText(text);
                    };
                    pre.style.position = 'relative';
                    pre.appendChild(copyBtn);
                }
            });
            contentDiv.querySelectorAll('pre code').forEach((el) => { hljs.highlightElement(el); });
            if (window.renderMathInElement) {
                renderMathInElement(contentDiv, { delimiters: [
                    {left: '$$', right: '$$', display: true},
                    {left: '$', right: '$', display: false},
                    {left: '\\(', right: '\\)', display: false},
                    {left: '\\[', right: '\\]', display: true}
                ]});
            }
        }

        updateTokenCounter();
    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error('Error:', error);
        }
    } finally {
        isStreaming = false;
        sendBtn.disabled = false;
        document.getElementById('btn-icon').textContent = '↑';
        document.getElementById('stop-btn').classList.add('hidden');
        
        uploadedImages = [];
        const input = document.getElementById('user-input');
        input.placeholder = 'Ask anything...';
    }
}

document.getElementById('user-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

document.getElementById('user-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

async function createNewChatInGroup(groupName) {
    localStorage.setItem('nextChatGroup', groupName);
    newChat();
}

function toggleHub(open) {
  const modal = document.getElementById('more-modal');
  if (modal) {
    if (open) {
      modal.classList.remove('hidden');
    } else {
      modal.classList.add('hidden');
    }
  }
}

const AppModules = {
    "documentation": { url: "/documentation", label: "Documentation", icon: "/assets/icons_document.svg" },
    "voice-chat":    { url: "/voice",         label: "Voice Chat",   icon: "/assets/icons_voice.png" },
    "playground":    { url: "/playground",    label: "Playground",   icon: "/assets/icons_playground.svg" },
    "code-gen":      { url: "/codegen",       label: "Code Gen",     icon: "/assets/icons_code.svg" }
};

function navigateToModule(moduleId, event) {
    const module = AppModules[moduleId];
    if (!module) {
        console.error(`Module ${moduleId} not found in registry.`);
        return;
    }

    const isNewTabRequested = event.ctrlKey || event.metaKey;

    if (isNewTabRequested) {
        window.open(module.url, '_blank');
    } else {
        window.location.href = module.url;
    }
}

function showToast(message, type = 'error') {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 p-4 rounded-md shadow-lg text-white z-50 transition-all duration-300 ${
        type === 'error' ? 'bg-red-500' : 'bg-green-500'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 5000);
}

window.onload = async () => {
    if (sidebarCollapsed) {
        document.getElementById('sidebar').style.width = '0';
        document.getElementById('sidebar').style.overflow = 'hidden';
    }

    await loadSystemPrompts();
    await refreshModelDropdown();

    if (currentConvId) {
    await selectConversation(currentConvId);
    } else {
    const convs = await (await fetch('/conversations')).json();
    if (convs.length > 0) {
        const latest = convs.reduce((prev, curr) =>
        new Date(curr.updated_at) > new Date(prev.updated_at) ? curr : prev
        );
        currentConvId = latest.id;
        localStorage.setItem('last_conversation_id', latest.id);
        await selectConversation(latest.id);
    } else {
        newChat();
    }
    }
    
    await loadConversations();
    if (webSearchEnabled) {
        document.getElementById('web-search-btn').classList.add('active');
    }

    if (currentSystemPrompt) {
        document.getElementById('system-prompt-btn').textContent = `Behavior: ${currentSystemPrompt}`;
    }
    
    document.addEventListener('click', (e) => {
        const contextModal = document.getElementById('context-modal');
        const promptDropdown = document.getElementById('system-prompt-dropdown');
        const moreModal = document.getElementById('more-modal');

        if (!e.target.closest('[onclick*="toggleContext"]') && !e.target.closest('#context-modal')) {
            contextModal.classList.add('hidden');
        }
        if (!e.target.closest('[onclick*="toggleSystemPrompt"]') && !e.target.closest('#system-prompt-dropdown')) {
            promptDropdown.classList.add('hidden');
        }
        if (!e.target.closest('[onclick*="toggleHub"]') && !e.target.closest('#more-modal')) {
            moreModal.classList.add('hidden');
        }
    });
};