/* ══════════════════════════════════════════════════════════════
   Settings — 外观设置
   ══════════════════════════════════════════════════════════════
   所有控件直接改 <html> 上的 CSS 变量，所以这一页自己就是实时预览。
   改完防抖 400ms，把整份 prefs POST 给 /api/settings/save（整份覆盖，
   和 notebooks / todolists 一个路子）。

   自定义背景图是唯一不进数据库的东西：图片本身交给 bg_local.js 存进
   IndexedDB（最多 100 张），库里只记 bg.src === 'local:<id>'。
   bg.src === 'none' 是纯黑背景 —— 删掉正在用的那张自定义图时切过去。
   ══════════════════════════════════════════════════════════════ */

(function () {
  const root = document.getElementById('settings-root');
  if (!root) return;

  const html = document.documentElement;
  const LOCAL_PREFIX = root.dataset.localPrefix;
  const NONE = root.dataset.noneKey;
  const statusEl = document.getElementById('save-status');

  let prefs = JSON.parse(root.dataset.prefs);

  // ─── 工具 ───────────────────────────────────────────────

  function getPath(obj, path) {
    return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
  }

  function setPath(obj, path, value) {
    const keys = path.split('.');
    const last = keys.pop();
    keys.reduce((o, k) => o[k], obj)[last] = value;
  }

  function showStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.toggle('is-error', !!isError);
    statusEl.classList.add('is-visible');
    clearTimeout(showStatus.timer);
    showStatus.timer = setTimeout(() => statusEl.classList.remove('is-visible'), 1600);
  }

  // ─── 保存 ───────────────────────────────────────────────

  let saveTimer = null;

  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      fetch('/api/settings/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ prefs: prefs }),
      })
        .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
        .then(data => {
          // 服务端会把越界值夹回区间，以它返回的为准
          prefs = data.prefs;
          showStatus('Saved');
        })
        .catch(() => showStatus('Save failed', true));
    }, 400);
  }

  // ─── 应用到页面 ─────────────────────────────────────────

  function applyVars() {
    html.style.setProperty('--lum', prefs.lum);
    html.style.setProperty('--bg-blur', prefs.bg.blur + 'px');
    html.style.setProperty('--bg-dim', prefs.bg.dim);
  }

  function localId(src) {
    return src && src.startsWith(LOCAL_PREFIX) ? src.slice(LOCAL_PREFIX.length) : null;
  }

  function applyBgImage() {
    const id = localId(prefs.bg.src);
    if (id) {
      html.dataset.bgLocal = id;
      // 读不到本地图（比如刚换设备）就退回内置默认图
      window.OnyxBg.apply(id).then(ok => { if (!ok) selectBuiltin(defaultTile(), false); });
    } else if (prefs.bg.src === NONE) {
      selectNone(false);
    } else {
      delete html.dataset.bgLocal;
      const tile = document.querySelector('.bg-tile[data-url][data-src="' + CSS.escape(prefs.bg.src) + '"]');
      if (tile) html.style.setProperty('--bg-image', "url('" + tile.dataset.url + "')");
    }
  }

  // 回退用的格子要和服务端渲染进 <html style> 的那张内置图一致，
  // 否则读不到本地图时画面会先显示回退图、再跳到别的图。
  function defaultTile() {
    return document.querySelector('.bg-tile[data-url][data-src="' + CSS.escape(root.dataset.defaultBg) + '"]')
        || document.querySelector('.bg-tile[data-url]');
  }

  function syncTiles() {
    document.querySelectorAll('.bg-tile[data-src]').forEach(t => {
      t.classList.toggle('is-active', t.dataset.src === prefs.bg.src);
    });
  }

  function formatValue(key, value) {
    if (key === 'bg.blur') return Number(value).toFixed(1) + 'px';
    return Number(value).toFixed(2);
  }

  // ─── 滑块 ───────────────────────────────────────────────

  document.querySelectorAll('input[type="range"][data-key]').forEach(input => {
    const key = input.dataset.key;
    const out = document.getElementById(input.id + '-value');

    function render() {
      if (out) out.textContent = formatValue(key, getPath(prefs, key));
    }

    render();
    input.addEventListener('input', () => {
      setPath(prefs, key, parseFloat(input.value));
      applyVars();
      render();
      save();
    });
  });

  // ─── 字体 ───────────────────────────────────────────────

  document.querySelectorAll('select[data-key]').forEach(select => {
    select.addEventListener('change', () => {
      setPath(prefs, select.dataset.key, select.value);
      // 选中项自己的 style 上就带着那个字体栈，直接拿来用，
      // 不需要在 JS 里再维护一份字体表
      const stack = select.options[select.selectedIndex].style.fontFamily;
      html.style.setProperty('--font-' + select.dataset.role, stack);
      save();
    });
  });

  // ─── 背景图 ─────────────────────────────────────────────

  const grid = document.getElementById('bg-grid');
  const fileInput = document.getElementById('bg-file');
  const uploadTile = document.getElementById('bg-upload-tile');
  const MAX = window.OnyxBg.MAX_COUNT;
  const VISIBLE_ROWS = 3;

  let userCount = 0;
  let tileUrls = [];     // 自定义图格子的 object URL，重绘时统一撤销

  function selectBuiltin(tile, persist) {
    if (!tile) return;
    prefs.bg.src = tile.dataset.src;
    delete html.dataset.bgLocal;
    html.style.setProperty('--bg-image', "url('" + tile.dataset.url + "')");
    syncTiles();
    if (persist !== false) save();
  }

  function selectLocal(id, persist) {
    prefs.bg.src = LOCAL_PREFIX + id;
    html.dataset.bgLocal = id;
    window.OnyxBg.apply(id);
    syncTiles();
    if (persist !== false) save();
  }

  // 纯黑：删掉正在用的自定义图之后的落点
  function selectNone(persist) {
    prefs.bg.src = NONE;
    delete html.dataset.bgLocal;
    html.style.setProperty('--bg-image', 'none');
    syncTiles();
    if (persist !== false) save();
  }

  // 内置图和自定义图都是 .bg-tile[data-src]，一个委托全接住
  grid.addEventListener('click', e => {
    const del = e.target.closest('.bg-del');
    if (del) {
      deleteLocal(del.dataset.id);
      return;
    }
    const tile = e.target.closest('.bg-tile[data-src]');
    if (!tile) return;
    const id = localId(tile.dataset.src);
    if (id) selectLocal(id, true);
    else selectBuiltin(tile, true);
  });

  // 上传格永远是"上传"，不再兼任"切回那张自定义图" —— 原来的 bug 就在这里：
  // 有了一张图之后，点它只会切回去，再也弹不出文件选择。
  uploadTile.addEventListener('click', () => {
    if (userCount >= MAX) {
      showStatus('Limit reached (' + MAX + ' images)', true);
      return;
    }
    fileInput.click();
    // 文件框关掉后焦点会回到上传格，Chrome 会给它套一圈很粗的默认焦点框
    uploadTile.blur();
  });

  fileInput.addEventListener('change', () => {
    let files = Array.from(fileInput.files || []);
    fileInput.value = '';
    if (!files.length) return;

    const room = Math.max(0, MAX - userCount);
    const skipped = Math.max(0, files.length - room);
    files = files.slice(0, room);
    if (!files.length) {
      showStatus('Limit reached (' + MAX + ' images)', true);
      return;
    }

    // 一张一张串行处理：同时解码几十张大图会把内存顶爆
    let lastId = null;
    let failed = 0;
    let chain = Promise.resolve();
    files.forEach((file, i) => {
      chain = chain.then(() => {
        showStatus(files.length > 1 ? 'Processing ' + (i + 1) + '/' + files.length + '…' : 'Processing…');
        return window.OnyxBg.add(file)
          .then(id => { lastId = id; })
          .catch(() => { failed += 1; });
      });
    });

    chain.then(() => renderUserTiles()).then(() => {
      if (lastId) selectLocal(lastId, true);   // 最后一张直接设为背景
      if (failed || skipped) {
        const parts = [];
        if (failed) parts.push(failed + ' could not be read');
        if (skipped) parts.push(skipped + ' over the ' + MAX + '-image limit');
        // save() 的 'Saved' 会在 400ms 后出现，晚一点再显示，免得被它盖掉
        setTimeout(() => showStatus(parts.join(', '), true), lastId ? 900 : 0);
      }
    });
  });

  function deleteLocal(id) {
    if (!id) return;
    const wasActive = prefs.bg.src === LOCAL_PREFIX + id;
    window.OnyxBg.remove(id)
      .then(() => {
        if (wasActive) selectNone(true);
        return renderUserTiles();
      })
      .catch(() => showStatus('Delete failed', true));
  }

  // 细圈 + 悬停时加粗的那一圈 + 叉；动画全在 settings.css 的 .bg-del__* 里
  const DEL_ICON =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<circle class="bg-del__ring" cx="12" cy="12" r="11"/>' +
    '<circle class="bg-del__ring-hot" cx="12" cy="12" r="10.5" pathLength="100"/>' +
    '<path class="bg-del__x" d="M8.75 8.75l6.5 6.5M15.25 8.75l-6.5 6.5"/></svg>';

  function renderUserTiles() {
    return window.OnyxBg.list().then(items => {
      grid.querySelectorAll('.bg-item--user').forEach(n => n.remove());
      tileUrls.forEach(u => URL.revokeObjectURL(u));
      tileUrls = [];

      const frag = document.createDocumentFragment();
      items.forEach(item => {
        const url = URL.createObjectURL(item.tile);
        tileUrls.push(url);

        const wrap = document.createElement('div');
        wrap.className = 'bg-item bg-item--user';

        const tile = document.createElement('button');
        tile.type = 'button';
        tile.className = 'bg-tile';
        tile.dataset.src = LOCAL_PREFIX + item.id;
        tile.style.backgroundImage = "url('" + url + "')";
        tile.title = 'Your image (stays on this device)';
        tile.setAttribute('aria-label', 'Your uploaded image');

        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'bg-del';
        del.dataset.id = item.id;
        del.title = 'Delete this image';
        del.setAttribute('aria-label', 'Delete this uploaded image');
        del.innerHTML = DEL_ICON;

        wrap.append(tile, del);
        frag.appendChild(wrap);
      });
      // 自定义图插在上传格前面（旧的在前、新的紧挨着上传格），上传格永远在最后
      uploadTile.before(frag);

      userCount = items.length;
      const full = userCount >= MAX;
      uploadTile.classList.toggle('is-full', full);
      uploadTile.textContent = full ? 'Full' : 'Upload';
      syncTiles();
    }).catch(() => { /* IndexedDB 不可用（隐私模式）：只剩内置图 */ });
  }

  // 超过三行就不再长高，改成格子内部滚动。列数随宽度变（auto-fill），
  // 格子高度随列宽变（aspect-ratio），所以只能量出来。
  function fitGrid() {
    const tile = grid.querySelector('.bg-tile');
    if (!tile) return;
    const cs = getComputedStyle(grid);
    const gap = parseFloat(cs.rowGap) || 0;
    const pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    grid.style.maxHeight = (tile.offsetHeight * VISIBLE_ROWS + gap * (VISIBLE_ROWS - 1) + pad) + 'px';
  }

  if (window.ResizeObserver) new ResizeObserver(fitGrid).observe(grid);
  fitGrid();

  // ─── 重置 ───────────────────────────────────────────────

  document.getElementById('reset-btn').addEventListener('click', () => {
    fetch('/api/settings/reset', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(() => location.reload())
      .catch(() => showStatus('Reset failed', true));
  });

  // ─── 初始化 ─────────────────────────────────────────────

  applyVars();
  applyBgImage();
  syncTiles();
  renderUserTiles();
})();
