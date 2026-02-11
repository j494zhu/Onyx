/* * PROJECT: NEURAL AUDIT LOGIC 
 * Handles interaction with the /api/ai/audit endpoint
 */

async function runNeuralAudit() {
    const btn = document.getElementById('audit-btn');
    const contentArea = document.getElementById('hud-content');
    const statusDot = document.getElementById('hud-status-dot');
    const statusText = document.getElementById('hud-status-text');
    
    // [FIX HERE] 关键修复：必须先获取用户选择的语气！
    // 1. 找到被选中的 Radio 按钮
    const toneInput = document.querySelector('input[name="ai_tone"]:checked');
    // 2. 取值（如果没有选中，默认使用 'strict'）
    const selectedTone = toneInput ? toneInput.value : 'strict';

    // --- Loading State ---
    btn.disabled = true;
    btn.innerText = "UPLINKING..."; 
    statusDot.style.backgroundColor = "var(--neon-yellow)";
    statusDot.style.boxShadow = "0 0 10px var(--neon-yellow)";
    statusText.innerText = "Processing";

    try {
        // --- API Request ---
        const response = await fetch('/api/ai/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // 现在 selectedTone 已经定义了，可以放心发送
            body: JSON.stringify({ tone: selectedTone }) 
        });
        
        if (!response.ok) throw new Error("Connection Refused");
        
        const data = await response.json();
        
        // --- Render Data ---
        // Score
        const scoreEl = document.getElementById('hud-score-val');
        scoreEl.innerText = data.score;
        
        // Insight
        document.getElementById('hud-insight-text').innerText = data.insight;
        
        // Warning
        const warnBox = document.getElementById('hud-warning-box');
        if (data.warning && data.warning !== "None") {
            warnBox.style.display = 'flex';
            document.getElementById('hud-warn-text').innerText = data.warning;
        } else {
            warnBox.style.display = 'none';
        }

        // Color Logic
        const colorMap = {
            'green': 'var(--neon-green)',
            'yellow': 'var(--neon-yellow)',
            'red': 'var(--neon-red)'
        };
        const activeColor = colorMap[data.status] || '#fff';

        scoreEl.style.color = activeColor;
        statusDot.style.backgroundColor = activeColor;
        statusDot.style.boxShadow = `0 0 15px ${activeColor}`;
        statusText.innerText = "Online";

        // Show Result
        contentArea.style.display = 'flex';
        btn.innerText = "REFRESH DATA";

    } catch (err) {
        console.error(err);
        btn.innerText = "LINK FAILED";
        statusDot.style.backgroundColor = "var(--neon-red)";
        statusText.innerText = "Error";
        
        // Show Error Message in HUD
        contentArea.style.display = 'flex';
        document.getElementById('hud-insight-text').innerText = "System Failure: " + err.message;
        document.getElementById('hud-score-val').innerText = "ERR";
        // 记得把分数颜色改红，不然还是白色的
        document.getElementById('hud-score-val').style.color = "var(--neon-red)";
        
    } finally {
        btn.disabled = false;
    }
}