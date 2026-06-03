/* static/scripts/pomodoro.js — backend-synced Pomodoro state machine */

const WORK_TIME = 25 * 60;
const SHORT_BREAK = 3 * 60;
const LONG_BREAK = 15 * 60;
const CYCLES_BEFORE_LONG = 4;

const PHASE_DURATIONS = {
    WORK: WORK_TIME,
    SHORT: SHORT_BREAK,
    LONG: LONG_BREAK,
};

const AUTOSAVE_INTERVAL_MS = 15000;

let pomoTimer = null;
let pomoLeft = WORK_TIME;
let isPomoRunning = false;
let currentPhase = 'WORK';
let cycleCount = 0;
let autosaveHandle = null;
let _stateLoaded = false;

function _phaseDuration(phase) {
    return PHASE_DURATIONS[phase] || WORK_TIME;
}

function nowSeconds() {
    return Date.now() / 1000;
}

function _pomoSnapshot() {
    return {
        remaining_seconds: pomoLeft,
        phase: currentPhase,
        cycle_count: cycleCount,
        running: isPomoRunning,
    };
}

function _saveToBackend() {
    const blob = new Blob([JSON.stringify(_pomoSnapshot())], { type: 'application/json' });
    navigator.sendBeacon('/api/pomodoro/save', blob);
}

function _startAutosave() {
    _stopAutosave();
    autosaveHandle = setInterval(function () {
        if (isPomoRunning) _saveToBackend();
    }, AUTOSAVE_INTERVAL_MS);
}

function _stopAutosave() {
    if (autosaveHandle) {
        clearInterval(autosaveHandle);
        autosaveHandle = null;
    }
}

function _advancePhase(overflowSeconds) {
    var remaining = overflowSeconds;
    while (remaining >= 0) {
        if (currentPhase === 'WORK') {
            cycleCount++;
            if (cycleCount >= CYCLES_BEFORE_LONG) {
                currentPhase = 'LONG';
                cycleCount = 0;
            } else {
                currentPhase = 'SHORT';
            }
        } else {
            currentPhase = 'WORK';
        }
        var nextDuration = _phaseDuration(currentPhase);
        if (remaining < nextDuration) {
            pomoLeft = nextDuration - remaining;
            return;
        }
        remaining -= nextDuration;
    }
    pomoLeft = _phaseDuration(currentPhase);
}

function _updateStatusText() {
    var statusText = document.getElementById('pomo-status-text');
    if (!statusText) return;
    if (currentPhase === 'WORK') {
        statusText.innerText = '>>> READY TO FOCUS <<<';
        statusText.style.color = '#ccc';
    } else if (currentPhase === 'SHORT') {
        statusText.innerText = '>>> STANDBY MODE (SHORT BREAK) <<<';
        statusText.style.color = '#2ecc71';
    } else {
        statusText.innerText = '>>> SYSTEM COOLING (LONG BREAK) <<<';
        statusText.style.color = '#3498db';
    }
}

function applyRestoredState(state, serverNow) {
    if (!state) return;

    pomoLeft = state.remaining_seconds;
    currentPhase = state.phase;
    cycleCount = state.cycle_count;
    isPomoRunning = false;

    if (state.running && state.paused_at) {
        var elapsed = serverNow - state.paused_at;
        if (elapsed > 0) {
            pomoLeft = pomoLeft - Math.floor(elapsed);
            if (pomoLeft <= 0) {
                _advancePhase(-pomoLeft);
            }
        }
    }

    _updateStatusText();
    updateDots();
    updatePomoDisplay();
    _updatePomoButtonToPaused();
    _stateLoaded = true;
}

function _updatePomoButtonToPaused() {
    var btn = document.getElementById('pomo-btn');
    if (!btn) return;
    btn.innerText = (pomoLeft === _phaseDuration(currentPhase) && cycleCount === 0 && currentPhase === 'WORK')
        ? 'INITIALIZE SEQUENCE'
        : 'RESUME';
    btn.style.background = 'transparent';
    btn.style.borderColor = 'rgba(255, 255, 255, 0.2)';
}

function loadPomodoroState() {
    fetch('/api/pomodoro/load')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.state) {
                applyRestoredState(data.state, data.server_now);
            } else {
                _stateLoaded = true;
            }
        })
        .catch(function () {
            _stateLoaded = true;
        });
}

