/* ══════════════════════════════════════════════════════════════
   Send Feedback
   前端校验只是为了即时提示；真正的校验和长度限制在服务端
   （services/feedback.py），这里的规则和它保持一致。
   ══════════════════════════════════════════════════════════════ */

(function () {
  const form = document.getElementById('fb-form');
  if (!form) return;

  const MAX = parseInt(form.dataset.max, 10) || 2000;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const msg = document.getElementById('fb-message');
  const nameEl = document.getElementById('fb-name');
  const emailEl = document.getElementById('fb-email');
  const honeypot = document.getElementById('fb-website');
  const counter = document.getElementById('fb-counter');
  const submit = document.getElementById('fb-submit');
  const status = document.getElementById('fb-status');
  const done = document.getElementById('fb-done');

  function setError(field, text) {
    document.getElementById('field-' + field).classList.toggle('has-error', !!text);
    document.getElementById('err-' + field).textContent = text || '';
  }

  function setStatus(text, isError) {
    status.textContent = text || '';
    status.classList.toggle('is-error', !!isError);
  }

  function refresh() {
    const len = msg.value.length;
    counter.textContent = len + ' / ' + MAX;
    counter.classList.toggle('is-near', len > MAX * 0.9);
    submit.disabled = msg.value.trim() === '';
    if (msg.value.trim()) setError('message', '');
  }

  msg.addEventListener('input', refresh);
  emailEl.addEventListener('input', () => setError('email', ''));

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const message = msg.value.trim();
    const email = emailEl.value.trim();
    let ok = true;

    if (!message) { setError('message', 'Please write a message.'); ok = false; }
    if (email && !EMAIL_RE.test(email)) { setError('email', "That doesn't look like an email address."); ok = false; }
    if (!ok) return;

    submit.disabled = true;
    setStatus('Sending…');

    fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({
        message: message,
        name: nameEl.value.trim(),
        email: email,
        website: honeypot.value,
      }),
    })
      .then(r => r.json().catch(() => ({})).then(data => ({ ok: r.ok, data: data })))
      .then(({ ok, data }) => {
        if (!ok) {
          // 服务端的提示（限流、校验）是写给人看的，直接展示
          setStatus(data.message || "Couldn't send — please try again in a moment.", true);
          submit.disabled = false;
          return;
        }
        setStatus('');
        form.hidden = true;
        done.classList.add('is-visible');
      })
      .catch(() => {
        setStatus("Couldn't send — please check your connection and try again.", true);
        submit.disabled = false;
      });
  });

  document.getElementById('fb-again').addEventListener('click', () => {
    form.reset();
    form.hidden = false;
    done.classList.remove('is-visible');
    setStatus('');
    refresh();
    msg.focus();
  });

  refresh();
})();
