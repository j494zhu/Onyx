/* ══════════════════════════════════════════════════════════════
   自定义背景图 —— 只存在浏览器本地，永远不上传服务器
   ══════════════════════════════════════════════════════════════
   为什么是 IndexedDB 而不是 localStorage：
     localStorage 只能存字符串，图片得先 base64，体积再涨 33%，而配额只有
     5MB 左右 —— 随便一张 4K 壁纸就会 QuotaExceededError。IndexedDB 直接
     存 Blob，不用编码，配额按磁盘算。

   每张图一条记录，key 是随机 id（[a-z0-9]），值是
     { full: Blob(长边 2560), tile: Blob(长边 480，设置页格子用), created }
   最多 MAX_COUNT 张。设置页格子用 tile 而不是 full：100 张全图同时解码
   会吃掉上 GB 的内存。

   localStorage 里每张图再放一张 96px 宽的缩略图（key 'onyx-bg-thumb:<id>'，
   几 KB）。它是**同步**可读的，所以能在 <head> 的预涂脚本里先铺上去顶住
   首屏，等 IndexedDB 异步读完再换成全图。

   服务端那边只记 'local:<id>'（User.ui_prefs 的 bg.src）。换台设备读不到
   这张图，<html style> 里的内置回退图就直接生效，不需要额外处理。

   旧版只有一张图：key 'custom'，值是裸 Blob，缩略图 key 是 'onyx-bg-thumb'。
   读的时候兼容裸 Blob；缩略图 key 在下面一次性挪到新名字。服务端把旧的
   'local' 标记读成 'local:custom'，所以不需要任何数据迁移。
   ══════════════════════════════════════════════════════════════ */

