/* ══════════════════════════════════════════════════════════════
   ONYX NEURAL ENGINE — Dashboard Logic
   Unified JS: Clock, Recorder, Notebook, To-Do
   ══════════════════════════════════════════════════════════════ */

// ═══════════════════════════════════════════
//  1. UTILITY FUNCTIONS
// ═══════════════════════════════════════════

function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

function formatTime(date) {
  const h = date.getHours().toString().padStart(2, '0');
  const m = date.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getHistoryBody() {
  return document.getElementById('history-table-body');
}

function reindexEntryRows() {
  const tbody = getHistoryBody();
  if (!tbody) return;
  const rows = tbody.querySelectorAll('tr[data-entry-id]');
  rows.forEach((row, idx) => {
    const indexCell = row.querySelector('.col-index');
    if (indexCell) indexCell.textContent = String(idx + 1);
  });
}

function ensureEmptyRowState() {
  const tbody = getHistoryBody();
  if (!tbody) return;

  const hasRows = tbody.querySelector('tr[data-entry-id]') !== null;
  const emptyRow = document.getElementById('history-empty-row');

  if (hasRows && emptyRow) {
    emptyRow.remove();
  }

  if (!hasRows && !emptyRow) {
    const tr = document.createElement('tr');
    tr.id = 'history-empty-row';
    tr.innerHTML = '<td colspan="5" class="history-empty">— No Records Yet —</td>';
    tbody.appendChild(tr);
  }
}

function buildEntryRow(entry) {
  const tr = document.createElement('tr');
  tr.id = `entry-row-${entry.id}`;
  tr.dataset.entryId = String(entry.id);
  tr.innerHTML = `
    <td class="col-index">1</td>
    <td class="col-desc">${escapeHtml(entry.desc)}</td>
    <td class="col-time">${escapeHtml(entry.start_time)}</td>
    <td class="col-time">${escapeHtml(entry.end_time)}</td>
    <td class="col-del">
      <form action="/api/entries/${entry.id}" method="POST" class="js-delete-form" data-entry-id="${entry.id}" style="margin:0;">
        <button type="submit" class="btn-delete">×</button>
      </form>
    </td>
  `;
  return tr;
}

function appendEntryRow(entry) {
  if (!entry || !entry.id) return;
  const tbody = getHistoryBody();
  if (!tbody) return;

  const existing = tbody.querySelector(`tr[data-entry-id="${entry.id}"]`);
  if (existing) return;

  ensureEmptyRowState();
  const row = buildEntryRow(entry);
  tbody.prepend(row);
  reindexEntryRows();
}

function removeEntryRowById(entryId) {
  const tbody = getHistoryBody();
  if (!tbody) return;

  const row = tbody.querySelector(`tr[data-entry-id="${entryId}"]`);
  if (row) row.remove();

  reindexEntryRows();
  ensureEmptyRowState();
}

async function postFormJson(action, formData) {
  const response = await fetch(action, {
    method: 'POST',
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      Accept: 'application/json',
    },
    body: formData,
  });

  if (!response.ok) {
    throw new Error('Request failed');
  }

  return response.json();
}

function setupAjaxEntryActions() {
  const form = document.getElementById('log-form');
  const tbody = getHistoryBody();
  if (!form || !tbody) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    try {
      const data = await postFormJson(form.action, new FormData(form));
      if (data && data.entry) {
        appendEntryRow(data.entry);
      }

      const submitBtn = document.getElementById('submit-btn');
      const recordBtn = document.getElementById('record-btn');
      const descInput = document.getElementById('desc_input');
      const startInput = document.getElementById('start_time');
      const endInput = document.getElementById('end_time');

      if (submitBtn) submitBtn.style.display = 'none';
      if (recordBtn) {
        recordBtn.style.display = 'block';
        recordBtn.innerHTML = '● Start Session';
      }
      if (descInput) descInput.value = '';
      if (startInput) startInput.value = '';
      if (endInput) endInput.value = '';
      isRecordingSession = false;
    } catch (e) {
      form.submit();
    }
  });

  tbody.addEventListener('submit', async (event) => {
    const deleteForm = event.target.closest('form.js-delete-form');
    if (!deleteForm) return;

    event.preventDefault();

    try {
      const data = await postFormJson(deleteForm.action, new FormData(deleteForm));
      if (data && data.id) {
        removeEntryRowById(String(data.id));
      }
    } catch (e) {
      deleteForm.submit();
    }
  });
}

