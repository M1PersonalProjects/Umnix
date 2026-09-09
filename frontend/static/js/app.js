(function () {
  const SESSION_KEY = 'eduai.session.v1';
  const ROLE_PATH = { student: '/student.html', parent: '/parent.html', admin: '/admin.html' };
  const ROLE_LABELS = { student: 'Ученик', parent: 'Учитель / Родитель', admin: 'Администратор' };
  const roleLabel = role => ROLE_LABELS[role] || role || '';
  const mentorKind = user => user?.mentor_kind === 'parent' ? 'parent' : 'teacher';
  const mentorLabel = user => mentorKind(user) === 'parent' ? 'Родитель' : 'Учитель';

  function applyMentorIdentity(user) {
    if (!user || user.role !== 'parent' || !document.body?.classList.contains('teacher-page')) return;
    const parentMode = mentorKind(user) === 'parent';
    document.body.dataset.mentorKind = parentMode ? 'parent' : 'teacher';
    // The template is written in Teacher wording by default. Only Parent-mode
    // needs adaptation; reversing every occurrence of «Родитель» in Teacher-mode
    // would corrupt neutral copy such as «Учитель или Родитель».
    if (!parentMode) return;
    const pairs = [['Учителями','Родителями'],['Учителем','Родителем'],['Учителю','Родителю'],
      ['Учителя','Родителя'],['Учитель','Родитель'],['учителями','родителями'],['учителем','родителем'],
      ['учителю','родителю'],['учителя','родителя'],['учитель','родитель']];
    const replaceText = value => pairs.reduce((out, pair) => out.split(pair[0]).join(pair[1]), String(value || ''));
    const processRoot = root => {
      if (!root) return;
      if (root.nodeType === Node.TEXT_NODE) {
        if (!root.parentElement?.closest('script,style,template')) root.nodeValue = replaceText(root.nodeValue);
        return;
      }
      if (root.nodeType !== Node.ELEMENT_NODE && root !== document.body) return;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.parentElement?.closest('script,style,template')) nodes.push(node);
      }
      nodes.forEach(node => { node.nodeValue = replaceText(node.nodeValue); });
      root.querySelectorAll?.('[title],[aria-label],[placeholder]').forEach(el => {
        ['title','aria-label','placeholder'].forEach(name => {
          const value = el.getAttribute(name);
          if (value) el.setAttribute(name, replaceText(value));
        });
      });
    };
    processRoot(document.body);
    if (!window.__umnixMentorCopyObserver) {
      window.__umnixMentorCopyObserver = new MutationObserver(mutations => {
        mutations.forEach(mutation => mutation.addedNodes.forEach(processRoot));
      });
      window.__umnixMentorCopyObserver.observe(document.body, { childList:true, subtree:true });
    }
    document.title = replaceText(document.title);
  }
  const MATH_RENDERER_VERSION = '20260812-5';
  let katexPromise = null;
  const BASIC_MATH_COMMAND_PATTERN = [
    'frac', 'sqrt', 'times', 'cdot', 'div', 'text', 'begin', 'end',
    'quad', 'qquad', 'Rightarrow', 'Leftarrow', 'rightarrow', 'leftarrow',
    'pm', 'leq?', 'geq?', 'neq?', 'pi', 'infty', 'left', 'right'
  ].join('|');
  const BARE_BASIC_MATH_RE = new RegExp(`\\\\(?:${BASIC_MATH_COMMAND_PATTERN})\\b`);
  const DOUBLE_BASIC_MATH_RE = new RegExp(
    `\\\\(?=(?:${BASIC_MATH_COMMAND_PATTERN})\\b)`,
    'g'
  );

  function readSession() { try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null'); }
     catch (_) { localStorage.removeItem(SESSION_KEY); return null; } }
  function saveSession(data) { localStorage.setItem(SESSION_KEY, JSON.stringify(data)); }
  function clearSession() { localStorage.removeItem(SESSION_KEY); }

  async function api(path, options = {}) {
    const session = readSession(); const headers = new Headers(options.headers || {});
    if (session?.token) headers.set('Authorization', `Bearer ${session.token}`);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers });
    if (response.status === 401) { clearSession(); if (!location.pathname.includes('auth')) location
      .replace('/auth.html'); }
    if (!response.ok) { let message = `Ошибка ${response.status}`; try { const body = await response
      .json(); message = body.detail || body.message || message; } catch (_) {}
       const error = new Error(message); error.status = response.status; throw error; }
    if (response.status === 204) return null;
    return response.json();
  }

  async function guard(allowedRoles) {
    const session = readSession();
    if (!session?.token) { location.replace('/auth.html'); return null; }
    try {
      const user = await api('/api/v1/auth/session');
      const allowed = allowedRoles.includes(user.role) || (user.is_admin && allowedRoles.includes('admin'));
      const adminAsParent = user.is_admin && allowedRoles.includes('parent');
      if (!allowed && !adminAsParent) {
        toast('У вас нет доступа к этой странице', 'error');
        setTimeout(() => location.replace(ROLE_PATH[user.role] || '/auth.html'), 500);
        return null;
      }
      saveSession({ ...session, user });
      applyMentorIdentity(user);
      document.querySelectorAll('[data-user-name]').forEach(el => el.textContent = user.username ?
         `@${user.username}` : `ID ${user.tg_id}`);
      document.querySelectorAll('[data-admin-only]').forEach(el => el.hidden = !user.is_admin);
      return user;
    } catch (_) { return null; }
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":
      '&#39;', '"':'&quot;' }[ch]));
  }

  function encodeMath(value) { return btoa(unescape(encodeURIComponent(value))); }
  function decodeMath(value) { return decodeURIComponent(escape(atob(value))); }

  function ensureMathStyles() {
    // Основные стили математического рендера находятся в app.css.
  }

  function ensureKatex() {
    if (window.katex) return Promise.resolve(window.katex);
    if (katexPromise) return katexPromise;
    katexPromise = new Promise((resolve, reject) => {
      if (!document.querySelector('link[data-eduai-katex]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.dataset.eduaiKatex = '1';
        link.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css';
        document.head.append(link);
      }
      const existing = document.querySelector('script[data-eduai-katex]');
      if (existing) {
        existing.addEventListener('load', () => resolve(window.katex), { once: true });
        existing.addEventListener('error', reject, { once: true });
        return;
      }
      const script = document.createElement('script');
      script.dataset.eduaiKatex = '1';
      script.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.js';
      script.defer = true;
      script.onload = () => resolve(window.katex);
      script.onerror = reject;
      document.head.append(script);
    });
    return katexPromise;
  }

  function normalizeLatexTransport(value) {
    let text = String(value ?? '');
    // JSON/LLM transport occasionally leaves doubled TeX backslashes.
    // Collapse them only before known TeX delimiters/commands, never globally.
    text = text.replace(/\\\\(?=[()[\]])/g, '\\');
    text = text.replace(DOUBLE_BASIC_MATH_RE, '\\');
    return text;
  }

  function latexFallback(expr) {
    let text = normalizeLatexTransport(expr).trim();
    let previous = null;

    // Resolve nested simple fractions from inside out.
    while (previous !== text) {
      previous = text;
      text = text.replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '($1)/($2)');
    }

    text = text
      .replace(/\\sqrt\s*\[([^\]]+)\]\s*\{([^{}]+)\}/g, 'root[$1]($2)')
      .replace(/\\sqrt\s*\{([^{}]+)\}/g, '√($1)')
      .replace(/\\text\s*\{([^{}]*)\}/g, '$1')
      .replace(/\\(?:quad|qquad)\b/g, ' ')
      .replace(/\\Rightarrow\b/g, ' ⇒ ')
      .replace(/\\Leftarrow\b/g, ' ⇐ ')
      .replace(/\\rightarrow\b/g, ' → ')
      .replace(/\\leftarrow\b/g, ' ← ')
      .replace(/\\times\b/g, '×')
      .replace(/\\cdot\b/g, '·')
      .replace(/\\div\b/g, ':')
      .replace(/\\pm\b/g, '±')
      .replace(/\\leq?\b/g, '≤')
      .replace(/\\geq?\b/g, '≥')
      .replace(/\\neq?\b/g, '≠')
      .replace(/\\pi\b/g, 'π')
      .replace(/\\infty\b/g, '∞')
      .replace(/\\begin\{cases\}|\\end\{cases\}/g, '')
      .replace(/\\(?:left|right)\b/g, '')
      .replace(/\\\\/g, '\n')
      .replace(/[{}]/g, '');

    // Never expose remaining TeX command names in fallback.
    text = text.replace(/\\[A-Za-z]+/g, '');
    return text.replace(/[ \t]{2,}/g, ' ').trim();
  }

  function renderMath(root = document) {
    const nodes = [];
    if (root?.matches?.('[data-eduai-math]')) nodes.push(root);
    if (root?.querySelectorAll) nodes.push(...root.querySelectorAll('[data-eduai-math]'));
    if (!nodes.length) return;

    ensureKatex().then(katex => {
      nodes.forEach(node => {
        if (node.dataset.rendered === '1') return;
        const source = decodeMath(node.dataset.eduaiMath || '');
        try {
          node.innerHTML = katex.renderToString(source, {
            displayMode: node.dataset.display === '1',
            throwOnError: true,
            strict: 'warn',
            trust: false,
            output: 'htmlAndMathml'
          });
          node.dataset.rendered = '1';
        } catch (_) {
          node.textContent = latexFallback(source);
          node.classList.add('math-fallback');
          node.dataset.rendered = 'fallback';
        }
      });
    }).catch(() => {
      nodes.forEach(node => {
        if (node.dataset.rendered) return;
        node.textContent = latexFallback(decodeMath(node.dataset.eduaiMath || ''));
        node.classList.add('math-fallback');
        node.dataset.rendered = 'fallback';
      });
    });
  }

  function protectBareLatex(text, protect) {
    // Handle legacy/model output where TeX commands were emitted without delimiters.
    // Process line by line so normal prose/URLs remain untouched.
    return text.split('\n').map(line => {
      if (!BARE_BASIC_MATH_RE.test(line)) {
        return line;
      }
      // If a line contains a TeX command, treat the mathematical tail as inline math.
      // This is intentionally conservative and does not touch URLs or code (already protected).
      const first = line.search(BARE_BASIC_MATH_RE);
      let start = first;
      while (start > 0 && !/[,:;.!?]\s/.test(line.slice(start - 2, start + 1))) start--;
      const prefix = line.slice(0, start);
      const expr = line.slice(start).trim();
      return prefix + protect(`<span class="math-inline" data-eduai-math="${encodeMath(expr)}
        " data-display="0"></span>`);
    }).join('\n');
  }

  function markdown(value) {
    const raw = normalizeLatexTransport(String(value ?? ''));
    const protectedParts = [];
    const protect = html => {
      const token = `@@EDUAI_${protectedParts.length}@@`;
      protectedParts.push(html);
      return token;
    };

    // Protect code before any mathematical processing.
    let text = raw.replace(/```([\s\S]*?)```/g, (_, code) =>
      protect(`<pre class="eduai-code"><code>${escapeHtml(code.replace(/^\n|\n$/g, ''))}</code></pre>`)
    );
    text = text.replace(/`([^`]+)`/g, (_, code) =>
      protect(`<code class="rounded bg-black/20 px-1">${escapeHtml(code)}</code>`)
    );

    // Explicit display and inline math.
    text = text.replace(/\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$/g, (_, a, b) =>
      protect(`<span class="math-display" data-eduai-math="${encodeMath(a || b || '')}" data-display="1"></span>`)
    );
    text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, expr) =>
      protect(`<span class="math-inline" data-eduai-math="${encodeMath(expr)}" data-display="0"></span>`)
    );

    // Legacy/bare TeX.
    text = protectBareLatex(text, protect);

    let safe = escapeHtml(text);
    safe = safe
      .replace(/^### (.+)$/gm, '<strong class="block text-base mt-2">$1</strong>')
      .replace(/^## (.+)$/gm, '<strong class="block text-lg mt-2">$1</strong>')
      .replace(/^# (.+)$/gm, '<strong class="block text-xl mt-2">$1</strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^[-•] (.+)$/gm, '<span class="block pl-3">• $1</span>')
      .replace(/\n/g, '<br>');

    protectedParts.forEach((html, index) => {
      safe = safe.replace(`@@EDUAI_${index}@@`, html);
    });

    queueMicrotask(() => renderMath(document));
    return safe;
  }

  function installMathObserver() {
    if (!document.body || window.__eduaiMathObserver) return;
    const observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) renderMath(node);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    window.__eduaiMathObserver = observer;
    renderMath(document);
  }

  function toast(message, type = 'info') {
    let stack = document.querySelector('.toast-stack');
    if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; document.body.append(stack); }
    const item = document.createElement('div'); item.className = `toast ${type}`; item
      .setAttribute('role', 'status'); item.textContent = message;
    stack.append(item); setTimeout(() => item.remove(), 4200);
  }

  function formatDate(value) { if (!value) return '—'; return new Intl.DateTimeFormat('ru-RU', {
     dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)); }
  function setBusy(button, busy, label = 'Подождите…') { if (!button) return; if (busy) { button.dataset
    .label = button.innerHTML; button.disabled = true; button.textContent = label; } else { button
    .disabled = false; if (button.dataset.label) button.innerHTML = button.dataset.label; } }
  function setFormDisabled(form, disabled) {
    if (!form) return;
    form.classList.toggle('is-submitting', Boolean(disabled));
    form.querySelectorAll('input, textarea, select, button').forEach(element => {
      if (element.closest('[data-thinking-cancel]')) return;
      element.disabled = Boolean(disabled);
    });
  }
  function openModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.add('open');
    document.body.classList.add('eduai-modal-open');
  }
  function closeModal(id) {
    document.getElementById(id)?.classList.remove('open');
    if (!document.querySelector('.modal-backdrop.open')) document.body.classList.remove('eduai-modal-open');
  }
  async function logout() {
    try {
      await api('/api/v1/auth/logout', { method: 'POST' });
    } catch (_) {
      // Локальный выход должен работать даже при недоступном сервере.
    } finally {
      clearSession();
      sessionStorage.setItem('eduai.manual.auth.v1', '1');
      location.replace('/auth.html');
    }
  }

  let activeThinkingWidgets = 0;

  function startThinking(label = 'Umnix думает', options = {}) {
    const widget = document.createElement('div');
    widget.className = 'thinking-widget glass-strong';
    widget.setAttribute('role', 'status');
    const canCancel = typeof options.onCancel === 'function';
    widget.innerHTML = `<span class="thinking-orb"></span><div><strong>${escapeHtml(label)}
      </strong><p class="muted text-xs">Пожалуйста, не закрывайте страницу · <span data-thinking-timer>
      00:00</span></p></div>${canCancel ?
       '<button type="button" class="btn-secondary thinking-cancel" data-thinking-cancel>Остановить</button>' : ''}`;
    document.body.append(widget);
    activeThinkingWidgets += 1;
    document.body.classList.add('ai-thinking');

    const cancelButton = widget.querySelector('[data-thinking-cancel]');
    cancelButton?.addEventListener('click', () => {
      cancelButton.disabled = true;
      cancelButton.textContent = 'Останавливаем…';
      try { options.onCancel(); } catch (_) {}
    });

    const started = Date.now();
    const timer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      const timerLabel = widget.querySelector('[data-thinking-timer]');
      if (timerLabel) timerLabel.textContent = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:
        ${String(elapsed % 60).padStart(2, '0')}`;
    }, 1000);

    let stopped = false;
    return () => {
      if (stopped) return;
      stopped = true;
      clearInterval(timer);
      widget.remove();
      activeThinkingWidgets = Math.max(0, activeThinkingWidgets - 1);
      if (!activeThinkingWidgets) document.body.classList.remove('ai-thinking');
    };
  }

  function initShell() {
    const sidebar = document.querySelector('.sidebar'); const backdrop = document.querySelector('.backdrop');
    const close = () => { sidebar?.classList.remove('open'); backdrop?.classList.remove('open'); };
    document.querySelector('.menu-toggle')?.addEventListener('click', () => { sidebar?.classList
      .toggle('open'); backdrop?.classList.toggle('open'); });
    backdrop?.addEventListener('click', close);
    const sectionStorageKey = `eduai.ui.section:${location.pathname}`;
    const activateSection = id => {
      if (!id || !document.getElementById(id)) return;
      document.body.dataset.activeSection = id;
      document.querySelectorAll('[data-section]').forEach(item => item.classList.toggle('active', item
        .dataset.section === id));
      document.querySelectorAll('.page-section').forEach(section => section.classList.toggle('active',
         section.id === id));
      try { localStorage.setItem(sectionStorageKey, id); } catch (_) {}
      close();
    };
    document.querySelectorAll('[data-section]').forEach(link => link.addEventListener('click', () =>
       activateSection(link.dataset.section)));
    document.querySelectorAll('[data-close-modal]').forEach(button => button.addEventListener('click',
       () => closeModal(button.dataset.closeModal)));
    document.querySelectorAll('.modal-backdrop').forEach(modal => modal.addEventListener('click',
       event => { if (event.target === modal) { modal.classList.remove('open'); if (!document
      .querySelector('.modal-backdrop.open')) document.body.classList.remove('eduai-modal-open'); } }));
    document.querySelectorAll('[data-logout]').forEach(button => button.addEventListener('click', logout));
    const initialSection = document.querySelector('.page-section.active')?.id;
    const requestedSection = new URLSearchParams(location.search).get('section');
    let savedSection = null;
    try { savedSection = localStorage.getItem(sectionStorageKey); } catch (_) {}
    const targetSection = requestedSection && document.getElementById(requestedSection)
      ? requestedSection
      : (savedSection && document.getElementById(savedSection) ? savedSection : initialSection);
    activateSection(targetSection);
  }


  function syncViewportHeight() {
    const tg = window.Telegram?.WebApp;
    // visualViewport/current Telegram viewport shrink with the mobile keyboard.
    // viewportStableHeight is deliberately last because using it first creates
    // phantom page height while the keyboard is open.
    const height = Number(
      window.visualViewport?.height ||
      tg?.viewportHeight ||
      window.innerHeight ||
      tg?.viewportStableHeight ||
      0
    );
    if (height > 0) {
      document.documentElement.style.setProperty('--eduai-viewport-height', `${Math.round(height)}px`);
    }
  }
  syncViewportHeight();
  window.addEventListener('resize', syncViewportHeight, { passive: true });
  window.visualViewport?.addEventListener('resize', syncViewportHeight, { passive: true });
  window.Telegram?.WebApp?.onEvent?.('viewportChanged', syncViewportHeight);

  ensureMathStyles();
  ensureKatex().catch(() => {});
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installMathObserver, { once: true });
  } else {
    installMathObserver();
  }

  window.EduAI = {
    api, guard, readSession, saveSession, clearSession, escapeHtml,
    markdown, renderMath, toast, formatDate, setBusy, openModal, closeModal,
    logout, startThinking, setFormDisabled, initShell, ROLE_PATH, ROLE_LABELS, roleLabel, mentorKind,
       mentorLabel, applyMentorIdentity, MATH_RENDERER_VERSION,
    mathDebug: { normalizeLatexTransport, latexFallback }
  };
})();