window.OnyxBg = (function () {
  const DB_NAME = 'onyx-bg';
  const STORE = 'images';
  const THUMB_PREFIX = 'onyx-bg-thumb:';
  const LEGACY_ID = 'custom';
  const LEGACY_THUMB_KEY = 'onyx-bg-thumb';

  const MAX_COUNT = 100;
  const MAX_EDGE = 2560;   // 超过这个长边就降采样：4MB 的原图通常能压到几百 KB
  const QUALITY = 0.82;
  const TILE_EDGE = 480;
  const TILE_QUALITY = 0.75;
  const THUMB_EDGE = 96;

  let objectUrl = null;    // 当前铺在背景上的那张；换图时撤销，避免泄漏
  let objectUrlId = null;

  // 旧版缩略图 key → 新 key（只会真正执行一次）
  try {
    const legacy = localStorage.getItem(LEGACY_THUMB_KEY);
    if (legacy !== null) {
      if (!localStorage.getItem(THUMB_PREFIX + LEGACY_ID)) {
        localStorage.setItem(THUMB_PREFIX + LEGACY_ID, legacy);
      }
      localStorage.removeItem(LEGACY_THUMB_KEY);
    }
  } catch (e) { /* 隐私模式 */ }

  let dbPromise = null;
  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      let req;
      try {
        req = indexedDB.open(DB_NAME, 1);
      } catch (e) {
        reject(e);
        return;
      }
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    dbPromise.catch(() => { dbPromise = null; });
    return dbPromise;
  }

  function tx(mode, fn) {
    return openDb().then(db => new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const req = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(req.result);
      t.onerror = () => reject(t.error || req.error);
      t.onabort = () => reject(t.error || req.error);
    }));
  }

  // 旧版的值是裸 Blob，新版是 {full, tile, created}
  function normalize(value) {
    if (!value) return null;
    if (value instanceof Blob) return { full: value, tile: null, created: 0 };
    if (value.full instanceof Blob) return value;
    return null;
  }

  function getRecord(id) {
    return tx('readonly', s => s.get(id)).then(normalize);
  }

  function getAllRecords() {
    return openDb().then(db => new Promise((resolve, reject) => {
      const out = [];
      const t = db.transaction(STORE, 'readonly');
      const req = t.objectStore(STORE).openCursor();
      req.onsuccess = () => {
        const cur = req.result;
        if (!cur) return;
        const rec = normalize(cur.value);
        if (rec) out.push({ id: String(cur.key), tile: rec.tile || rec.full, created: rec.created || 0 });
        cur.continue();
      };
      t.oncomplete = () => resolve(out);
      t.onerror = () => reject(t.error);
    }));
  }

  function thumbKey(id) { return THUMB_PREFIX + id; }

  function readThumb(id) {
    try { return localStorage.getItem(thumbKey(id)); } catch (e) { return null; }
  }

  function writeThumb(id, dataUrl) {
    try {
      if (dataUrl) localStorage.setItem(thumbKey(id), dataUrl);
      else localStorage.removeItem(thumbKey(id));
    } catch (e) { /* 写不进去无所谓 —— 只是少了防闪烁的占位图 */ }
  }

  // IndexedDB 里已经没有的图，缩略图也顺手清掉（比如别的标签页删过）
  function pruneThumbs(liveIds) {
    try {
      const live = new Set(liveIds);
      const stale = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(THUMB_PREFIX) && !live.has(k.slice(THUMB_PREFIX.length))) stale.push(k);
      }
      stale.forEach(k => localStorage.removeItem(k));
    } catch (e) {}
  }

  function newId() {
    // 时间戳 + 随机串，全小写字母数字，服务端的白名单是 [a-z0-9]{1,32}
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function applyUrl(url) {
    document.documentElement.style.setProperty('--bg-image', "url('" + url + "')");
  }

  function blobToCanvas(blob, maxEdge) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(img.width * scale));
        c.height = Math.max(1, Math.round(img.height * scale));
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        resolve(c);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Not a readable image')); };
      img.src = url;
    });
  }

  function canvasToBlob(canvas, quality) {
    return new Promise((resolve, reject) => {
      canvas.toBlob(b => (b ? resolve(b) : reject(new Error('Encode failed'))), 'image/webp', quality);
    });
  }

  function count() {
    return tx('readonly', s => s.count());
  }

  return {
    MAX_COUNT: MAX_COUNT,

    /** 某张图的同步缩略图（预涂脚本用） */
    thumb: readThumb,

    /** 所有自定义图，按上传时间从旧到新：[{id, tile: Blob, created}] */
    list: function () {
      return getAllRecords().then(items => {
        pruneThumbs(items.map(i => i.id));
        return items.sort((a, b) => a.created - b.created);
      });
    },

    count: count,

    /** 把某张图铺上去；没有就返回 false，让 <html style> 的回退图留着 */
    apply: function (id) {
      if (!id) return Promise.resolve(false);
      return getRecord(id).then(rec => {
        if (!rec) return false;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = URL.createObjectURL(rec.full);
        objectUrlId = id;
        applyUrl(objectUrl);
        return true;
      }).catch(() => false);
    },

    /** 存一张用户选的图：降采样 → WebP → 写 IndexedDB，顺带写缩略图。返回新 id */
    add: function (file) {
      return count().then(n => {
        if (n >= MAX_COUNT) throw new Error('limit');
        return blobToCanvas(file, MAX_EDGE);
      }).then(canvas => canvasToBlob(canvas, QUALITY))
        .then(full => blobToCanvas(full, TILE_EDGE)
          .then(tileCanvas => canvasToBlob(tileCanvas, TILE_QUALITY)
            .then(tile => {
              const id = newId();
              const rec = { full: full, tile: tile, created: Date.now() };
              return tx('readwrite', s => s.put(rec, id)).then(() => {
                // 96px 缩略图从 480px 那张再缩，省一次大图解码
                const scale = THUMB_EDGE / Math.max(tileCanvas.width, tileCanvas.height);
                const c = document.createElement('canvas');
                c.width = Math.max(1, Math.round(tileCanvas.width * Math.min(1, scale)));
                c.height = Math.max(1, Math.round(tileCanvas.height * Math.min(1, scale)));
                c.getContext('2d').drawImage(tileCanvas, 0, 0, c.width, c.height);
                writeThumb(id, c.toDataURL('image/webp', 0.6));
                return id;
              });
            })));
    },

    /** 删除一张：IndexedDB 记录 + localStorage 缩略图 */
    remove: function (id) {
      writeThumb(id, null);
      if (objectUrlId === id && objectUrl) {
        // 先别 revoke：调用方会马上把 --bg-image 换掉，revoke 早了画面会闪一下
        const stale = objectUrl;
        objectUrl = null;
        objectUrlId = null;
        setTimeout(() => URL.revokeObjectURL(stale), 1000);
      }
      return tx('readwrite', s => s.delete(id));
    },

    has: function (id) { return getRecord(id).then(r => !!r).catch(() => false); },
  };
})();

// 页面标了 data-bg-local="<id>" 才去读；其余页面一行 IndexedDB 都不碰。
(function () {
  const id = document.documentElement.dataset.bgLocal;
  if (id) window.OnyxBg.apply(id);
})();
