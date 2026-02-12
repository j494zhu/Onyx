// --- RECORDER & CLOCK LOGIC ---

// 1. 电子时钟 (每秒刷新)
function updateDigitalClock() {
    const clockEl = document.getElementById('digital-clock');
    if (!clockEl) return;

    const now = new Date();
    const h = now.getHours().toString().padStart(2, '0');
    const m = now.getMinutes().toString().padStart(2, '0');
    const s = now.getSeconds().toString().padStart(2, '0');
    
    // [修改] 秒针样式：
    // font-size: 0.4em (更小)
    // opacity: 0.4 (更淡，几乎隐形)
    // vertical-align: text-top (位于右上方)
    clockEl.innerHTML = `${h}:${m}<span style="font-size: 0.4em; opacity: 0.4; vertical-align: text-top; margin-left: 6px; font-weight: normal;">${s}</span>`;
}
setInterval(updateDigitalClock, 1000);
updateDigitalClock();


// 2. 录制按钮逻辑
let isRecordingSession = false; 

function toggleRecording() {
    const btn = document.getElementById('record-btn');
    const submitBtn = document.getElementById('submit-btn');
    const inputStart = document.getElementById('start_time');
    const inputEnd = document.getElementById('end_time');
    const clockEl = document.getElementById('digital-clock');
    const descInput = document.getElementById('desc_input');

    if (!isRecordingSession) {
        // === START ===
        isRecordingSession = true;
        const now = new Date();
        inputStart.value = formatTime(now);
        
        btn.innerText = "STOP & LOG";
        // [修改] 录制中的颜色：柔和的暗红色，带透明度
        btn.style.backgroundColor = "rgba(229, 115, 115, 0.8)"; 
        btn.style.borderColor = "#e57373";
        // btn.style.color = "white"; // 保持白色文字

        // 时钟微变色提示 (可选，用淡红色)
        clockEl.style.color = "rgba(229, 115, 115, 0.9)"; 

    } else {
        // === STOP ===
        isRecordingSession = false;
        const now = new Date();
        inputEnd.value = formatTime(now);
        
        btn.style.display = "none";
        submitBtn.style.display = "block";
        // 提交按钮保持和默认Start按钮一样的青绿色
        submitBtn.innerText = `CONFIRM LOG (${inputStart.value} - ${inputEnd.value})`;
        
        // 恢复时钟默认颜色
        clockEl.style.color = "rgba(255,255,255,0.85)";
        
        if(descInput) descInput.focus();
    }
}

// (确保 formatTime 函数还在下面)
function formatTime(date) {
    let h = date.getHours();
    let m = date.getMinutes();
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
}