(function () {
  const appId = document.body.dataset.interactiveAppId;
  const requestedVersion = new URLSearchParams(window.location.search).get('version');
  const versionQuery = requestedVersion ? `?version=${encodeURIComponent(requestedVersion)}` : '';
  const frame = document.getElementById('interactive-frame');
  const loading = document.getElementById('interactive-loading');
  const title = document.getElementById('interactive-title');
  const version = document.getElementById('interactive-version');
  const resultBox = document.getElementById('interactive-result');
  const downloadButton = document.getElementById('interactive-download');
  const backButton = document.getElementById('interactive-back');
  const answersButton = document.getElementById('interactive-answers');
  const answersPanel = document.getElementById('interactive-answers-panel');
  const answersContent = document.getElementById('interactive-answers-content');
  const answersClose = document.getElementById('interactive-answers-close');
  let app = null;

  async function fetchProtectedBlob(url) {
    const session = EduAI.readSession?.();
    const headers = new Headers();
    if (session?.token) headers.set('Authorization', `Bearer ${session.token}`);
    const response = await fetch(url, { headers, credentials: 'same-origin' });
    if (!response.ok) {
      let message = `Ошибка ${response.status}`;
      try { const body = await response.json(); message = body.detail || message; } catch (_) {}
      throw new Error(message);
    }
    return response.blob();
  }

  async function load() {
    try {
      app = await EduAI.api(`/api/v1/interactive/${encodeURIComponent(appId)}${versionQuery}`);
      title.innerHTML = EduAI.markdown(app.title || 'Интерактивное задание');
      EduAI.renderMath?.(title);
      version.textContent = `Версия v${app.version_no || app.current_version || 1}${app
        .question_count ? ` · ${app.question_count} вопросов` : ''}`;
      if (answersButton) {
        let canViewAnswers = Boolean(app.can_view_answers);
        // Defensive fallback: /auth/session reads the canonical users row by tg_id.
        // This keeps the Teacher button visible even if an older interactive payload was cached.
        if (!canViewAnswers) {
          try {
            const currentUser = await EduAI.api('/api/v1/auth/session');
            canViewAnswers = currentUser?.role === 'parent' || currentUser?.role === 'admin' ||
               Boolean(currentUser?.is_admin);
          } catch (_) {}
        }
        answersButton.hidden = !canViewAnswers;
      }
      frame.hidden = true;
      loading.hidden = false;
      loading.textContent = 'Подготавливаем интерактивное задание…';
      const reveal = () => {
        loading.hidden = true;
        frame.hidden = false;
      };
      frame.addEventListener('load', reveal, { once: true });
      frame.srcdoc = app.html_document || '<!doctype html><p>Нет содержимого</p>';
      // Safety fallback for unusual WebView implementations that do not emit load for srcdoc.
      setTimeout(() => { if (frame.hidden) reveal(); }, 1800);
    } catch (error) {
      loading.textContent = error.message || 'Не удалось загрузить интерактивное задание';
    }
  }

  window.addEventListener('message', async event => {
    if (event.source !== frame.contentWindow) return;
    if (!event.data || event.data.type !== 'eduai-interactive-result') return;
    const payload = event.data.payload || {};
    const safe = {
      score: Number.isFinite(Number(payload.score)) ? Number(payload.score) : 0,
      max_score: Number.isFinite(Number(payload.max_score)) ? Math.max(0, Number(payload.max_score)) : 0,
      completed: Boolean(payload.completed),
      answers: payload.answers && typeof payload.answers === 'object' ? payload.answers : {}
    };
    try {
      const saved = await EduAI.api(`/api/v1/interactive/${encodeURIComponent(appId)}/result`, {
        method: 'POST', body: JSON.stringify(safe)
      });
      resultBox.hidden = false;
      const resultText = saved.max_score > 0
        ? `Результат сохранён: ${saved.score} из ${saved.max_score} (${saved.percent}%).${saved
          .feedback ? ` ${saved.feedback}` : ''}`
        : (saved.feedback || 'Результат интерактивного задания сохранён.');
      resultBox.innerHTML = EduAI.markdown(resultText);
      EduAI.renderMath?.(resultBox);
    } catch (error) {
      // Owners/Teachers can preview apps without having an assignment; this is expected.
      const session = EduAI.readSession?.();
      if (session?.user?.role === 'student') EduAI.toast(error.message, 'error');
    }
  });

  downloadButton.addEventListener('click', async () => {
    try {
      const blob = await fetchProtectedBlob(`/api/v1/interactive/${encodeURIComponent(appId)}/download${versionQuery}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${(app?.title || 'interactive').replace(/[^\p{L}\p{N}._-]+/gu, '_')}.html`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { EduAI.toast(error.message, 'error'); }
  });

  answersButton?.addEventListener('click', async () => {
    answersButton.disabled = true;
    const original = answersButton.textContent;
    answersButton.textContent = 'Готовим ответы…';
    try {
      const data = await EduAI.api(`/api/v1/interactive/${encodeURIComponent(appId)}/answers${versionQuery}`);
      answersContent.innerHTML = EduAI.markdown(data.answers_markdown || 'Ответы не сформированы.');
      EduAI.renderMath?.(answersContent);
      answersPanel.hidden = false;
      answersPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      EduAI.toast(error.message || 'Не удалось получить ответы', 'error');
    } finally {
      answersButton.disabled = false;
      answersButton.textContent = original;
    }
  });

  answersClose?.addEventListener('click', () => { answersPanel.hidden = true; });

  backButton.addEventListener('click', () => {
    const session = EduAI.readSession?.();
    const role = session?.user?.role;
    const target = role === 'student' ? '/student.html' : '/parent.html';
    const chatId = app?.session_id ? `?chat=${encodeURIComponent(app.session_id)}` : '';
    location.href = `${target}${chatId}`;
  });

  load();
})();
