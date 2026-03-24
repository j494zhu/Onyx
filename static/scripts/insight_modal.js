/**
 * 🚀 NEURAL INSIGHT LOGIC
 * Handles the Weekly Report Modal & Data Mapping
 */

async function openWeeklyInsight() {
    const modal = document.getElementById('insight-modal');
    const card = document.getElementById('insight-card');
    
    // 1. 显示模态框 (进入 Loading 状态)
    modal.style.display = 'flex';
    // 简单的入场动画：从 0.9 倍大小放大到 1 倍
    setTimeout(() => { card.style.transform = 'scale(1)'; }, 10);

    // 重置 UI 为 "Loading..." 防止看到上一次的数据
    document.getElementById('card-week-label').innerText = "Establishing Uplink...";
    document.getElementById('card-roast').innerText = "Analyzing neural patterns...";
    
    try {
        // 2. 请求后端 API
        const res = await fetch('/api/generate_weekly_insight', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await res.json();

        // 错误处理
        if (data.status === 'error') {
            alert(data.message);
            closeInsight();
            return;
        }

        // ============================================================
        // 3. 数据映射 (Data Mapping) - 把 JSON 填入 HTML
        // ============================================================

        // A. 基础文本信息
        document.getElementById('card-week-label').innerText = data.week_label || "Unknown Protocol";
        document.getElementById('card-achievement').innerText = data.achievement || "No data.";
        // 注意：后端返回的是 'optimization_protocol'，前端 ID 是 'card-advice'
        document.getElementById('card-advice').innerText = data.optimization_protocol || "No advice generated.";

        // B. [V2.0 新增] 矩阵分析数据
        document.getElementById('card-phase').innerText = `STATUS: ${data.neural_phase || 'CALCULATING'}`;
        document.getElementById('card-dw-ratio').innerText = `${data.deep_work_ratio || 0}%`;
        document.getElementById('card-peak').innerText = data.peak_window || "--:--";
        document.getElementById('card-roast').innerText = `"${data.roast || 'No anomalies detected.'}"`;

        // ============================================================
        // 4. 动态情绪上色 (Dynamic Mood Coloring)
        // ============================================================
        
        // 获取后端返回的颜色，如果没有则默认使用蓝色
        const color = data.primary_mood_color || '#3498db'; 

        // 4.1 顶部颜色条
        const colorBar = document.getElementById('card-color-bar');
        if(colorBar) colorBar.style.backgroundColor = color;

        // 4.2 Phase 标签 (边框 + 文字 + 微透明背景)
        const phaseTag = document.getElementById('card-phase');
        if(phaseTag) {
            phaseTag.style.color = color;
            phaseTag.style.borderColor = color;
            phaseTag.style.backgroundColor = hexToRgba(color, 0.1); // 自定义辅助函数
        }

        // 4.3 Roast 区域 (变成红色或者跟随心情变色)
        // 如果是 'Burnout' (红色)，Roast 区域会显得很危险；如果是 'Flow'，则显得温和
        const roastBox = document.getElementById('card-roast-box');
        if(roastBox) {
            roastBox.style.borderLeftColor = color;
            roastBox.style.backgroundColor = hexToRgba(color, 0.05);
            // 标题颜色也跟着变
            const roastTitle = roastBox.querySelector('div:first-child');
            if(roastTitle) roastTitle.style.color = color;
        }

        // 4.4 标题渐变色 (高级感来源)
        const title = document.getElementById('card-week-label');
        if(title) {
            title.style.backgroundImage = `linear-gradient(45deg, #fff, ${color})`;
            title.style.webkitBackgroundClip = 'text';
            title.style.webkitTextFillColor = 'transparent';
        }

    } catch (e) {
        console.error("Neural Link Failed:", e);
        alert("Neural Link Severed: Check console for details.");
        closeInsight();
    }
}

// 关闭模态框
function closeInsight() {
    const modal = document.getElementById('insight-modal');
    const card = document.getElementById('insight-card');
    
    // 退场动画
    card.style.transform = 'scale(0.9)';
    setTimeout(() => { modal.style.display = 'none'; }, 200);
}

// 辅助函数：把 Hex 颜色转成 RGBA (为了让背景透明)
function hexToRgba(hex, alpha) {
    let c;
    if(/^#([A-Fa-f0-9]{3}){1,2}$/.test(hex)){
        c= hex.substring(1).split('');
        if(c.length== 3){
            c= [c[0], c[0], c[1], c[1], c[2], c[2]];
        }
        c= '0x'+c.join('');
        return 'rgba('+[(c>>16)&255, (c>>8)&255, c&255].join(',')+','+alpha+')';
    }
    return `rgba(52, 152, 219, ${alpha})`; // 默认蓝色
}
