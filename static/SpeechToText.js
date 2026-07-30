async function initMic() {
    // Fetch voice models from backend
    let voiceModels = [];
    try {
        const res = await fetch('/voice-models');
        if (res.ok) {
            voiceModels = await res.json();
        }
    } catch (e) {
        console.warn('Could not fetch voice models', e);
    }

    // Check Web Speech support
    const webSpeechSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

    // Build available methods
    availableSTTMethods = [];
    if (webSpeechSupported) {
        availableSTTMethods.push({ id: 'web-speech', label: 'Web Speech (built‑in)' });
    }
    voiceModels.forEach(vm => {
        availableSTTMethods.push({ id: vm.model, label: `${vm.model} (${vm.provider})` });
    });

    // Load or pick default STT method
    const saved = localStorage.getItem('sttMethod');
    if (saved) {
        // Check if saved method still exists in available
        const found = availableSTTMethods.find(m => m.id === saved);
        sttMethod = found ? found.id : null;
    }
    if (!sttMethod && availableSTTMethods.length > 0) {
        sttMethod = availableSTTMethods[0].id;
        localStorage.setItem('sttMethod', sttMethod);
    }

    // Show/hide mic button
    const micBtn = document.getElementById('mic-btn');
    if (availableSTTMethods.length === 0) {
        micBtn.style.display = 'none';
    } else {
        micBtn.style.display = '';
        updateMicButtonTooltip();
    }
}

function handleMicClick() {
    if (!sttMethod) return;

    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

async function startRecording() {
    const micBtn = document.getElementById('mic-btn');
    if (sttMethod === 'web-speech') {
        // Web Speech API
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false; // we'll restart manually for multiple presses
        recognition.interimResults = false; // only final
        recognition.lang = 'en-US'; // can be made configurable later

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            appendTranscript(transcript);
        };
        recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            if (event.error === 'no-speech' || event.error === 'audio-capture') {
            }
        };
        recognition.onend = () => {
            micBtn.classList.remove('recording');
            isRecording = false;
            updateMicButtonTooltip();
        };

        micBtn.classList.add('recording');
        isRecording = true;
        micBtn.classList.remove('processing');
        updateMicButtonTooltip();
        try {
            await recognition.start();
            // Store recognition instance to abort later if needed
            micRecorder = recognition;
        } catch (e) {
            console.error('Recognition start error:', e);
            micBtn.classList.remove('recording');
            isRecording = false;
            updateMicButtonTooltip();
        }
    } else {
        // Backend STT (e.g., whisper-1)
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaStream = stream;

            const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
            audioChunks = [];

            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };
            recorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await transcribeWithBackend(audioBlob);
                cleanupMedia();
            };

            recorder.start();
            micRecorder = recorder;

            micBtn.classList.add('recording');
            isRecording = true;
            updateMicButtonTooltip();

            // Start silence detection
            startSilenceDetection(stream);
        } catch (err) {
            console.error('Microphone access denied:', err);
            alert('Microphone access denied. Please allow it in browser settings.');
            micBtn.classList.remove('recording');
            isRecording = false;
            updateMicButtonTooltip();
        }
    }
}

function stopRecording() {
    const micBtn = document.getElementById('mic-btn');
    if (sttMethod === 'web-speech' && micRecorder) {
        micRecorder.stop(); // triggers onend
    } else if (micRecorder && micRecorder.state === 'recording') {
        micRecorder.stop();
        clearTimeout(silenceTimeout);
    }
}

function startSilenceDetection(stream) {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = audioContext.createAnalyser();
    const microphone = audioContext.createMediaStreamSource(stream);
    microphone.connect(analyser);
    analyser.fftSize = 256;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    let lastSoundTime = Date.now();
    const SILENCE_DURATION = 2000; // 2 seconds

    const checkSilence = () => {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
            sum += dataArray[i];
        }
        const avg = sum / bufferLength;
        const db = 20 * Math.log10(avg / 255); // rough dBFS

        if (db < silenceThreshold) {
            // silence
            const now = Date.now();
            if (now - lastSoundTime > SILENCE_DURATION && isRecording) {
                // trigger stop
                if (micRecorder && micRecorder.state === 'recording') {
                    micRecorder.stop();
                }
                clearTimeout(silenceTimeout);
                return;
            }
        } else {
            lastSoundTime = Date.now();
        }

        if (isRecording && micRecorder?.state === 'recording') {
            requestAnimationFrame(checkSilence);
        }
    };

    checkSilence();
}

