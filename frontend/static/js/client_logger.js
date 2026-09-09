(function () {
  const ENDPOINT = '/api/v1/auth/frontend-error';
  let sending = false;

  function currentTgId() {
    try {
      const session = JSON.parse(localStorage.getItem('eduai.session.v1') || 'null');
      const saved = Number(session?.user?.tg_id);
      if (Number.isSafeInteger(saved) && saved > 0) return saved;
    } catch (_) {}

    const input = document.getElementById('telegram-id');
    const entered = Number(String(input?.value || '').trim());
    return Number.isSafeInteger(entered) && entered > 0 ? entered : null;
  }

  function send(message, sourceFile, lineNumber) {
    if (sending || !message) return;
    sending = true;
    const body = JSON.stringify({
      tg_id: currentTgId(),
      message: String(message).slice(0, 1000),
      source_file: String(sourceFile || 'frontend').slice(0, 500),
      line_number: Number.isFinite(Number(lineNumber)) ? Number(lineNumber) : 0,
    });

    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {}).finally(() => { sending = false; });
  }

  window.addEventListener('error', event => {
    send(event.message || 'Unknown JavaScript error', event.filename || 'frontend', event.lineno || 0);
  });

  window.addEventListener('unhandledrejection', event => {
    const reason = event.reason;
    const message = reason?.message || String(reason || 'Unhandled promise rejection');
    const stack = String(reason?.stack || '');
    const match = stack.match(/(?:https?:\/\/[^/]+)?\/([^:()]+):(\d+):(?:\d+)/);
    send(message, match?.[1] || 'frontend', Number(match?.[2] || 0));
  });
})();