/* === EduAI unified rich math rendering: 2026-08-16 === */
(function () {
  if (!window.EduAI) return;

  const previousRenderMath = EduAI.renderMath;
  const COMMAND_NAMES = [
    'frac', 'dfrac', 'tfrac', 'sqrt', 'times', 'cdot', 'div', 'pm', 'mp',
    'le', 'leq', 'ge', 'geq', 'ne', 'neq', 'approx', 'equiv', 'sim', 'simeq',
    'propto', 'in', 'notin', 'ni', 'subset', 'subseteq', 'supset', 'supseteq',
    'cap', 'cup', 'setminus', 'emptyset', 'forall', 'exists', 'nabla', 'partial',
    'sum', 'prod', 'int', 'iint', 'iiint', 'oint', 'lim', 'min', 'max',
    'sin', 'cos', 'tan', 'tg', 'cot', 'ctg', 'log', 'ln', 'lg', 'exp',
    'pi', 'infty', 'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'varepsilon',
    'zeta', 'eta', 'theta', 'vartheta', 'iota', 'kappa', 'lambda', 'mu', 'nu',
    'xi', 'rho', 'sigma', 'tau', 'upsilon', 'phi', 'varphi', 'chi', 'psi', 'omega',
    'Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma', 'Phi', 'Psi', 'Omega',
    'quad', 'qquad', 'Rightarrow', 'Leftarrow', 'Leftrightarrow', 'rightarrow',
    'leftarrow', 'to', 'mapsto', 'implies', 'iff', 'text', 'textrm', 'mathrm',
    'mathbf', 'mathit', 'mathsf', 'mathtt', 'operatorname', 'begin', 'end', 'left',
    'right', 'overline', 'underline', 'vec', 'hat', 'bar', 'dot', 'ddot', 'boxed',
    'ldots', 'cdots', 'vdots', 'ddots'
  ];
  const COMMAND_PATTERN = COMMAND_NAMES.join('|');
  const COMMAND_RE = new RegExp(`\\\\(?:${COMMAND_PATTERN})(?![A-Za-z])`);
  const DOUBLE_COMMAND_RE = new RegExp(
    `\\\\(?=(?:\\[|\\]|\\(|\\)|${COMMAND_PATTERN})(?![A-Za-z]))`,
    'g'
  );
  const WRAPPER_NAMES = [
    'text', 'textrm', 'mathrm', 'mathbf', 'mathit', 'mathsf', 'mathtt',
    'operatorname', 'overline', 'underline', 'vec', 'hat', 'bar', 'boxed'
  ];
  const WRAPPER_RE = new RegExp(
    `\\\\(?:${WRAPPER_NAMES.join('|')})\\s*\\{([^{}]*)\\}`,
    'g'
  );
  const WINDOWS_PATH_RE = /\b[A-Za-z]:\\(?:[^\\\s]+\\)+[^\s]*/;

  const encodeMath = value => btoa(unescape(encodeURIComponent(String(value ?? ''))));

  function normalize(value) {
    return String(value ?? '')
      .replace(/\\\\(?=[()[\]])/g, '\\')
      .replace(DOUBLE_COMMAND_RE, '\\');
  }

  function fallback(value) {
    let text = normalize(value).trim();
    let previous = null;

    while (previous !== text) {
      previous = text;
      text = text.replace(/\\(?:frac|dfrac|tfrac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '($1)/($2)');
    }

    text = text
      .replace(/\\sqrt\s*\[([^\]]+)\]\s*\{([^{}]+)\}/g, 'root[$1]($2)')
      .replace(/\\sqrt\s*\{([^{}]+)\}/g, '√($1)');

    previous = null;
    while (previous !== text) {
      previous = text;
      text = text.replace(WRAPPER_RE, '$1');
    }

    const symbols = {
      times:'×', cdot:'·', div:':', pm:'±', mp:'∓', le:'≤', leq:'≤', ge:'≥', geq:'≥', ne:'≠', neq:'≠',
      approx:'≈', equiv:'≡', sim:'∼', simeq:'≃', propto:'∝', in:'∈', notin:'∉', ni:'∋', subset:'⊂', subseteq:'⊆',
      supset:'⊃', supseteq:'⊇', cap:'∩', cup:'∪', setminus:'∖', emptyset:'∅', forall:'∀', exists:'∃',
         nabla:'∇', partial:'∂',
      sum:'∑', prod:'∏', int:'∫', iint:'∬', iiint:'∭', oint:'∮', Rightarrow:'⇒', Leftarrow:'⇐', Leftrightarrow:'⇔',
      rightarrow:'→', leftarrow:'←', to:'→', mapsto:'↦', implies:'⇒', iff:'⇔', pi:'π', infty:'∞',
         alpha:'α', beta:'β', gamma:'γ',
      delta:'δ', epsilon:'ε', varepsilon:'ϵ', zeta:'ζ', eta:'η', theta:'θ', vartheta:'ϑ', iota:'ι',
         kappa:'κ', lambda:'λ', mu:'μ',
      nu:'ν', xi:'ξ', rho:'ρ', sigma:'σ', tau:'τ', upsilon:'υ', phi:'φ', varphi:'ϕ', chi:'χ', psi:'ψ',
         omega:'ω', Gamma:'Γ',
      Delta:'Δ', Theta:'Θ', Lambda:'Λ', Xi:'Ξ', Pi:'Π', Sigma:'Σ', Phi:'Φ', Psi:'Ψ', Omega:'Ω', ldots:
        '…', cdots:'⋯', vdots:'⋮', ddots:'⋱'
    };

    text = text.replace(/\\[,;:]/g, ' ').replace(/\\!/g, '');
    text = text.replace(/\\([A-Za-z]+)\*?/g, (all, name) => {
      if (Object.prototype.hasOwnProperty.call(symbols, name)) return symbols[name];
      if (/^(sin|cos|tan|tg|cot|ctg|log|ln|lg|exp|lim|min|max)$/.test(name)) return name;
      if (/^(quad|qquad|left|right)$/.test(name)) return ' ';
      if (/^(begin|end)$/.test(name)) return '';
      return '';
    });

    const supers = '⁰¹²³⁴⁵⁶⁷⁸⁹';
    const subs = '₀₁₂₃₄₅₆₇₈₉';
    text = text
      .replace(/\\\\/g, '\n')
      .replace(/\\[\[\]()]/g, '')
      .replace(/\^\{([0-9])\}/g, (_, n) => supers[Number(n)])
      .replace(/_\{([0-9])\}/g, (_, n) => subs[Number(n)])
      .replace(/\^([0-9])/g, (_, n) => supers[Number(n)])
      .replace(/_([0-9])/g, (_, n) => subs[Number(n)])
      .replace(/[{}]/g, '')
      .replace(/[ \t]{2,}/g, ' ');
    return text.trim();
  }

  function hasBareLatex(line) {
    if (COMMAND_RE.test(line)) return true;
    if (WINDOWS_PATH_RE.test(line) && !/[{}^_$]/.test(line)) return false;
    return /\\[A-Za-z]+\*?\s*(?:\{|_|\^)/.test(line) || /\\(?:begin|end)\s*\{/.test(line) || /\\[,;:!]/.test(line);
  }

  function renderRichContent(value) {
    const protectedParts = [];
    const protect = html => {
      const token = `@@EDUAI_UNIFIED_${protectedParts.length}@@`;
      protectedParts.push(html);
      return token;
    };

    let text = normalize(value);

    // Programming code is content, not mathematics. Keep it verbatim and safe.
    text = text.replace(/```([\s\S]*?)```/g, (_, code) =>
      protect(`<pre class="eduai-code"><code>${EduAI.escapeHtml(code.replace(/^\n|\n$/g, ''))}</code></pre>`)
    );
    text = text.replace(/`([^`]+)`/g, (_, code) =>
      protect(`<code class="rounded bg-black/20 px-1">${EduAI.escapeHtml(code)}</code>`)
    );

    // Canonical and common legacy math delimiters render through the shared KaTeX renderer.
    text = text.replace(/\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$/g, (_, a, b) =>
      protect(`<span class="math-display" data-eduai-math="${encodeMath(a || b || '')}" data-display="1"></span>`)
    );
    text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, expr) =>
      protect(`<span class="math-inline" data-eduai-math="${encodeMath(expr)}" data-display="0"></span>`)
    );
    text = text.replace(/(?<!\$)\$([^$\n]{1,2000})\$(?!\$)/g, (_, expr) =>
      protect(`<span class="math-inline" data-eduai-math="${encodeMath(expr)}" data-display="0"></span>`)
    );

    // Malformed/legacy bare TeX must never be exposed. Explicitly delimited math
    // above remains beautiful KaTeX; bare commands use a readable Unicode fallback.
    text = text.split('\n').map(line => hasBareLatex(line) ? fallback(line) : line).join('\n');

    let safe = EduAI.escapeHtml(text)
      .replace(/^### (.+)$/gm, '<strong class="block text-base mt-2">$1</strong>')
      .replace(/^## (.+)$/gm, '<strong class="block text-lg mt-2">$1</strong>')
      .replace(/^# (.+)$/gm, '<strong class="block text-xl mt-2">$1</strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^[-•] (.+)$/gm, '<span class="block pl-3">• $1</span>')
      .replace(/\n/g, '<br>');

    protectedParts.forEach((html, index) => {
      safe = safe.replace(`@@EDUAI_UNIFIED_${index}@@`, html);
    });

    queueMicrotask(() => previousRenderMath?.(document));
    return `<div class="rich-content">${safe}</div>`;
  }

  EduAI.renderRichContent = renderRichContent;
  EduAI.markdown = renderRichContent;
  EduAI.latexFallback = fallback;
  EduAI.MATH_RENDERER_VERSION = '20260816-unified-2';
})();
/* === /EduAI unified rich math rendering === */

/* === EDUAI IOS-INSPIRED ADAPTIVE UI START === */
(function () {
  const THEME_KEY = 'eduai.ui.theme';
  const LAYOUT_PREFIX = 'eduai.ui.layout:';
  const currentPath = location.pathname || '/';
  const mediaDark = window.matchMedia?.('(prefers-color-scheme: dark)');

  function safeGet(key, fallback = null) {
    try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
  }

  function safeSet(key, value) {
    try { localStorage.setItem(key, value); } catch (_) {}
  }

  function currentThemePreference() {
    const value = safeGet(THEME_KEY, 'system');
    return ['light', 'dark', 'system'].includes(value) ? value : 'system';
  }

  function resolveTheme(preference = currentThemePreference()) {
    if (preference === 'system') return mediaDark?.matches ? 'dark' : 'light';
    return preference;
  }

  function applyTheme(preference = currentThemePreference()) {
    const resolved = resolveTheme(preference);
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = preference;
    document.documentElement.style.colorScheme = resolved;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', resolved === 'dark' ? '#101114' : '#f5f5f7');
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      const active = button.dataset.themeChoice === preference;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function setTheme(preference) {
    if (!['light', 'dark', 'system'].includes(preference)) return;
    safeSet(THEME_KEY, preference);
    applyTheme(preference);
  }

  function navLabel(link) {
    const clone = link.cloneNode(true);
    clone.querySelectorAll('.badge').forEach(item => item.remove());
    const icon = clone.querySelector(':scope > span[aria-hidden="true"], :scope > span:first-child');
    icon?.remove();
    return clone.textContent.replace(/\s+/g, ' ').trim();
  }

  function navIcon(link) {
    return link.querySelector(':scope > span[aria-hidden="true"], :scope > span:first-child')
      ?.textContent?.trim() || '•';
  }

  function navigationSources() {
    const sidebarLinks = [...document.querySelectorAll('.sidebar nav [data-section]')];
    if (sidebarLinks.length) return sidebarLinks;
    return [...document.querySelectorAll('.desktop-quick-nav [data-section]')];
  }

  function createQuickNavigation() {
    const sourceLinks = navigationSources();
    const topbar = document.querySelector('.topbar');
    if (!sourceLinks.length || !topbar || topbar.querySelector('.desktop-quick-nav')) return;
    const nav = document.createElement('nav');
    nav.className = 'desktop-quick-nav';
    nav.setAttribute('aria-label', 'Быстрая навигация');
    sourceLinks.slice(0, 5).forEach(source => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `quick-nav-link${source.classList.contains('active') ? ' active' : ''}`;
      button.dataset.section = source.dataset.section;
      button.innerHTML = `<span aria-hidden="true">${navIcon(source)}</span><span>${navLabel(source)}</span>`;
      nav.append(button);
    });
    topbar.insertBefore(nav, topbar.lastElementChild);
  }


  function resetInterfaceLayout() {
    try {
      Object.keys(localStorage).forEach(key => {
        if (key.startsWith(LAYOUT_PREFIX) || key.startsWith('eduai.ui.section:') || key
          .startsWith('eduai.ui.tutorSidebarCollapsed')) {
          localStorage.removeItem(key);
        }
      });
    } catch (_) {}
    location.reload();
  }

  function createSettingsPanel() {
    if (document.querySelector('[data-ui-settings]')) return;
    const host = document.querySelector('.topbar > :last-child') || document
      .querySelector('.interactive-toolbar') || document.body;
    const wrap = document.createElement('div');
    wrap.className = 'ui-settings-wrap';
    wrap.dataset.uiSettings = '1';
    wrap.innerHTML = `
      <button class="icon-btn ui-settings-toggle" type="button" aria-label="Настройки интерфейса"
         aria-haspopup="dialog" aria-expanded="false">⚙</button>
      <div class="ui-settings-popover glass-strong" role="dialog" aria-label="Настройка отображения темы сайта" hidden>
        <div class="ui-settings-head"><div><strong>Тема сайта</strong>
          <p class="ui-settings-description">Выберите оформление Umnix</p></div>
          <button type="button" class="thread-action" data-ui-settings-close aria-label="Закрыть">×</button></div>
        <div class="theme-segmented" role="group" aria-label="Тема оформления">
          <button type="button" data-theme-choice="light">Светлая</button>
          <button type="button" data-theme-choice="dark">Тёмная</button>
          <button type="button" data-theme-choice="system">Системная</button>
        </div>
      </div>`;
    if (host === document.body) {
      wrap.classList.add('ui-settings-floating');
      document.body.append(wrap);
    } else {
      host.append(wrap);
    }
    const toggle = wrap.querySelector('.ui-settings-toggle');
    const popover = wrap.querySelector('.ui-settings-popover');
    let closeTimer = null;
    const open = () => {
      clearTimeout(closeTimer);
      document.querySelectorAll('.ui-settings-popover.is-open').forEach(other => {
        if (other !== popover) {
          other.classList.remove('is-open');
          other.setAttribute('aria-hidden', 'true');
        }
      });
      popover.hidden = false;
      popover.setAttribute('aria-hidden', 'false');
      requestAnimationFrame(() => popover.classList.add('is-open'));
      toggle.setAttribute('aria-expanded', 'true');
      setTimeout(() => popover.querySelector('[data-theme-choice].active')?.focus({ preventScroll: true }), 40);
    };
    const close = () => {
      clearTimeout(closeTimer);
      popover.classList.remove('is-open');
      popover.setAttribute('aria-hidden', 'true');
      toggle.setAttribute('aria-expanded', 'false');
      closeTimer = setTimeout(() => { if (!popover.classList.contains('is-open')) popover.hidden = true; }, 190);
    };
    toggle.addEventListener('click', event => {
      event.stopPropagation();
      if (popover.hidden || !popover.classList.contains('is-open')) open(); else close();
    });
    wrap.querySelector('[data-ui-settings-close]').addEventListener('click', close);
    wrap.querySelectorAll('[data-theme-choice]').forEach(button => button.addEventListener('click',
       () => setTheme(button.dataset.themeChoice)));
    document.addEventListener('click', event => { if (!wrap.contains(event.target)) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
    applyTheme();
  }

  function openThemeSettings() {
    const wrap = document.querySelector('[data-ui-settings]');
    const toggle = wrap?.querySelector('.ui-settings-toggle');
    const popover = wrap?.querySelector('.ui-settings-popover');
    if (!wrap || !toggle || !popover) return false;
    applyTheme();
    popover.hidden = false;
    popover.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => popover.classList.add('is-open'));
    toggle.setAttribute('aria-expanded', 'true');
    setTimeout(() => popover.querySelector('[data-theme-choice].active')?.focus({ preventScroll: true }), 40);
    return true;
  }

  function moduleKey(element, index) {
    if (element.dataset.uiModule) return element.dataset.uiModule;
    const ownId = element.id || element.querySelector('[id]')?.id;
    const text = element.querySelector('h2,h3,.stat-value,p')?.textContent?.trim()?.slice(0, 32) || `module-${index}`;
    const slug = (ownId || text).toLowerCase().replace(/[^a-z0-9а-яё]+/gi, '-').replace(/^-|-$/g, '');
    element.dataset.uiModule = slug || `module-${index}`;
    return element.dataset.uiModule;
  }

  function applySavedOrder(container, storageKey) {
    let order = [];
    try { order = JSON.parse(safeGet(storageKey, '[]')); } catch (_) {}
    if (!Array.isArray(order) || !order.length) return;
    const byKey = new Map([...container.children].map((child, index) => [moduleKey(child, index), child]));
    order.forEach(key => { const child = byKey.get(key); if (child) container.append(child); });
  }

  function saveOrder(container, storageKey) {
    const order = [...container.children].filter(child => child.matches('.ui-movable-module'))
      .map((child, index) => moduleKey(child, index));
    safeSet(storageKey, JSON.stringify(order));
  }

  function enableMovableContainer(container, name) {
    if (!container || container.dataset.uiMovableReady) return;
    container.dataset.uiMovableReady = '1';
    const storageKey = `${LAYOUT_PREFIX}${currentPath}:${name}`;
    [...container.children].forEach((child, index) => {
      child.classList.add('ui-movable-module');
      child.draggable = true;
      moduleKey(child, index);
      child.addEventListener('dragstart', event => {
        if (window.matchMedia('(max-width: 767px)').matches) { event.preventDefault(); return; }
        child.classList.add('ui-dragging');
        event.dataTransfer?.setData('text/plain', child.dataset.uiModule);
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
      });
      child.addEventListener('dragend', () => { child.classList.remove('ui-dragging');
         saveOrder(container, storageKey); });
    });
    container.addEventListener('dragover', event => {
      const dragging = container.querySelector('.ui-dragging');
      if (!dragging) return;
      event.preventDefault();
      const siblings = [...container.querySelectorAll('.ui-movable-module:not(.ui-dragging)')];
      const target = siblings.find(item => {
        const box = item.getBoundingClientRect();
        return event.clientY < box.top + box.height / 2 && event.clientX < box.right + Math.max(48, box.width / 2);
      });
      if (target) container.insertBefore(dragging, target); else container.append(dragging);
    });
    applySavedOrder(container, storageKey);
  }

  function enableMovableModules() {
    const adminOverview = document.getElementById('admin-overview');
    enableMovableContainer(adminOverview?.querySelector('.grid.grid-cols-2'), 'admin-stats');
  }

  function setupMatrixBackground() {
    if (document.querySelector('.eduai-matrix-canvas')) return;
    const canvas = document.createElement('canvas');
    canvas.className = 'eduai-matrix-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.prepend(canvas);

    const context = canvas.getContext('2d');
    if (!context) return;

    const tokens = [
      'E=mc²', 'λ=h/p', '∫dx', '∑x', 'Δx·Δp≥ħ/2', 'π', 'θ', 'Ω', 'α', 'β',
      '√x', 'x²+y²=r²', 'function()', 'const', 'let', 'AI=>', '{01}', '101101', 'learn()', 'f(x)'
    ];
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let streams = [];
    let width = 0;
    let height = 0;
    let lastFrame = 0;
    let frameId = null;

    const createStreams = () => {
      const columnWidth = window.innerWidth < 600 ? 54 : 44;
      const count = Math.max(7, Math.floor(width / columnWidth));
      streams = Array.from({ length: count }, (_, index) => ({
        x: index * columnWidth + 10 + Math.random() * 12,
        y: Math.random() * -height,
        speed: 7 + Math.random() * 10,
        token: tokens[Math.floor(Math.random() * tokens.length)],
        size: 11 + Math.random() * 3,
      }));
    };

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      width = Math.max(1, window.innerWidth);
      height = Math.max(1, window.innerHeight);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      createStreams();
    };

    const draw = timestamp => {
      if (timestamp - lastFrame < 42 && !reduceMotion?.matches) {
        frameId = requestAnimationFrame(draw);
        return;
      }
      const delta = lastFrame ? Math.min(0.08, (timestamp - lastFrame) / 1000) : 0.04;
      lastFrame = timestamp;
      context.clearRect(0, 0, width, height);
      const rgb = getComputedStyle(document.documentElement).getPropertyValue('--matrix-rgb').trim() || '70, 70, 78';
      for (const stream of streams) {
        const progress = Math.max(0, Math.min(1, stream.y / height));
        const opacity = Math.max(0, (1 - progress) * 0.16);
        context.font = `${stream.size}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        context.fillStyle = `rgba(${rgb}, ${opacity})`;
        context.fillText(stream.token, stream.x, stream.y);
        if (!reduceMotion?.matches) stream.y += stream.speed * delta;
        if (stream.y > height + 20) {
          stream.y = -20 - Math.random() * height * 0.25;
          stream.token = tokens[Math.floor(Math.random() * tokens.length)];
        }
      }
      if (!reduceMotion?.matches) frameId = requestAnimationFrame(draw);
    };

    const restart = () => {
      if (frameId) cancelAnimationFrame(frameId);
      lastFrame = 0;
      resize();
      frameId = requestAnimationFrame(draw);
    };

    window.addEventListener('resize', restart, { passive: true });
    reduceMotion?.addEventListener?.('change', restart);
    restart();
  }

  function setupTopGlow() {
    if (document.querySelector('.eduai-top-glow')) return;
    const glow = document.createElement('div');
    glow.className = 'eduai-top-glow';
    glow.setAttribute('aria-hidden', 'true');
    document.body.prepend(glow);
  }

  function setupMobileKeyboard() {
    const viewport = window.visualViewport;
    const update = () => {
      const focused = document.activeElement?.matches
        ?.('textarea,input:not([type="checkbox"]):not([type="radio"]),[contenteditable="true"]');
      const referenceHeight = Math.max(window.innerHeight || 0, Number(document.documentElement
        .dataset.maxViewportHeight || 0));
      if (referenceHeight) document.documentElement.dataset.maxViewportHeight = String(referenceHeight);
      const visibleHeight = viewport?.height || window.innerHeight;
      const keyboardOpen = Boolean(focused && referenceHeight && visibleHeight < referenceHeight * 0.82);
      document.body.classList.toggle('keyboard-open', keyboardOpen);
    };
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', () => setTimeout(update, 80));
    viewport?.addEventListener('resize', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
  }

  function setupBookModePanels() {
    document.querySelectorAll('[data-chat-layout]').forEach((layout, index) => {
      const asides = [...layout.children].filter(child => child.tagName === 'ASIDE');
      const panel = asides.at(-1);
      const center = layout.querySelector('.chat-center-card');
      if (!panel || !center || panel.matches('[data-chat-sidebar]') || panel.dataset.bookPanelReady) return;
      panel.dataset.bookPanelReady = '1';
      panel.classList.add('chat-context-panel');
      panel.style.setProperty('--book-panel-index', String(index));
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn-secondary book-panel-toggle';
      button.setAttribute('aria-expanded', 'false');
      button.innerHTML = '<span aria-hidden="true">📚</span><span>Учебник</span>';
      const headerRow = center.querySelector(':scope > div:first-child .flex') || center.firstElementChild;
      headerRow?.append(button);
      const backdrop = document.createElement('button');
      backdrop.type = 'button';
      backdrop.className = 'ui-context-backdrop';
      backdrop.setAttribute('aria-label', 'Закрыть выбор учебника');
      layout.append(backdrop);
      const close = () => { layout.classList.remove('book-panel-open'); button
        .setAttribute('aria-expanded', 'false'); };
      const closeButton = document.createElement('button');
      closeButton.type = 'button';
      closeButton.className = 'icon-btn book-panel-close';
      closeButton.setAttribute('aria-label', 'Закрыть выбор учебника');
      closeButton.textContent = '×';
      panel.prepend(closeButton);
      closeButton.addEventListener('click', close);
      button.addEventListener('click', () => {
        const open = !layout.classList.contains('book-panel-open');
        document.querySelectorAll('[data-chat-layout].book-panel-open').forEach(other => {
           if (other !== layout) other.classList.remove('book-panel-open'); });
        layout.classList.toggle('book-panel-open', open);
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      backdrop.addEventListener('click', close);
      let startY = null;
      let startX = null;
      panel.addEventListener('touchstart', event => {
        const touch = event.touches?.[0];
        if (!touch) return;
        startY = touch.clientY; startX = touch.clientX;
      }, { passive: true });
      panel.addEventListener('touchend', event => {
        const touch = event.changedTouches?.[0];
        if (!touch || startY === null) return;
        const dy = touch.clientY - startY;
        const dx = touch.clientX - startX;
        if (window.matchMedia('(max-width: 767px)').matches && dy > 72 && Math.abs(dy) > Math.abs(dx) * 1.2) close();
        startY = startX = null;
      }, { passive: true });
    });
  }

  function setupMobileSectionNavigation() {
    const primaryNav = document.querySelector('.teacher-primary-nav, .student-primary-nav, .admin-primary-nav');
    const topbar = document.querySelector('.topbar');
    const actions = document.querySelector('.teacher-topbar-actions, .student-topbar-actions, .admin-topbar-actions')
       || topbar?.lastElementChild;
    if (!primaryNav || !topbar || !actions || document.querySelector('[data-mobile-section-menu]')) return;

    const wrap = document.createElement('div');
    wrap.className = 'mobile-section-menu';
    wrap.dataset.mobileSectionMenu = '1';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'icon-btn mobile-section-menu-toggle';
    toggle.setAttribute('aria-label', 'Открыть разделы');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.innerHTML = '<span class="mobile-section-menu-arrow" aria-hidden="true">↗</span>';
    const sheet = document.createElement('div');
    sheet.className = 'mobile-section-menu-sheet glass-strong';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', 'Разделы кабинета');
    sheet.setAttribute('aria-hidden', 'true');

    const close = () => { wrap.classList.remove('open'); toggle.setAttribute('aria-expanded','false');
       sheet.setAttribute('aria-hidden','true'); };
    primaryNav.querySelectorAll('[data-section]').forEach(source => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'mobile-section-menu-item';
      item.dataset.sectionTarget = source.dataset.section;
      item.innerHTML = `<span aria-hidden="true">${navIcon(source)}</span><span>${navLabel(source)}</span>`;
      item.addEventListener('click', () => { source.click(); close(); });
      sheet.append(item);
    });
    const roleSource = primaryNav.querySelector('.quick-role-switch');
    if (roleSource) {
      const link = document.createElement('a');
      link.className = 'mobile-section-menu-item mobile-section-role-switch';
      link.href = roleSource.href;
      link.innerHTML = '<span aria-hidden="true">⇄</span><span>Сменить режим</span>';
      if (roleSource.hasAttribute('data-admin-only')) link.setAttribute('data-admin-only','');
      link.hidden = roleSource.hidden;
      new MutationObserver(() => { link.hidden = roleSource.hidden; }).observe(roleSource, {
         attributes:true, attributeFilter:['hidden'] });
      sheet.append(link);
    }
    wrap.append(toggle, sheet);
    actions.prepend(wrap);
    toggle.addEventListener('click', event => { event.stopPropagation(); const open = !wrap.classList
      .contains('open'); document.querySelectorAll('.mobile-section-menu.open').forEach(other => other
      .classList.remove('open')); wrap.classList.toggle('open', open); toggle.setAttribute('aria-expanded',
       open ? 'true':'false'); sheet.setAttribute('aria-hidden', open ? 'false':'true'); });
    sheet.addEventListener('click', event => event.stopPropagation());
    document.addEventListener('click', event => { if (!wrap.contains(event.target)) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
    new MutationObserver(() => {
      const active = document.body.dataset.activeSection;
      sheet.querySelectorAll('[data-section-target]').forEach(item => item.classList.toggle('active',
         item.dataset.sectionTarget === active));
      if (window.matchMedia('(max-width: 767px)').matches) close();
    }).observe(document.body, { attributes:true, attributeFilter:['data-active-section'] });
  }

  function setupTutorMobileNavigation() {
    document.querySelectorAll('[data-chat-layout]').forEach(layout => {
      if (layout.dataset.mobileNavReady === '1') return;
      const section = layout.closest('.page-section');
      const center = layout.querySelector('.chat-center-card');
      const headerRow = center?.querySelector('.chat-screen-header-row') || center
        ?.querySelector(':scope > div:first-child .flex');
      const bookButton = headerRow?.querySelector('.book-panel-toggle');
      const primaryNav = document.querySelector('.teacher-primary-nav, .student-primary-nav');
      if (!section || !headerRow || !primaryNav) return;
      layout.dataset.mobileNavReady = '1';

      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'icon-btn tutor-mobile-nav-toggle';
      toggle.setAttribute('aria-label', 'Открыть разделы');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.innerHTML = '<span aria-hidden="true" class="tutor-mobile-nav-arrow">↗</span>';

      const sheet = document.createElement('div');
      sheet.className = 'tutor-mobile-nav-sheet glass-strong';
      sheet.setAttribute('role', 'dialog');
      sheet.setAttribute('aria-label', 'Разделы кабинета');
      sheet.setAttribute('aria-hidden', 'true');

      const addSection = source => {
        const target = source.dataset.section;
        if (!target || target === section.id) return;
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'tutor-mobile-nav-item';
        item.dataset.mobileNavTarget = target;
        item.innerHTML = `<span aria-hidden="true">${navIcon(source)}</span><span>${navLabel(source)}</span>`;
        item.addEventListener('click', () => {
          source.click();
          close();
        });
        sheet.append(item);
      };
      primaryNav.querySelectorAll('[data-section]').forEach(addSection);

      const roleSource = primaryNav.querySelector('.quick-role-switch');
      let roleClone = null;
      if (roleSource) {
        roleClone = document.createElement('a');
        roleClone.className = 'tutor-mobile-nav-item tutor-mobile-role-switch';
        roleClone.href = roleSource.href;
        roleClone.innerHTML = '<span aria-hidden="true">⇄</span><span>Сменить роль</span>';
        if (roleSource.hasAttribute('data-admin-only')) roleClone.setAttribute('data-admin-only', '');
        roleClone.hidden = roleSource.hidden;
        sheet.append(roleClone);
        new MutationObserver(() => { roleClone.hidden = roleSource.hidden; }).observe(roleSource, {
           attributes: true, attributeFilter: ['hidden'] });
      }

      const close = () => {
        layout.classList.remove('mobile-nav-open');
        toggle.setAttribute('aria-expanded', 'false');
        sheet.setAttribute('aria-hidden', 'true');
      };
      const open = () => {
        layout.classList.add('mobile-nav-open');
        toggle.setAttribute('aria-expanded', 'true');
        sheet.setAttribute('aria-hidden', 'false');
      };
      toggle.addEventListener('click', event => {
        event.stopPropagation();
        if (layout.classList.contains('mobile-nav-open')) close(); else open();
      });
      sheet.addEventListener('click', event => event.stopPropagation());
      document.addEventListener('click', event => {
        if (layout.classList.contains('mobile-nav-open') && !sheet.contains(event.target) && event
          .target !== toggle) close();
      });
      document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });

      if (bookButton) headerRow.insertBefore(toggle, bookButton);
      else headerRow.append(toggle);
      layout.append(sheet);
    });
  }

  function setupGlobalScrollControl() {
    if (document.querySelector('[data-global-scroll-control]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'global-scroll-control';
    button.dataset.globalScrollControl = '1';
    button.hidden = true;
    document.body.append(button);
    let engaged = false;
    let hideTimer = null;

    const targetInfo = () => {
      const active = document.querySelector('.page-section.active');
      const log = active?.querySelector('.chat-log');
      if (log && log.scrollHeight > log.clientHeight + 96) return { element: log, isWindow: false };
      const root = document.scrollingElement || document.documentElement;
      return { element: root, isWindow: true };
    };

    const update = () => {
      const { element, isWindow } = targetInfo();
      const top = isWindow ? window.scrollY : element.scrollTop;
      const height = isWindow ? window.innerHeight : element.clientHeight;
      const max = Math.max(0, element.scrollHeight - height);
      if (!engaged || max < 140 || top < 4) { button.hidden = true; return; }
      const down = top < max / 2;
      button.textContent = down ? '↓' : '↑';
      button.setAttribute('aria-label', down ? 'Прокрутить вниз' : 'Прокрутить вверх');
      button.setAttribute('title', down ? 'Вниз' : 'Вверх');
      button.hidden = false;
      clearTimeout(hideTimer);
      if (top < 8 || max - top < 8) hideTimer = setTimeout(() => { button.hidden = true; engaged = false; }, 650);
    };

    const onScroll = () => { engaged = true; update(); };
    window.addEventListener('scroll', onScroll, { passive: true });
    document.querySelectorAll('.chat-log,.table-wrap,.modal-panel').forEach(element => element
      .addEventListener('scroll', onScroll, { passive: true }));
    button.addEventListener('click', () => {
      const { element, isWindow } = targetInfo();
      const top = isWindow ? window.scrollY : element.scrollTop;
      const height = isWindow ? window.innerHeight : element.clientHeight;
      const max = Math.max(0, element.scrollHeight - height);
      const destination = top < max / 2 ? element.scrollHeight : 0;
      if (isWindow) window.scrollTo({ top: destination, behavior: 'smooth' });
      else element.scrollTo({ top: destination, behavior: 'smooth' });
    });
  }

  function syncNavState() {
    const sync = () => {
      const activeSection = document.body.dataset.activeSection || document.querySelector('.page-section.active')?.id;
      if (!activeSection) return;
      document.querySelectorAll('.quick-nav-link,.mobile-nav-link[data-section]').forEach(item => item
        .classList.toggle('active', item.dataset.section === activeSection));
    };
    new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ['data-active-section'] });
    sync();
  }

  function initAdaptiveUI() {
    applyTheme();
    createQuickNavigation();
    createSettingsPanel();
    setupMatrixBackground();
    setupTopGlow();
    setupMobileKeyboard();
    enableMovableModules();
    setupBookModePanels();
    setupMobileSectionNavigation();
    setupTutorMobileNavigation();
    setupGlobalScrollControl();
    syncNavState();
  }

  mediaDark?.addEventListener?.('change', () => { if (currentThemePreference() === 'system') applyTheme('system'); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAdaptiveUI, { once: true });
  else initAdaptiveUI();

  window.EduAIUI = { applyTheme, setTheme, resetInterfaceLayout, openThemeSettings };
})();
/* === EDUAI IOS-INSPIRED ADAPTIVE UI END === */