function setupEventStream() {
  if (!window.EventSource) return;

  const source = new EventSource('/api/events');

  source.addEventListener('entry_created', (event) => {
    try {
      appendEntryRow(JSON.parse(event.data));
    } catch (e) {
      console.error('Failed to parse entry_created event', e);
    }
  });

  source.addEventListener('entry_deleted', (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload && payload.id != null) {
        removeEntryRowById(String(payload.id));
      }
    } catch (e) {
      console.error('Failed to parse entry_deleted event', e);
    }
  });

  source.addEventListener('notebooks_updated', (event) => {
    try {
      applyNotebooksUpdate(JSON.parse(event.data));
    } catch (e) {
      console.error('Failed to parse notebooks_updated event', e);
    }
  });

  source.addEventListener('todos_updated', (event) => {
    try {
      applyTodosUpdate(JSON.parse(event.data));
    } catch (e) {
      console.error('Failed to parse todos_updated event', e);
    }
  });

  source.addEventListener('heartbeat', () => {
    const body = document.body;
    if (body) body.dataset.sseHeartbeatAt = String(Date.now());
  });

  source.onerror = () => {
    // EventSource reconnects automatically; keep this non-fatal.
    console.warn('SSE connection interrupted; waiting for reconnect.');
  };
}


// ═══════════════════════════════════════════
//  2. DIGITAL CLOCK
// ═══════════════════════════════════════════

function updateDigitalClock() {
  const el = document.getElementById('digital-clock');
  if (!el) return;
  const now = new Date();
  const h = now.getHours().toString().padStart(2, '0');
  const m = now.getMinutes().toString().padStart(2, '0');
  el.innerHTML = `${h}<span class="blink-colon">:</span>${m}`;
}

setInterval(updateDigitalClock, 2500);
updateDigitalClock();


// ═══════════════════════════════════════════
//  3. SESSION RECORDER
// ═══════════════════════════════════════════

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
    inputStart.value = formatTime(new Date());
    btn.innerHTML = '<span>■</span> Stop & Log';
    btn.classList.add('is-recording');
    if (clockEl) clockEl.style.color = 'rgba(255,255,255,1)';
  } else {
    // === STOP ===
    isRecordingSession = false;
    const now = new Date();
    inputEnd.value = formatTime(now);
    btn.style.display = 'none';
    btn.classList.remove('is-recording');
    submitBtn.style.display = 'block';
    submitBtn.innerHTML = `Confirm Log`;

    // 显示可编辑的开始/结束时间行（默认填入刚记录的时间，用户可手动修改）
    const timeRow = document.getElementById('time-edit-row');
    if (timeRow) timeRow.style.display = 'flex';

    if (clockEl) clockEl.style.color = 'rgba(255,255,255,0.85)';
    if (descInput) descInput.focus();
  }
}


// ═══════════════════════════════════════════
//  4. NOTEBOOK (multi-notebook + 书签栏)
// ═══════════════════════════════════════════

/* 数据形如 [{id, name, content}]，服务端保证至少有一本。
   正文改动 debounce 后只提交当前这一本；增删改名各走各的接口，
   服务端每次都回完整数组并通过 SSE 广播，跨标签页保持一致。 */

let notebooks = [];
let activeNotebookId = null;
let applyingRemoteNotebook = false;

const ACTIVE_NB_STORAGE_KEY = 'onyx-active-notebook';

function getActiveNotebook() {
  return notebooks.find((b) => b.id === activeNotebookId) || null;
}

function setNotebookStatus(text) {
  const el = document.getElementById('status-book');
  if (el) el.innerText = text;
}

function rememberActiveNotebook(id) {
  try {
    localStorage.setItem(ACTIVE_NB_STORAGE_KEY, id);
  } catch (e) {}
}

// 把当前这本的正文灌回 textarea，并同步"远端基准值"避免触发自动保存
function paintActiveNotebook() {
  const textarea = document.getElementById('notebook_area');
  const book = getActiveNotebook();
  if (!textarea || !book) return;

  const content = book.content || '';
  if (textarea.value !== content) {
    applyingRemoteNotebook = true;
    textarea.value = content;
    applyingRemoteNotebook = false;
  }
  textarea.dataset.lastRemoteValue = content;
}

// ── 渲染书签栏 ──────────────────────────────────────────────

function buildNotebookTab(book) {
  const tab = document.createElement('button');
  tab.type = 'button';
  tab.className = 'nb-tab' + (book.id === activeNotebookId ? ' is-active' : '');
  tab.dataset.id = book.id;
  tab.setAttribute('role', 'tab');
  tab.setAttribute('aria-selected', book.id === activeNotebookId ? 'true' : 'false');
  // 图形上不写名字，名字只在悬停提示和删除确认里出现
  tab.title = book.name;
  tab.setAttribute('aria-label', book.name);

  // 书签形：长方形 + 底边凹进一个三角
  tab.innerHTML =
    '<svg viewBox="0 0 24 24" width="15" height="15" stroke-width="1.7" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>';

  return tab;
}

