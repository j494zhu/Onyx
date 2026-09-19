/* ══════════════════════════════════════════════════════════════
   自定义背景图 —— 只存在浏览器本地，永远不上传服务器
   ══════════════════════════════════════════════════════════════
   为什么是 IndexedDB 而不是 localStorage：
     localStorage 只能存字符串，图片得先 base64，体积再涨 33%，而配额只有
     5MB 左右 —— 随便一张 4K 壁纸就会 QuotaExceededError。IndexedDB 直接
     存 Blob，不用编码，配额按磁盘算。

   localStorage 里只放一张 96px 宽的缩略图（几 KB）。它是**同步**可读的，
   所以能在 <head> 的预涂脚本里先铺上去顶住首屏，等 IndexedDB 异步读完再
   换成全图。背景本来就要模糊+压暗，这一下换图几乎看不出来。

   服务端那边只记一个 'local' 标记（User.ui_prefs 的 bg.src）。换台设备读
   不到这张图，<html style> 里的内置回退图就直接生效，不需要额外处理。
   ══════════════════════════════════════════════════════════════ */

window.OnyxBg = (function () {
  const DB_NAME = 'onyx-bg';
  const STORE = 'images';
  const KEY = 'custom';
  const THUMB_KEY = 'onyx-bg-thumb';

  const MAX_EDGE = 2560;   // 超过这个长边就降采样：4MB 的原图通常能压到几百 KB
  const QUALITY = 0.82;
  const THUMB_EDGE = 96;

  let objectUrl = null;    // 撤销上一个，避免切图时泄漏

  function openDb() {
    return new Promise((resolve, reject) => {
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
  }

  function tx(mode, fn) {
    return openDb().then(db => new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const req = fn(t.objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }));
  }

  function getBlob() { return tx('readonly', s => s.get(KEY)); }
  function putBlob(blob) { return tx('readwrite', s => s.put(blob, KEY)); }
  function delBlob() { return tx('readwrite', s => s.delete(KEY)); }

  function readThumb() {
    try { return localStorage.getItem(THUMB_KEY); } catch (e) { return null; }
  }

  function writeThumb(dataUrl) {
    try {
      if (dataUrl) localStorage.setItem(THUMB_KEY, dataUrl);
      else localStorage.removeItem(THUMB_KEY);
    } catch (e) { /* 隐私模式下写不进去，无所谓 —— 只是少了防闪烁的占位图 */ }
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

  return {
    /** 有没有同步可用的缩略图（预涂脚本用） */
    thumb: readThumb,

    /** 把 IndexedDB 里的图铺上去；没有就返回 false，让 <html style> 的回退图留着 */
    apply: function () {
      return getBlob().then(blob => {
        if (!blob) return false;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = URL.createObjectURL(blob);
        applyUrl(objectUrl);
        return true;
      }).catch(() => false);
    },

    /** 存一张用户选的图：降采样 → 转 WebP → 写 IndexedDB，顺带写一张缩略图 */
    save: function (file) {
      return blobToCanvas(file, MAX_EDGE)
        .then(canvas => canvasToBlob(canvas, QUALITY)
          .then(blob => putBlob(blob).then(() => blob))
          .then(blob => blobToCanvas(blob, THUMB_EDGE))
          .then(thumbCanvas => {
            writeThumb(thumbCanvas.toDataURL('image/webp', 0.6));
          }))
        .then(() => this.apply());
    },

    /** 清掉本地图（切回内置图时调用） */
    clear: function () {
      writeThumb(null);
      if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
      return delBlob().catch(() => {});
    },

    has: function () { return getBlob().then(b => !!b).catch(() => false); },
  };
})();

// 页面标了 data-bg-local 才去读；其余页面一行 IndexedDB 都不碰。
if (document.documentElement.dataset.bgLocal === '1') {
  window.OnyxBg.apply();
}
