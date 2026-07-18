# Onyx "Pulse" 图标 — 图形公式与复现指南

设计工具目录，**不参与应用运行时**。线上资产在 `static/icons/`，由本目录的脚本生成。

## 几何公式（64×64 视口）

- **瓦片**：`rect 64×64, rx=14`，底色默认纯白；描边框 `rect(0.75, 0.75, 62.5, 62.5, rx=13.25)`，颜色 `#e4e7ea`，宽 1.5。
- **波形曲线**（两段三次贝塞尔，圆头线帽）：

  ```
  M 9 36  C 17 16, 25 16, 32 34  C 38 50, 46 50, 55 24
  ```

  线宽：favicon 系（16/32/ico）用 **8**（特粗）；大图标（apple-touch/192/512）用 **4.5**。
- **渐变**：沿 x 轴的双色 linearGradient（objectBoundingBox），起点色→终点色。
- **端点圆点**：圆心 = 曲线终点，半径 4（线宽 8 时）/ 2.6（线宽 4.5 时），填终点色。
- **右侧曲线长度**（可调参数 `t ∈ (0,1]`，默认 1）：对第二段贝塞尔
  `P0=(32,34) P1=(38,50) P2=(46,50) P3=(55,24)` 做 De Casteljau 截断，
  取 `[0,t]` 子曲线：`Q1=lerp(P0,P1,t), Q2=lerp(P1,P2,t), Q3=lerp(P2,P3,t),
  R1=lerp(Q1,Q2,t), R2=lerp(Q2,Q3,t), S=lerp(R1,R2,t)`，
  新控制点 `(P0, Q1, R1, S)`，圆点移到 `S`。

## 光影公式

所有阴影都是与水平线成 **75°** 的平行四边形色带，裁剪进瓦片：
过 `(xc, 32)`、方向 `(cos75°, −sin75°)`（屏幕坐标）、半长 T=60 的直线为边界。
图层顺序恒为：**底色 → 阴影带 → 边框 → 白晕 → 曲线 → 圆点**。

- **白晕（halo）**：曲线下方垫同路径白描边，宽 = 线宽 + 2.5；
  透明度沿 x 渐隐：offset 0–0.45 不透明，0.65 处降为 0。
- **递缩回声（A6/A7）**：左侧实阴影 `#f1efec` 至 `x0`，随后交替
  [白隙, 阴影, 白隙, 阴影, …] 共 8 段，宽度序列（密版，已含 0.85 缩放）：

  ```
  [1.53, 2.21, 1.275, 1.445, 1.02, 0.935, 0.765, 0.68]
  ```

  阴影四级色：`#f3f1ee → #f6f4f1 → #faf8f6 → #fcfbfa`（末段 0.68 宽，细如线）。
  结构右缘 = `boundary` 参数；`x0 = boundary − Σ宽度`。
- **网格（GRID 模板）**：整组绕中心旋转 −8°，两个方向各画间距 10 的细线，
  颜色 `#dbe5d2`，宽 0.8，裁剪进瓦片。

## 保留的预设

| 预设 | 配色（起→终） | 光影 | 白晕 |
|------|--------------|------|------|
| A1   | `#ffcf3f → #ff4d3d` | 无 | 无 |
| A6   | `#FFE100 → #ff4d3d` | 密回声，右缘 64/3 ≈ 21.33 | 有 |
| A7   | `#FFE100 → #ff4d3d` | 密回声，右缘 26 | 有 |
| GRID | `#6bb388 → #b7c95f` | 无（改为 −8° 网格底纹） | 无 |
| **FINAL**（2026-07-18 定稿上线） | `#b7c95f → #6bb488` | 密回声，右缘 64/3 | 有 |

FINAL 附加参数：`trim=0.94`；线宽分档 **<48px 用 9.5，≥48px 用 4.5**。
复现：`python design/icon/make_assets.py FINAL --stroke 9.5 --large-stroke 4.5`

## 使用

```bash
# 预览各预设 SVG（写到本目录 preview_*.svg）
venv/Scripts/python.exe design/icon/icon_svg.py

# 交互调参（浏览器实时预览 + 试戴 favicon；file:// 下标签页不显示 favicon，需走 http）
venv/Scripts/python.exe -m http.server 8898 --directory design/icon
# 打开 http://127.0.0.1:8898/playground.html

# 由预设生成全套线上资产到 static/icons/（favicon.svg + 16/32 PNG + ICO +
# apple-touch-icon 180 + icon-192/512；需要 Pillow）
venv/Scripts/python.exe design/icon/make_assets.py A6
venv/Scripts/python.exe design/icon/make_assets.py A6 --stroke 8 --trim 0.95
```

页面接入：`templates/_icons.html` 已被所有页面 include，资产文件名不变则无需改模板。
