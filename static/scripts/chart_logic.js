/* static/scripts/chart_logic.js */

// --- 全局变量 ---
let chartInstance = null;
let currentChartType = 'doughnut'; // 默认图表类型
let lastChartData = null; // 缓存数据，用于切换图表类型时无需重新请求

// --- 赛博朋克配色方案 (Neon Palette) ---
const neonColors = [
    'rgba(0, 255, 65, 0.7)',   // Matrix Green (代码)
    'rgba(0, 219, 222, 0.7)',  // Cyan (学习)
    'rgba(252, 0, 255, 0.7)',  // Neon Pink (娱乐)
    'rgba(255, 184, 0, 0.7)',  // Cyber Yellow (深工)
    'rgba(145, 71, 255, 0.7)', // Electric Purple (会议)
    'rgba(255, 51, 51, 0.7)'   // Alert Red (杂务)
];

const neonBorders = [
    'rgba(0, 255, 65, 1)',
    'rgba(0, 219, 222, 1)',
    'rgba(252, 0, 255, 1)',
    'rgba(255, 184, 0, 1)',
    'rgba(145, 71, 255, 1)',
    'rgba(255, 51, 51, 1)'
];

/**
 * 1. 切换图表类型 (Doughnut / Bar / Polar)
 */
function setChartType(type) {
    currentChartType = type;
    
    // 更新按钮的高亮状态
    const btns = document.querySelectorAll('.chart-btn');
    btns.forEach(btn => btn.classList.remove('active'));
    
    // 简单的映射逻辑
    if(type === 'doughnut') btns[0].classList.add('active');
    if(type === 'bar') btns[1].classList.add('active');
    if(type === 'polarArea') btns[2].classList.add('active');

    // 如果已经有缓存的数据，立即重绘
    if (lastChartData) {
        renderChart(lastChartData);
    }
}

/**
 * 2. 核心功能: 触发 API 分析 (Initialize Analysis)
 */
async function generateChart() {
    const overlay = document.getElementById('chart-overlay');
    const btn = document.querySelector('.run-analysis-btn');
    const footer = document.getElementById('total-tracked-time');
    
    // UI: 进入 Loading 状态
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="btn-icon">⏳</span> PROCESSING...';
    btn.disabled = true;
    
    try {
        // 发送请求给后端 AI 引擎
        const response = await fetch('/api/visualize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) throw new Error("Analysis Protocol Failed");
        
        const data = await response.json();
        
        // 缓存数据
        lastChartData = data;
        
        // 渲染图表
        renderChart(data);
        
        // UI: 隐藏遮罩层 (淡出动画)
        overlay.style.opacity = '0';
        setTimeout(() => {
            overlay.style.display = 'none';
        }, 400); // 等待 CSS transition 结束
        
        // UI: 更新底部统计
        const hours = Math.floor(data.total_minutes / 60);
        const mins = data.total_minutes % 60;
        footer.innerText = `TOTAL TRACKED: ${hours}H ${mins}M`;

    } catch (err) {
        console.error(err);
        btn.innerHTML = '<span class="btn-icon">⚠️</span> RETRY LINK';
        btn.disabled = false;
        btn.style.borderColor = "#ff3333";
        btn.style.color = "#ff3333";
    }
}

/**
 * 3. 使用 Chart.js 渲染图表
 */
function renderChart(data) {
    const ctx = document.getElementById('distributionChart').getContext('2d');
    
    // 如果已有图表实例，先销毁，防止重影
    if (chartInstance) {
        chartInstance.destroy();
    }

    const palette = getRandomPalette(data.labels.length);
    
    // 配置 Chart.js
    chartInstance = new Chart(ctx, {
        type: currentChartType,
        data: {
            labels: data.labels, // ["Coding", "Sleep", ...]
            datasets: [{
                label: 'Minutes',
                data: data.data,     // [120, 480, ...]
                backgroundColor: palette.bgColors,
                borderColor: palette.borderColors,
                borderWidth: 1,
                hoverOffset: 15
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                animateScale: true,
                animateRotate: true
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: 'rgba(255,255,255,0.7)',
                        font: { 
                            family: "'Consolas', 'Monaco', monospace", 
                            size: 11 
                        },
                        padding: 20,
                        usePointStyle: true // 用小圆点代替方块，更精致
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#00ff41',
                    bodyFont: { family: 'monospace' },
                    borderColor: 'rgba(255,255,255,0.2)',
                    borderWidth: 1
                }
            },
            // 根据图表类型动态调整坐标轴
            scales: currentChartType === 'bar' ? {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: 'rgba(255,255,255,0.5)', font: { family: 'monospace'} }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: 'rgba(255,255,255,0.5)', font: { family: 'monospace'} }
                }
            } : {
                // 环形图和极坐标图不需要轴
                x: { display: false },
                y: { display: false }
            },
            // 环形图特有配置：空心率
            cutout: currentChartType === 'doughnut' ? '70%' : '0%'
        }
    });
}