async function transcribeWithBackend(audioBlob) {
    const micBtn = document.getElementById('mic-btn');
    micBtn.classList.remove('recording');
    micBtn.classList.add('processing');
    updateMicButtonTooltip();

    try {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        formData.append('model', sttMethod); // e.g., 'whisper-1'

        const resp = await fetch('/voice/transcribe', {
            method: 'POST',
            body: formData
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Transcription failed');
        }
        const data = await resp.json();
        appendTranscript(data.text);
    } catch (err) {
        console.error('Transcription error:', err);
        alert('Transcription failed: ' + err.message);
    } finally {
        micBtn.classList.remove('processing', 'recording');
        isRecording = false;
        updateMicButtonTooltip();
        cleanupMedia();
    }
}

function appendTranscript(text) {
    if (!text) return;
    const input = document.getElementById('user-input');
    const current = input.value;
    if (current) {
        input.value = current + ' ' + text;
    } else {
        input.value = text;
    }
    // Trigger auto-resize
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
}

function toggleMicDropdown(event) {
    event.preventDefault();
    let dropdown = document.querySelector('.mic-dropdown');
    if (!dropdown) {
        // Create dropdown once
        dropdown = document.createElement('div');
        dropdown.className = 'mic-dropdown';
        document.querySelector('.max-w-4xl.mx-auto.relative').appendChild(dropdown);
    }

    // Populate options
    dropdown.innerHTML = '';
    availableSTTMethods.forEach(method => {
        const btn = document.createElement('button');
        btn.textContent = method.label;
        if (method.id === sttMethod) {
            btn.classList.add('selected');
        }
        btn.onclick = () => {
            sttMethod = method.id;
            localStorage.setItem('sttMethod', sttMethod);
            updateMicButtonTooltip();
            dropdown.style.display = 'none';
        };
        dropdown.appendChild(btn);
    });

    // Show it
    dropdown.style.display = 'block';
    // Position it above the mic button
    const micBtn = document.getElementById('mic-btn');
    const micRect = micBtn.getBoundingClientRect();
    const parentRect = micBtn.parentElement.getBoundingClientRect();
    dropdown.style.bottom = (parentRect.bottom - micRect.top) + 'px';
    dropdown.style.right = (parentRect.right - micRect.right) + 'px';

    // Close on outside click
    function closeDropdown(e) {
        if (!dropdown.contains(e.target) && e.target !== micBtn) {
            dropdown.style.display = 'none';
            document.removeEventListener('click', closeDropdown);
        }
    }
    setTimeout(() => {
        document.addEventListener('click', closeDropdown);
    }, 0);
}

function updateMicButtonTooltip() {
    const btn = document.getElementById('mic-btn');
    if (!btn) return;
    let label = 'Voice input';
    if (sttMethod) {
        const method = availableSTTMethods.find(m => m.id === sttMethod);
        if (method) {
            label = `Voice input (${method.label})`;
        }
    }
    btn.title = label + ' - Right‑click to change';
}

function cleanupMedia() {
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    micRecorder = null;
    audioChunks = [];
    isRecording = false;
    clearTimeout(silenceTimeout);
}

function speakMessage(elementId) {
    const contentDiv = document.getElementById(elementId);
    if (!contentDiv) return;

    // 1. Handle already speaking (Stop if clicked again)
    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
        updateSpeakButtonIcon(elementId, '🔊');
        return;
    }

    // 2. Get text content (ignoring thinking blocks)
    const text = contentDiv.innerText;
    if (!text) return;

    const utterance = new SpeechSynthesisUtterance(text);
    
    // Optional: Customize voice
    utterance.rate = 1.0; // Speed
    utterance.pitch = 1.0; // Tone
    
    // Set the global reference so we can stop it
    currentSpeechUtterance = utterance;

    // UI Update: Change icon to "Stop" while speaking
    updateSpeakButtonIcon(elementId, '⏹️');

    utterance.onend = () => {
        updateSpeakButtonIcon(elementId, '🔊');
    };

    utterance.onerror = () => {
        updateSpeakButtonIcon(elementId, '🔊');
    };

    window.speechSynthesis.speak(utterance);
}

function updateSpeakButtonIcon(elementId, icon) {
    const btn = document.getElementById(`speak-btn-${elementId}`);
    if (btn) btn.textContent = icon;
}

window.addEventListener('load', () => {
    initMic();
});