function renderNotebookTabs() {
  const strip = document.getElementById('nb-tab-strip');
  if (!strip) return;
  strip.innerHTML = '';
  notebooks.forEach((book) => strip.appendChild(buildNotebookTab(book)));

  // 只剩一本时删除按钮置灰（后端也会拒绝）
  const delBtn = document.getElementById('nb-del');
  if (delBtn) {
    delBtn.disabled = notebooks.length <= 1;
    const active = getActiveNotebook();
    delBtn.title = active ? 'Delete "' + active.name + '"' : 'Delete current notebook';
  }
}

// ── 正文自动保存 ────────────────────────────────────────────

let pendingNotebookSave = null;

function saveNotebookContent(id, content) {
  setNotebookStatus('Saving...');
  return fetch('/api/notebooks/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, content: content }),
  })
    .then((r) => r.json())
    .then((data) => {
      setNotebookStatus(
        data.status === 'success' ? 'Saved ' + data.saved_at : 'Error!'
      );
    })
    .catch(() => setNotebookStatus('Error!'));
}

// 立刻把挂起的改动落盘（切换书签、删除、新建之前都要先冲一次，否则会丢字）
function flushNotebookSave() {
  if (!pendingNotebookSave) return;
  const id = pendingNotebookSave.id;
  const content = pendingNotebookSave.content;
  pendingNotebookSave = null;

  const book = notebooks.find((b) => b.id === id);
  if (book) book.content = content;
  saveNotebookContent(id, content);
}

const debouncedNotebookSave = debounce(() => flushNotebookSave(), 1000);

// ── 切换 ────────────────────────────────────────────────────

function switchNotebook(id) {
  if (id === activeNotebookId) return;
  flushNotebookSave();

  activeNotebookId = id;
  rememberActiveNotebook(id);
  paintActiveNotebook();
  renderNotebookTabs();
}

// ── 增 / 删 / 改名 ──────────────────────────────────────────

// 三个结构性接口都回 {notebooks, active_id}，收尾逻辑是同一套
function applyNotebookMutation(data) {
  if (!data || data.status !== 'success') return false;

  notebooks = data.notebooks || notebooks;
  activeNotebookId = data.active_id || activeNotebookId;
  rememberActiveNotebook(activeNotebookId);

  paintActiveNotebook();
  renderNotebookTabs();
  if (data.saved_at) setNotebookStatus('Saved ' + data.saved_at);
  return true;
}

async function createNotebook() {
  flushNotebookSave();
  try {
    const res = await fetch('/api/notebooks/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) {
      setNotebookStatus(data.message || 'Error!');
      return;
    }
    applyNotebookMutation(data);
  } catch (e) {
    setNotebookStatus('Error!');
  }
}

async function deleteNotebook(id) {
  // 被删的那本可能正挂着未保存的改动，直接丢掉，别再写回一本不存在的
  if (pendingNotebookSave && pendingNotebookSave.id === id) {
    pendingNotebookSave = null;
  } else {
    flushNotebookSave();
  }

  try {
    const res = await fetch('/api/notebooks/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id }),
    });
    const data = await res.json();
    if (!res.ok) {
      setNotebookStatus(data.message || 'Error!');
      return;
    }
    applyNotebookMutation(data);
  } catch (e) {
    setNotebookStatus('Error!');
  }
}

// ── 删除确认弹窗 ────────────────────────────────────────────

let confirmResolver = null;

function confirmDialog(message) {
  const overlay = document.getElementById('confirm-overlay');
  const text = document.getElementById('confirm-text');
  const okBtn = document.getElementById('confirm-ok');
  // 弹窗节点不在（比如别的页面复用了本脚本）就退回原生 confirm
  if (!overlay || !text || !okBtn) return Promise.resolve(window.confirm(message));

  text.textContent = message;
  overlay.hidden = false;
  okBtn.focus();

  return new Promise((resolve) => {
    confirmResolver = resolve;
  });
}

function closeConfirmDialog(result) {
  const overlay = document.getElementById('confirm-overlay');
  if (overlay) overlay.hidden = true;
  if (confirmResolver) {
    const resolve = confirmResolver;
    confirmResolver = null;
    resolve(result);
  }
}

