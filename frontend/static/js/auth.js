document.addEventListener('DOMContentLoaded', () => {
  const BOT_ATTEMPT_KEY = 'eduai.telegram.bot.login.v1';
  const MANUAL_AUTH_KEY = 'eduai.manual.auth.v1';
  const form = document.getElementById('browser-login');
  const input = document.getElementById('telegram-id');
  const submit = form?.querySelector('button[type="submit"]');
  const telegramBlock = document.getElementById('telegram-progress');
  const telegramButton = document.getElementById('telegram-login');
  const telegramStatus = document.getElementById('telegram-status');
  const missingBlock = document.getElementById('not-registered');
  let pollTimer = null;

  function route(user) {
    location.replace(EduAI.ROLE_PATH[user.role] || '/auth.html');
  }

  function persist(data, source) {
    const telegramPhotoUrl = window.Telegram?.WebApp?.initDataUnsafe?.user?.photo_url ||
      data.telegram_photo_url || '';
    EduAI.saveSession({
      token: data.session_token,
      source,
      telegram_photo_url: telegramPhotoUrl,
      user: {
        tg_id: data.tg_id,
        username: data.username,
        role: data.role,
      },
    });
    sessionStorage.removeItem(BOT_ATTEMPT_KEY);
    sessionStorage.removeItem(MANUAL_AUTH_KEY);
    route(data);
  }

  function readBotAttempt() {
    try {
      return JSON.parse(sessionStorage.getItem(BOT_ATTEMPT_KEY) || 'null');
    } catch (_) {
      sessionStorage.removeItem(BOT_ATTEMPT_KEY);
      return null;
    }
  }

  function saveBotAttempt(attempt) {
    sessionStorage.setItem(BOT_ATTEMPT_KEY, JSON.stringify(attempt));
  }

  function showBotProgress(message) {
    if (telegramBlock) telegramBlock.hidden = false;
    if (telegramStatus) telegramStatus.textContent = message;
  }

  function stopBotPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
  }

  async function pollBotLogin() {
    stopBotPolling();
    const attempt = readBotAttempt();
    if (!attempt) return;

    if (attempt.expires_at && Date.parse(attempt.expires_at) <= Date.now()) {
      sessionStorage.removeItem(BOT_ATTEMPT_KEY);
      showBotProgress('Срок подтверждения истёк. Нажмите «Войти через Telegram Bot» ещё раз.');
      return;
    }

    try {
      const data = await EduAI.api('/api/v1/auth/telegram-bot/status', {
        method: 'POST',
        body: JSON.stringify({
          request_id: attempt.request_id,
          browser_token: attempt.browser_token,
        }),
      });
      if (data.status === 'success') {
        persist(data, 'telegram_bot');
        return;
      }
      if (data.status === 'registration_required') {
        showBotProgress('Telegram подтверждён. Завершите выбор роли в боте, затем вернитесь сюда.');
      } else {
        showBotProgress('Ожидаем подтверждение в Telegram Bot…');
      }
    } catch (error) {
      if ([404, 409, 410].includes(error.status)) {
        sessionStorage.removeItem(BOT_ATTEMPT_KEY);
        showBotProgress(error.message);
        return;
      }
      showBotProgress('Не удалось проверить подтверждение. Повторяем автоматически…');
    }
    pollTimer = setTimeout(pollBotLogin, 1500);
  }

  async function startBotLogin() {
    EduAI.setBusy(telegramButton, true, 'Открываем Telegram…');
    try {
      const attempt = await EduAI.api('/api/v1/auth/telegram-bot/start', { method: 'POST' });
      saveBotAttempt(attempt);
      showBotProgress('Подтвердите вход в Telegram Bot и вернитесь на эту страницу.');
      pollBotLogin();
      window.setTimeout(() => {
        const telegram = window.Telegram?.WebApp;
        if (telegram?.openTelegramLink) telegram.openTelegramLink(attempt.bot_url);
        else window.location.href = attempt.bot_url;
      }, 150);
    } catch (error) {
      EduAI.toast(error.message || 'Не удалось открыть Telegram Bot', 'error');
      EduAI.setBusy(telegramButton, false);
    }
  }

  async function telegramWebAppLogin(initData) {
    if (!initData) return false;
    try {
      const data = await EduAI.api('/api/v1/auth/telegram-webapp', {
        method: 'POST',
        body: JSON.stringify({ init_data_raw: initData }),
      });
      persist(data, 'telegram_webapp');
      return true;
    } catch (_) {
      return false;
    }
  }

  form?.addEventListener('submit', async event => {
    event.preventDefault();
    if (missingBlock) missingBlock.hidden = true;
    const rawId = String(input?.value || '').trim();
    if (!/^\d+$/.test(rawId)) {
      EduAI.toast('Введите корректный Telegram ID', 'error');
      return;
    }

    const tgId = Number(rawId);
    if (!Number.isSafeInteger(tgId) || tgId <= 0) {
      EduAI.toast('Введите корректный Telegram ID', 'error');
      return;
    }

    EduAI.setBusy(submit, true, 'Проверяем…');
    try {
      const data = await EduAI.api('/api/v1/auth/browser-login', {
        method: 'POST',
        body: JSON.stringify({ tg_id: tgId }),
      });
      persist(data, 'telegram_id');
    } catch (error) {
      if (error.status === 404 && missingBlock) missingBlock.hidden = false;
      EduAI.toast(error.message || 'Не удалось войти по Telegram ID', 'error');
    } finally {
      EduAI.setBusy(submit, false);
    }
  });

  telegramButton?.addEventListener('click', startBotLogin);
  window.addEventListener('focus', pollBotLogin);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollBotLogin();
  });

  const telegram = window.Telegram?.WebApp;
  if (telegram) {
    telegram.ready();
    telegram.expand();
  }

  const current = EduAI.readSession();
  if (current?.token) {
    EduAI.api('/api/v1/auth/session')
      .then(route)
      .catch(() => {
        EduAI.clearSession();
        pollBotLogin();
      });
    return;
  }

  const manualAuth = sessionStorage.getItem(MANUAL_AUTH_KEY) === '1';
  if (telegram?.initData && !manualAuth) {
    telegramWebAppLogin(telegram.initData).then(success => {
      if (!success) pollBotLogin();
    });
  } else {
    pollBotLogin();
  }
});