function savePomodoroState() {
    _saveToBackend();
}

window.addEventListener('beforeunload', function () {
    _stopAutosave();
    savePomodoroState();
});

window.addEventListener('DOMContentLoaded', function () {
    loadPomodoroState();
    _startAutosave();
});

function togglePomodoro() {
    var btn = document.getElementById('pomo-btn');

    if (!isPomoRunning) {
        isPomoRunning = true;

        if (currentPhase === 'WORK') {
            btn.innerText = 'PAUSE FOCUS';
        } else {
            btn.innerText = 'PAUSE BREAK';
        }

        btn.style.borderColor = 'rgba(255, 255, 255, 0.5)';

        pomoTimer = setInterval(function () {
            if (pomoLeft > 0) {
                pomoLeft--;
                updatePomoDisplay();
            } else {
                handlePhaseComplete();
            }
        }, 1000);

        _saveToBackend();

    } else {
        clearInterval(pomoTimer);
        pomoTimer = null;
        isPomoRunning = false;
        btn.innerText = 'RESUME';
        btn.style.borderColor = 'rgba(255, 255, 255, 0.2)';
        updatePomoDisplay();

        _saveToBackend();
    }
}

function handlePhaseComplete() {
    clearInterval(pomoTimer);
    pomoTimer = null;
    isPomoRunning = false;

    var btn = document.getElementById('pomo-btn');
    var statusText = document.getElementById('pomo-status-text');

    if (currentPhase === 'WORK') {
        cycleCount++;
        updateDots();

        if (cycleCount >= CYCLES_BEFORE_LONG) {
            currentPhase = 'LONG';
            pomoLeft = LONG_BREAK;
            statusText.innerText = '>>> SYSTEM COOLING (LONG BREAK) <<<';
            statusText.style.color = '#3498db';
            cycleCount = 0;
        } else {
            currentPhase = 'SHORT';
            pomoLeft = SHORT_BREAK;
            statusText.innerText = '>>> STANDBY MODE (SHORT BREAK) <<<';
            statusText.style.color = '#2ecc71';
        }

    } else {
        currentPhase = 'WORK';
        pomoLeft = WORK_TIME;
        statusText.innerText = '>>> READY TO FOCUS <<<';
        statusText.style.color = '#ccc';

        if (cycleCount === 0) updateDots();
    }

    updatePomoDisplay();
    btn.innerText = 'START NEXT PHASE';
    btn.style.background = 'transparent';
    btn.style.borderColor = 'rgba(255, 255, 255, 0.2)';

    _saveToBackend();
}

function updatePomoDisplay() {
    var display = document.getElementById('pomo-timer-display');
    var btn = document.getElementById('pomo-btn');

    var m = Math.floor(pomoLeft / 60);
    var s = pomoLeft % 60;
    display.innerText = m.toString().padStart(2, '0') + ':' + s.toString().padStart(2, '0');

    document.title = '(' + m + ':' + (s < 10 ? '0' : '') + s + ') Onyx';

    var totalTime = _phaseDuration(currentPhase);
    var progress = ((totalTime - pomoLeft) / totalTime) * 100;

    if (btn.innerText !== 'START NEXT PHASE' && btn.innerText !== 'INITIALIZE SEQUENCE') {
        btn.style.background = 'linear-gradient(90deg, rgba(255, 255, 255, 0.15) ' + progress + '%, transparent ' + progress + '%)';
    } else {
        btn.style.background = 'transparent';
    }
}

function updateDots() {
    var dotsContainer = document.getElementById('pomo-cycle-dots');
    if (!dotsContainer) return;

    dotsContainer.innerHTML = '';

    for (var i = 0; i < CYCLES_BEFORE_LONG; i++) {
        var dot = document.createElement('span');
        dot.style.width = '6px';
        dot.style.height = '6px';
        dot.style.borderRadius = '50%';
        dot.style.margin = '0 4px';

        if (i < cycleCount) {
            dot.style.backgroundColor = 'rgba(255, 255, 255, 0.8)';
            dot.style.boxShadow = '0 0 5px rgba(255, 255, 255, 0.5)';
        } else {
            dot.style.backgroundColor = '#333';
            dot.style.boxShadow = 'none';
        }

        dotsContainer.appendChild(dot);
    }
}