function setupConfirmDialog() {
  const overlay = document.getElementById('confirm-overlay');
  if (!overlay) return;

  const ok = document.getElementById('confirm-ok');
  const cancel = document.getElementById('confirm-cancel');
  if (ok) ok.addEventListener('click', () => closeConfirmDialog(true));
  if (cancel) cancel.addEventListener('click', () => closeConfirmDialog(false));

  // 点遮罩空白处 = 取消
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeConfirmDialog(false);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !overlay.hidden) closeConfirmDialog(false);
  });
}

// ── 跨标签页：收到别处推来的变更 ────────────────────────────

function applyNotebooksUpdate(payload) {
  if (!payload || !Array.isArray(payload.notebooks)) return;

  notebooks = payload.notebooks;

  // 当前这本被别的标签页删掉了，就跟着服务端给的 active_id 走
  if (!notebooks.some((b) => b.id === activeNotebookId)) {
    activeNotebookId =
      payload.active_id || (notebooks[0] && notebooks[0].id) || null;
    rememberActiveNotebook(activeNotebookId);
  }

  renderNotebookTabs();
  paintActiveNotebook();

  if (payload.saved_at) setNotebookStatus('Saved ' + payload.saved_at);
}

// ── 初始化 ──────────────────────────────────────────────────

function setupNotebooks() {
  const dataEl = document.getElementById('notebooks-data');
  const textarea = document.getElementById('notebook_area');
  const strip = document.getElementById('nb-tab-strip');
  if (!dataEl || !textarea || !strip) return;

  try {
    const parsed = JSON.parse(dataEl.textContent || '[]');
    if (Array.isArray(parsed)) notebooks = parsed;
  } catch (e) {
    notebooks = [];
  }
  if (!notebooks.length) {
    notebooks = [{ id: '1', name: 'Notebook', content: '' }];
  }

  // 优先恢复上次看的那本；没有或已被删掉就回到第一本
  let restored = null;
  try {
    restored = localStorage.getItem(ACTIVE_NB_STORAGE_KEY);
  } catch (e) {}
  activeNotebookId = notebooks.some((b) => b.id === restored)
    ? restored
    : notebooks[0].id;

  paintActiveNotebook();
  renderNotebookTabs();

  textarea.addEventListener('input', function () {
    if (applyingRemoteNotebook) return;
    pendingNotebookSave = { id: activeNotebookId, content: this.value };
    debouncedNotebookSave();
  });

  // 切换：事件委托，书签每次 render 都会重建
  strip.addEventListener('click', (e) => {
    const tab = e.target.closest('.nb-tab');
    if (tab) switchNotebook(tab.dataset.id);
  });

  const addBtn = document.getElementById('nb-add');
  if (addBtn) addBtn.addEventListener('click', createNotebook);

  // 叉号删的是当前选中的那本；弹窗里会写清楚是哪一本
  const delBtn = document.getElementById('nb-del');
  if (delBtn) {
    delBtn.addEventListener('click', async () => {
      const book = getActiveNotebook();
      if (!book || notebooks.length <= 1) return;
      const ok = await confirmDialog(
        'Delete "' + book.name + '"? Its contents will be permanently lost.'
      );
      if (ok) deleteNotebook(book.id);
    });
  }

  // 关页面前把还没落盘的改动送出去
  window.addEventListener('beforeunload', () => {
    if (!pendingNotebookSave) return;
    try {
      navigator.sendBeacon(
        '/api/notebooks/save',
        new Blob([JSON.stringify(pendingNotebookSave)], {
          type: 'application/json',
        })
      );
    } catch (e) {}
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupAjaxEntryActions();
  setupEventStream();
  ensureEmptyRowState();
  setupTodoList();
  setupConfirmDialog();
  setupNotebooks();
});


// ═══════════════════════════════════════════
//  4b. TO-DO CHECKLIST
// ═══════════════════════════════════════════

let todoState = [];
let applyingRemoteTodos = false;

function makeTodoId() {
  return 't' + Date.now().toString(36) + Math.floor(Math.random() * 1e4).toString(36);
}

function saveTodos() {
  if (applyingRemoteTodos) return;

  const statusSpan = document.getElementById('status-quick');
  if (statusSpan) statusSpan.innerText = 'Saving...';

  fetch('/api/todos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ todos: todoState }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (statusSpan) statusSpan.innerText = 'Saved ' + data.saved_at;
    })
    .catch(() => {
      if (statusSpan) statusSpan.innerText = 'Error!';
    });
}

