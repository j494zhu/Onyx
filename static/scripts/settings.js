/* ══════════════════════════════════════════════════════════════
   Settings — 外观设置
   ══════════════════════════════════════════════════════════════
   所有控件直接改 <html> 上的 CSS 变量，所以这一页自己就是实时预览。
   改完防抖 400ms，把整份 prefs POST 给 /api/settings/save（整份覆盖，
   和 notebooks / todolists 一个路子）。

   自定义背景图是唯一不进数据库的东西：图片本身交给 bg_local.js 存进
   IndexedDB，库里只记 bg.src === 'local'。
   ══════════════════════════════════════════════════════════════ */

(function () {
  const root = document.getElementById('settings-root');
  if (!root) return;

  const html = document.documentElement;
  const LOCAL = root.dataset.localKey;
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

  function applyBgImage() {
    if (prefs.bg.src === LOCAL) {
      html.dataset.bgLocal = '1';
      // 读不到本地图（比如刚换设备）就退回内置默认图
      window.OnyxBg.apply().then(ok => { if (!ok) selectBuiltin(defaultTile(), false); });
    } else {
      delete html.dataset.bgLocal;
      const tile = document.querySelector('.bg-tile[data-src="' + CSS.escape(prefs.bg.src) + '"]');
      if (tile) html.style.setProperty('--bg-image', "url('" + tile.dataset.url + "')");
    }
  }

  // 回退用的格子要和服务端渲染进 <html style> 的那张内置图一致，
  // 否则读不到本地图时画面会先显示回退图、再跳到别的图。
  function defaultTile() {
    return document.querySelector('.bg-tile[data-src="' + CSS.escape(root.dataset.defaultBg) + '"]')
        || document.querySelector('.bg-tile[data-src]');
  }

  function syncTiles() {
    document.querySelectorAll('.bg-tile').forEach(t => {
      const src = t.dataset.src || LOCAL;
      t.classList.toggle('is-active', src === prefs.bg.src);
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

  const fileInput = document.getElementById('bg-file');
  const uploadTile = document.getElementById('bg-upload-tile');
  const clearBtn = document.getElementById('bg-clear');

  function selectBuiltin(tile, persist) {
    if (!tile) return;
    prefs.bg.src = tile.dataset.src;
    delete html.dataset.bgLocal;
    html.style.setProperty('--bg-image', "url('" + tile.dataset.url + "')");
    syncTiles();
    if (persist !== false) save();
  }

  document.querySelectorAll('.bg-tile[data-src]').forEach(tile => {
    tile.addEventListener('click', () => selectBuiltin(tile, true));
  });

  // 上传格：已经有本地图就直接切过去，没有才弹文件选择
  uploadTile.addEventListener('click', () => {
    window.OnyxBg.has().then(has => {
      if (has) {
        prefs.bg.src = LOCAL;
        html.dataset.bgLocal = '1';
        window.OnyxBg.apply();
        syncTiles();
        save();
      } else {
        fileInput.click();
      }
    });
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (!file) return;

    showStatus('Processing…');
    window.OnyxBg.save(file)
      .then(() => {
        prefs.bg.src = LOCAL;
        html.dataset.bgLocal = '1';
        syncTiles();
        refreshUploadTile();
        save();
      })
      .catch(() => showStatus('Could not read that image', true));
  });

  clearBtn.addEventListener('click', () => {
    window.OnyxBg.clear().then(() => {
      refreshUploadTile();
      selectBuiltin(defaultTile(), true);
    });
  });

  function refreshUploadTile() {
    window.OnyxBg.has().then(has => {
      clearBtn.hidden = !has;
      uploadTile.classList.toggle('has-image', has);
      const thumb = window.OnyxBg.thumb();
      uploadTile.style.backgroundImage = has && thumb ? "url('" + thumb + "')" : '';
    });
  }

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
  refreshUploadTile();
})();
