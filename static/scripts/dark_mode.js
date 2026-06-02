(function () {
  const KEY = 'onyx-dark-mode';
  const root = document.documentElement;
  const mq = window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;

  function syncToggle() {
    const toggle = document.getElementById('dm-toggle');
    if (toggle) toggle.classList.toggle('is-dark', root.classList.contains('dark-mode'));
  }

  function applyDark(on, persist) {
    root.classList.toggle('dark-mode', on);
    if (persist) localStorage.setItem(KEY, on ? '1' : '0');
    syncToggle();
  }

  // The pre-paint script in <head> already set the initial theme on <html>;
  // here we just mirror that state onto the toggle UI once it exists.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncToggle);
  } else {
    syncToggle();
  }

  // Follow the OS theme automatically — but only while the user has not made
  // an explicit choice via the toggle.
  if (mq) {
    const onSystemChange = (e) => {
      if (localStorage.getItem(KEY) === null) applyDark(e.matches, false);
    };
    if (mq.addEventListener) mq.addEventListener('change', onSystemChange);
    else if (mq.addListener) mq.addListener(onSystemChange);
  }

  // Exposed for the toggle's onclick. This is an explicit user choice, so persist it.
  window.toggleDarkMode = function () {
    applyDark(!root.classList.contains('dark-mode'), true);
  };
})();