function renderTodos() {
  const list = document.getElementById('todo-list');
  const empty = document.getElementById('todo-empty');
  if (!list) return;

  list.innerHTML = '';

  if (!todoState.length) {
    if (empty) empty.style.display = 'block';
    updateTodoProgress();
    return;
  }
  if (empty) empty.style.display = 'none';

  todoState.forEach((todo) => {
    const li = document.createElement('li');
    li.className = 'todo-item' + (todo.done ? ' is-done' : '');
    li.dataset.id = todo.id;

    const box = document.createElement('button');
    box.type = 'button';
    box.className = 'todo-item__check';
    box.setAttribute('role', 'checkbox');
    box.setAttribute('aria-checked', String(!!todo.done));
    box.innerHTML = todo.done ? '✓' : '';
    box.addEventListener('click', () => toggleTodo(todo.id));

    const label = document.createElement('span');
    label.className = 'todo-item__text';
    label.textContent = todo.text;
    // Click-to-edit: turn the label into an inline input.
    label.addEventListener('dblclick', () => editTodo(todo.id, label));

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'todo-item__del';
    del.setAttribute('aria-label', 'Delete task');
    del.innerHTML = '×';
    del.addEventListener('click', () => deleteTodo(todo.id));

    li.appendChild(box);
    li.appendChild(label);
    li.appendChild(del);
    list.appendChild(li);
  });

  updateTodoProgress();
}

function updateTodoProgress() {
  const fill = document.getElementById('todo-progress-fill');
  const pctEl = document.getElementById('todo-progress-pct');
  if (!fill || !pctEl) return;

  const total = todoState.length;
  const done = todoState.filter((t) => t.done).length;
  const pct = total ? Math.round((done / total) * 100) : 0;

  // --pct 同时驱动填充宽度和游标头位置（见 dashboard.css）。
  const wrap = fill.closest('.todo-progress');
  if (wrap) {
    wrap.style.setProperty('--pct', pct + '%');
    wrap.classList.toggle('is-zero', pct === 0);
    wrap.classList.toggle('is-complete', pct === 100 && total > 0);
  } else {
    fill.style.width = pct + '%';
  }

  pctEl.textContent = pct + '%';
}

function toggleTodo(id) {
  const todo = todoState.find((t) => t.id === id);
  if (!todo) return;
  todo.done = !todo.done;
  renderTodos();
  saveTodos();
}

function deleteTodo(id) {
  todoState = todoState.filter((t) => t.id !== id);
  renderTodos();
  saveTodos();
}

function addTodo(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) return;
  todoState.push({ id: makeTodoId(), text: trimmed.slice(0, 500), done: false });
  renderTodos();
  saveTodos();
}

function editTodo(id, labelEl) {
  const todo = todoState.find((t) => t.id === id);
  if (!todo) return;

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 500;
  input.className = 'todo-item__edit';
  input.value = todo.text;

  const commit = () => {
    const val = input.value.trim();
    if (val) {
      todo.text = val.slice(0, 500);
    }
    renderTodos();
    saveTodos();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    else if (e.key === 'Escape') { renderTodos(); }
  });

  labelEl.replaceWith(input);
  input.focus();
  input.select();
}

function applyTodosUpdate(payload) {
  if (!payload || !Array.isArray(payload.todos)) return;
  applyingRemoteTodos = true;
  todoState = payload.todos.map((t) => ({
    id: String(t.id),
    text: String(t.text || ''),
    done: !!t.done,
  }));
  renderTodos();
  applyingRemoteTodos = false;

  const statusSpan = document.getElementById('status-quick');
  if (statusSpan && payload.saved_at) statusSpan.innerText = 'Saved ' + payload.saved_at;
}

function setupTodoList() {
  const dataEl = document.getElementById('todos-data');
  if (dataEl) {
    try {
      const parsed = JSON.parse(dataEl.textContent || '[]');
      if (Array.isArray(parsed)) {
        todoState = parsed.map((t) => ({
          id: String(t.id || makeTodoId()),
          text: String(t.text || ''),
          done: !!t.done,
        }));
      }
    } catch (e) {
      console.error('Failed to parse initial todos', e);
    }
  }

  renderTodos();

  const form = document.getElementById('todo-add-form');
  const input = document.getElementById('todo-input');
  if (form && input) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      addTodo(input.value);
      input.value = '';
      input.focus();
    });
  }
}


// ═══════════════════════════════════════════
//  5. PAGE INIT
// ═══════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  /* ── Streak Check-in Toast auto-dismiss ── */
  const $toast = document.getElementById('streak-toast');
  if ($toast && $toast.classList.contains('streak-toast--show')) {
    setTimeout(() => {
      $toast.classList.remove('streak-toast--show');
      $toast.classList.add('streak-toast--hide');
      setTimeout(() => { $toast.remove(); }, 600);
    }, 3500);
  }
});
