(function () {
  class ChatUI {
    constructor(options) {
      this.options = options;
      this.state = { sessions: [], activeId: null, editingInteractiveId: null,
         editingInteractiveVersion: null, interactiveAction: null, profile: null, threadQuery: '',
         pendingRequest: null, voiceRecorder: null, voiceStream: null, voiceChunks: [], voiceStopTimer: null };
      this.$ = name => document.getElementById(options[name]);
      this.layout = null;
      this.jumpButton = null;
    }

    async init() {
      this.bind();
      await this.loadProfile();
      const preferredChat = new URLSearchParams(window.location.search).get('chat');
      await Promise.all([this.loadSessions(preferredChat), this.loadClasses()]);
    }

    bind() {
      this.$('newChatId').addEventListener('click', () => this.newChat());
      this.$('threadsId').addEventListener('click', event => this.threadAction(event));
      this.$('formId').addEventListener('submit', event => this.send(event));
      this.$('formId').querySelector('[data-chat-voice]')?.addEventListener('click', () => this.toggleVoiceRecording());
      this.$('logId').addEventListener('click', event => this.messageAction(event));
      this.$('logId').addEventListener('scroll', () => this.updateJumpButton(), { passive: true });
      this.installChatChrome();
      this.$('inputId').addEventListener('input', () => this.resizeComposer());
      this.$('inputId').addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          const form = this.$('formId');
          if (typeof form.requestSubmit === 'function') form.requestSubmit();
          else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
      });
      this.$('attachId').addEventListener('change', () => this.previewAttachment());
      this.$('removeAttachId').addEventListener('click', () => this.clearAttachment());
      this.bindPlusMenu();
      this.$('classId').addEventListener('change', () => this.loadSubjects());
      this.$('subjectId').addEventListener('change', () => this.loadBooks());
      this.$('bookId').addEventListener('change', () => this.loadPages());
      this.$('lockId').addEventListener('click', () => this.lockContext());
      this.$('exitId').addEventListener('click', () => this.exitContext());
    }

    installChatChrome() {
      const section = this.$('formId')?.closest('.page-section');
      this.layout = section?.querySelector('[data-chat-layout]') || null;
      this.jumpButton = section?.querySelector('[data-chat-jump-bottom]') || null;
      this.jumpButton?.addEventListener('click', () => this.jumpByPosition());
      this.layout?.querySelectorAll('[data-chat-sidebar-toggle]').forEach(button => {
        button.addEventListener('click', () => this.toggleThreadsPanel());
      });
      this.layout?.querySelector('[data-chat-sidebar-backdrop]')?.addEventListener('click', () => this
        .closeThreadsDrawer());
      window.addEventListener('resize', () => {
        this.closeThreadsDrawer();
        this.updateSidebarButtons();
        this.resizeComposer();
      }, { passive: true });
      this.installThreadSearch();
      this.installTutorRail();
      this.installSwipeGestures();
      try {
        const saved = localStorage.getItem('eduai.ui.tutorSidebarCollapsed.v2');
        this.layout?.classList.toggle('threads-collapsed', saved !== '0');
      } catch (_) {
        this.layout?.classList.add('threads-collapsed');
      }
      this.updateSidebarButtons();
      this.resizeComposer();
      queueMicrotask(() => this.updateJumpButton());
    }


    installThreadSearch() {
      const list = this.$('threadsId');
      const sidebar = list?.closest('[data-chat-sidebar]');
      if (!list || !sidebar || sidebar.querySelector('[data-chat-search]')) return;
      const field = document.createElement('label');
      field.className = 'chat-thread-search';
      field.innerHTML = `<span class="sr-only">Поиск по чатам</span>
        <input class="input" type="search" autocomplete="off" placeholder="Поиск чатов" data-chat-search
         aria-label="Поиск по чатам">`;
      list.before(field);
      if (!sidebar.querySelector('[data-chat-library-link]')) {
        const libraryButton = document.createElement('button');
        libraryButton.type = 'button';
        libraryButton.className = 'btn-secondary chat-library-link';
        libraryButton.dataset.chatLibraryLink = '1';
        libraryButton.innerHTML = '<span aria-hidden="true">▣</span><span>Библиотека файлов</span>';
        field.after(libraryButton);
        libraryButton.addEventListener('click', () => { location.href = '/files.html'; });
      }
      field.querySelector('[data-chat-search]')?.addEventListener('input', event => {
        this.state.threadQuery = String(event.target.value || '').trim().toLocaleLowerCase('ru-RU');
        this.renderThreads();
      });
    }

    installTutorRail() {
      const sidebar = this.layout?.querySelector('[data-chat-sidebar]');
      if (!sidebar || sidebar.querySelector('[data-chat-rail]')) return;
      const rail = document.createElement('div');
      rail.className = 'chat-rail-actions';
      rail.dataset.chatRail = '1';
      rail.innerHTML = `
        <button type="button" class="icon-btn" data-rail-chats aria-label="Открыть список чатов" title="Чаты">☰</button>
        <button type="button" class="icon-btn" data-rail-new aria-label="Создать новый чат" title="Новый чат">＋</button>
        <button type="button" class="icon-btn" data-rail-files aria-label="Открыть библиотеку
           файлов" title="Библиотека файлов">▣</button>
        <span class="chat-rail-spacer" aria-hidden="true"></span>
        <button type="button" class="chat-rail-avatar" data-rail-profile aria-label="Личный кабинет"
           title="Личный кабинет">E</button>`;
      sidebar.prepend(rail);
      rail.querySelector('[data-rail-chats]')?.addEventListener('click', () => this.toggleThreadsPanel());
      rail.querySelector('[data-rail-new]')?.addEventListener('click', () => this.newChat());
      rail.querySelector('[data-rail-files]')?.addEventListener('click', () => { location.href = '/files.html'; });
      rail.querySelector('[data-rail-profile]')?.addEventListener('click', () => this.openProfile());
    }

    telegramAvatarUrl() {
      const fromWebApp = window.Telegram?.WebApp?.initDataUnsafe?.user?.photo_url;
      const fromSession = EduAI.readSession?.()?.telegram_photo_url;
      return String(fromWebApp || fromSession || '').trim();
    }

    decorateProfile(profile) {
      const telegramPhoto = this.telegramAvatarUrl();
      if (!telegramPhoto) return profile;
      return {
        ...profile,
        avatar_fallback_url: profile?.avatar_url || '',
        avatar_url: telegramPhoto,
      };
    }

    installAvatarFallback(image, profile, fallbackNode = null) {
      if (!image) return;
      const fallbackUrl = String(profile?.avatar_fallback_url || '').trim();
      let fallbackTried = false;
      image.addEventListener('load', () => {
        image.hidden = false;
        if (fallbackNode) fallbackNode.hidden = true;
      });
      image.addEventListener('error', () => {
        if (!fallbackTried && fallbackUrl && image.src !== fallbackUrl) {
          fallbackTried = true;
          image.src = fallbackUrl;
          return;
        }
        image.hidden = true;
        if (fallbackNode) fallbackNode.hidden = false;
      });
    }

    updateTutorRailProfile() {
      const button = this.layout?.querySelector('[data-rail-profile]');
      if (!button) return;
      const profile = this.state.profile || {};
      const label = profile.username ? `@${profile.username}` : String(profile.tg_id || 'Профиль');
      button.title = `${label} · Личный кабинет`;
      button.setAttribute('aria-label', `Личный кабинет: ${label}`);
      const initial = EduAI.escapeHtml(label.replace(/^@/, '').charAt(0).toUpperCase() || 'E');
      if (profile.avatar_url) {
        button.innerHTML = `<img src="${EduAI.escapeHtml(profile.avatar_url)}" alt=""><span>${initial}</span>`;
        const image = button.querySelector('img');
        this.installAvatarFallback(image, profile, button.querySelector('span'));
      } else {
        button.innerHTML = `<span>${initial}</span>`;
      }
    }

    async loadProfile() {
      try {
        this.state.profile = this.decorateProfile(await EduAI.api('/api/v1/tutor/profile'));
        this.installProfileButton();
      } catch (error) {
        console.warn('Umnix profile is unavailable', error);
      }
    }

    installProfileButton() {
      const sidebar = this.layout?.querySelector('[data-chat-sidebar]') || this.$('threadsId')
        ?.closest('[data-chat-sidebar]');
      if (!sidebar || sidebar.querySelector('[data-chat-profile]')) return;
      this.updateTutorRailProfile();
      const profile = this.state.profile || {};
      const label = profile.username ? `@${profile.username}` : String(profile.tg_id || 'Профиль');
      const wrap = document.createElement('div');
      wrap.className = 'chat-profile-wrap';
      wrap.innerHTML = `
        <button type="button" class="chat-profile-button" data-chat-profile aria-label="Открыть личный кабинет">
          <span class="chat-profile-avatar"><img src="${EduAI.escapeHtml(profile.avatar_url ||
             '')}" alt="" data-chat-profile-avatar><span data-chat-profile-fallback>${EduAI.escapeHtml(label
            .charAt(0).toUpperCase())}</span></span>
          <span class="min-w-0"><strong class="block truncate">${EduAI.escapeHtml(label)}
            </strong><small class="muted">Личный кабинет</small></span>
        </button>`;
      sidebar.appendChild(wrap);
      const image = wrap.querySelector('[data-chat-profile-avatar]');
      const fallback = wrap.querySelector('[data-chat-profile-fallback]');
      this.installAvatarFallback(image, profile, fallback);
      wrap.querySelector('[data-chat-profile]')?.addEventListener('click', () => this.openProfile());
    }

    openProfile() {
      const profile = this.state.profile || {};
      let modal = document.getElementById('chat-profile-modal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'chat-profile-modal';
        modal.className = 'modal-backdrop';
        modal.innerHTML = `<div class="modal-panel glass-strong profile-sheet">
          <div class="flex items-start justify-between gap-3"><div>
          <p class="text-xs font-bold uppercase tracking-wider muted">Umnix</p>
          <h2 class="text-xl font-extrabold">Личный кабинет</h2></div>
          <button class="icon-btn" type="button" data-profile-close aria-label="Закрыть">×</button></div>
          <div data-profile-body class="mt-5"></div></div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', event => { if (event.target === modal || event.target
          .closest('[data-profile-close]')) EduAI.closeModal('chat-profile-modal'); });
      }
      const label = profile.username ? `@${profile.username}` : String(profile.tg_id || '—');
      modal.querySelector('[data-profile-body]')
        .innerHTML = `<div class="flex items-center gap-4">
        <span class="chat-profile-avatar chat-profile-avatar-large"><img src="${EduAI.escapeHtml(profile
        .avatar_url || '')}" alt="Аватар Telegram" data-profile-avatar-image>
        <span data-profile-avatar-fallback>${EduAI.escapeHtml(label.charAt(0).toUpperCase())}
        </span></span><div><p class="font-extrabold">${EduAI.escapeHtml(label)}
        </p><p class="text-sm muted">Telegram ID: ${EduAI.escapeHtml(String(profile.tg_id || '—'))}</p></div></div>`;
      this.installAvatarFallback(modal.querySelector('[data-profile-avatar-image]'), profile, modal
        .querySelector('[data-profile-avatar-fallback]'));
      EduAI.openModal('chat-profile-modal');
    }

    installSwipeGestures() {
      if (!this.layout || this.layout.dataset.swipeReady === '1') return;
      this.layout.dataset.swipeReady = '1';
      let startX = null;
      let startY = null;
      let blocked = false;
      let dragging = false;
      let initialOpen = false;
      const controlSelector = [
        'input',
        'textarea',
        'select',
        'button',
        'a',
        '[contenteditable="true"]',
        '.chat-plus-menu',
        '.table-wrap',
        '.thread-menu-panel',
        '.tutor-mobile-nav-sheet',
      ].join(',');
      const isControl = target => Boolean(target?.closest?.(controlSelector));
      const sidebar = () => this.layout?.querySelector('[data-chat-sidebar]');
      const clearDrag = () => {
        this.layout?.classList.remove('thread-swipe-active', 'thread-swipe-dragging');
        this.layout?.style.removeProperty('--thread-drag-x');
        this.layout?.style.removeProperty('--thread-drawer-progress');
        startX = startY = null;
        blocked = dragging = false;
      };
      this.layout.addEventListener('touchstart', event => {
        const touch = event.touches?.[0];
        if (!touch || !this.isThreadsDrawerMode()) return;
        blocked = isControl(event.target);
        startX = touch.clientX;
        startY = touch.clientY;
        initialOpen = this.layout.classList.contains('threads-drawer-open');
        dragging = false;
      }, { passive: true });
      this.layout.addEventListener('touchmove', event => {
        if (startX === null || blocked || !this.isThreadsDrawerMode()) return;
        const touch = event.touches?.[0];
        if (!touch) return;
        const dx = touch.clientX - startX;
        const dy = touch.clientY - startY;
        if (!dragging) {
          if (Math.abs(dx) < 10) return;
          if (Math.abs(dx) <= Math.abs(dy) * 1.15) { blocked = true; return; }
          dragging = true;
          this.layout.classList.add('thread-swipe-active', 'thread-swipe-dragging');
        }
        const drawerWidth = sidebar()?.getBoundingClientRect().width || Math.min(window.innerWidth * .86, 336);
        const offset = initialOpen ? Math.max(-drawerWidth, Math.min(0, dx)) : Math.max(0, Math.min(drawerWidth, dx));
        const progress = initialOpen ? 1 - Math.abs(offset) / drawerWidth : offset / drawerWidth;
        this.layout.style.setProperty('--thread-drag-x', `${offset}px`);
        this.layout.style.setProperty('--thread-drawer-progress', String(Math.max(0, Math.min(1, progress))));
        event.preventDefault();
      }, { passive: false });
      this.layout.addEventListener('touchend', event => {
        if (startX === null || blocked || !this.isThreadsDrawerMode()) { clearDrag(); return; }
        const touch = event.changedTouches?.[0];
        if (!touch) { clearDrag(); return; }
        const dx = touch.clientX - startX;
        const dy = touch.clientY - startY;
        const horizontal = Math.abs(dx) >= 48 && Math.abs(dx) > Math.abs(dy) * 1.15;
        this.layout.classList.remove('thread-swipe-dragging', 'thread-swipe-active');
        this.layout.style.removeProperty('--thread-drag-x');
        this.layout.style.removeProperty('--thread-drawer-progress');
        if (horizontal) {
          if (!initialOpen && dx > 0) this.layout.classList.add('threads-drawer-open');
          if (initialOpen && dx < 0) this.layout.classList.remove('threads-drawer-open');
        }
        this.updateSidebarButtons();
        startX = startY = null;
        blocked = dragging = false;
      }, { passive: true });
      this.layout.addEventListener('touchcancel', clearDrag, { passive: true });
    }

    isThreadsDrawerMode() {
      return window.matchMedia('(max-width: 1279px)').matches;
    }

    toggleThreadsPanel() {
      if (!this.layout) return;
      if (this.isThreadsDrawerMode()) {
        this.layout.classList.toggle('threads-drawer-open');
      } else {
        this.layout.classList.toggle('threads-collapsed');
        try { localStorage.setItem('eduai.ui.tutorSidebarCollapsed.v2', this.layout.classList
          .contains('threads-collapsed') ? '1' : '0'); } catch (_) {}
      }
      this.updateSidebarButtons();
    }

    closeThreadsDrawer() {
      if (!this.layout) return;
      this.layout.classList.remove('threads-drawer-open');
      this.updateSidebarButtons();
    }

    updateSidebarButtons() {
      if (!this.layout) return;
      const drawer = this.isThreadsDrawerMode();
      const open = drawer
        ? this.layout.classList.contains('threads-drawer-open')
        : !this.layout.classList.contains('threads-collapsed');
      this.layout.querySelectorAll('[data-chat-sidebar-toggle]').forEach(button => {
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }

    isNearBottom(threshold = 72) {
      const log = this.$('logId');
      if (!log) return true;
      return (log.scrollHeight - log.scrollTop - log.clientHeight) <= threshold;
    }

    scrollToBottom(behavior = 'smooth') {
      const log = this.$('logId');
      if (!log) return;
      if (typeof log.scrollTo === 'function') log.scrollTo({ top: log.scrollHeight, behavior });
      else log.scrollTop = log.scrollHeight;
      if (this.jumpButton) this.jumpButton.hidden = true;
    }

    jumpByPosition() {
      const log = this.$('logId');
      if (!log) return;
      const max = Math.max(0, log.scrollHeight - log.clientHeight);
      const towardBottom = log.scrollTop < max / 2;
      if (typeof log.scrollTo === 'function') log.scrollTo({ top: towardBottom ? log.scrollHeight : 0,
         behavior: 'smooth' });
      else log.scrollTop = towardBottom ? log.scrollHeight : 0;
    }

    updateJumpButton() {
      if (!this.jumpButton) return;
      const log = this.$('logId');
      if (!log) return;
      const max = Math.max(0, log.scrollHeight - log.clientHeight);
      if (max < 96 || log.scrollTop < 4) { this.jumpButton.hidden = true; return; }
      const towardBottom = log.scrollTop < max / 2;
      this.jumpButton.textContent = towardBottom ? '↓' : '↑';
      this.jumpButton.setAttribute('aria-label', towardBottom ? 'Перейти вниз' : 'Перейти вверх');
      this.jumpButton.setAttribute('title', towardBottom ? 'Вниз' : 'Вверх');
      this.jumpButton.hidden = false;
    }

    resizeComposer() {
      const input = this.$('inputId');
      if (!input) return;
      const mobile = window.matchMedia('(max-width: 767px)').matches;
      const baseHeight = mobile ? 34 : 32;
      const maxHeight = mobile ? 112 : 136;
      if (!String(input.value || '').trim()) {
        input.style.height = `${baseHeight}px`;
        input.style.overflowY = 'hidden';
        return;
      }
      input.style.height = 'auto';
      const nextHeight = Math.min(Math.max(input.scrollHeight, baseHeight), maxHeight);
      input.style.height = `${nextHeight}px`;
      input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
    }

    bindPlusMenu() {
      const form = this.$('formId');
      if (!form) return;
      const wrap = form.querySelector('.chat-plus-wrap');
      const plus = form.querySelector('[data-chat-plus]');
      const menu = form.querySelector('[data-chat-plus-menu]');
      const attachTrigger = form.querySelector('[data-chat-attach-trigger]');
      const interactiveTrigger = form.querySelector('[data-chat-interactive-trigger]');
      const modePreview = form.parentElement?.querySelector('[data-chat-compose-mode]');
      const modeClear = modePreview?.querySelector('[data-chat-compose-mode-clear]');

      const closeMenu = () => {
        if (!menu || !plus) return;
        menu.hidden = true;
        plus.setAttribute('aria-expanded', 'false');
      };
      const toggleMenu = () => {
        if (!menu || !plus) return;
        menu.hidden = !menu.hidden;
        plus.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
      };

      plus?.addEventListener('click', event => { event.stopPropagation(); toggleMenu(); });
      attachTrigger?.addEventListener('click', () => { closeMenu(); this.$('attachId').click(); });
      interactiveTrigger?.addEventListener('click', () => {
        closeMenu();
        this.startInteractiveCompose('create');
      });
      modeClear?.addEventListener('click', () => this.clearInteractiveCompose());
      document.addEventListener('click', event => {
        if (wrap && !wrap.contains(event.target)) closeMenu();
      });
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMenu();
      });
    }

    interactiveActionInput() {
      return this.$('formId')?.querySelector('[data-chat-interactive-action]') || null;
    }

    startInteractiveCompose(action = 'create', appId = null, versionNo = null) {
      this.state.interactiveAction = action;
      this.state.editingInteractiveId = appId || null;
      this.state.editingInteractiveVersion = versionNo ? Number(versionNo) : null;
      const hidden = this.interactiveActionInput();
      if (hidden) hidden.value = action;
      const preview = this.$('formId')?.parentElement?.querySelector('[data-chat-compose-mode]');
      const label = preview?.querySelector('[data-chat-compose-mode-label]');
      if (preview) preview.hidden = false;
      if (label) label.textContent = action === 'edit' ?
         '🧩 Редактирование интерактивного приложения' : '🧩 Создание интерактивного приложения';
      const input = this.$('inputId');
      if (input) {
        if (!input.dataset.defaultPlaceholder) input.dataset.defaultPlaceholder = input.placeholder || '';
        input.placeholder = action === 'edit'
          ? 'Опишите, что изменить: добавить вопросы, таймер, оформление…'
          : 'Опишите приложение: тема, количество вопросов, сложность, оформление…';
        input.focus();
      }
    }

    clearInteractiveCompose() {
      this.state.interactiveAction = null;
      this.state.editingInteractiveId = null;
      this.state.editingInteractiveVersion = null;
      const hidden = this.interactiveActionInput();
      if (hidden) hidden.value = '';
      const preview = this.$('formId')?.parentElement?.querySelector('[data-chat-compose-mode]');
      if (preview) preview.hidden = true;
      const input = this.$('inputId');
      if (input?.dataset.defaultPlaceholder) input.placeholder = input.dataset.defaultPlaceholder;
    }

    async loadSessions(preferredId = null, { loadMessages = true } = {}) {
      try {
        this.state.sessions = await EduAI.api('/api/v1/tutor/sessions');
        const available = this.state.sessions.some(item => String(item
          .session_id) === String(preferredId || this.state.activeId));
        this.state.activeId = available ? String(preferredId || this.state.activeId) : String(this
          .state.sessions[0]?.session_id || '');
        this.renderThreads();
        if (this.state.activeId && loadMessages) await this.loadMessages();
      } catch (error) { EduAI.toast(error.message, 'error'); }
    }

    renderThreads() {
      const query = this.state.threadQuery || '';
      const sessions = query
        ? this.state.sessions.filter(item => `${item.title || ''} ${item.book_title || ''}`
          .toLocaleLowerCase('ru-RU').includes(query))
        : this.state.sessions;
      this.$('threadsId').innerHTML = sessions.map(item => {
        const id = String(item.session_id);
        const active = id === this.state.activeId;
        const telegramDefault = item.chat_type === 'telegram_default';
        const context = item.context_locked
          ? `${item.book_title || 'Учебник'}${item.page_number ? ', стр. ' + item.page_number : ''}`
          : item.active_context_mode === 'attachment'
            ? 'Файловый контекст'
            : `${item.message_count} сообщ.`;
        const meta = telegramDefault ? `Telegram · ${context}` : context;
        const deleteButton = telegramDefault
          ? ''
          : '<button type="button" data-delete>Удалить чат</button>';
        return `<div class="thread-item ${active ? 'active' : ''}" data-session="${id}">
          <button class="thread-open" title="${EduAI.escapeHtml(item.title)}">
            <strong>${EduAI.escapeHtml(item.title)}</strong>
            <small>${EduAI.escapeHtml(meta)}</small>
          </button>
          <details class="thread-menu">
            <summary class="thread-menu-toggle" title="Действия с чатом" aria-label="Действия с чатом">⋮</summary>
            <div class="thread-menu-panel">
              <button type="button" data-rename>Переименовать</button>
              ${deleteButton}
            </div>
          </details>
        </div>`;
      }).join('');
      if (!sessions.length && query) {
        this.$('threadsId').innerHTML = '<p class="chat-thread-empty muted">Чаты не найдены</p>';
      }
      const session = this.state.sessions.find(item => String(item.session_id) === this.state.activeId);
      this.renderContextState(session);
    }

    async threadAction(event) {
      const item = event.target.closest('.thread-item'); if (!item) return;
      const menu = event.target.closest('.thread-menu');
      if (menu && !event.target.closest('[data-delete], [data-rename]')) return;
      if (event.target.closest('[data-delete]')) {
        const current = this.state.sessions.find(x => String(x.session_id) === item.dataset.session);
        if (!confirm(`Удалить чат «${current?.title || 'Новый чат'}» и всю его историю?`)) return;
        try {
          await EduAI.api(`/api/v1/tutor/sessions/${item.dataset.session}`, { method: 'DELETE' });
          if (String(this.state.activeId) === String(item.dataset.session)) this.state.activeId = null;
          await this.loadSessions();
          EduAI.toast('Чат удалён', 'success');
        } catch (error) { EduAI.toast(error.message, 'error'); }
        return;
      }
      if (event.target.closest('[data-rename]')) {
        const current = this.state.sessions.find(x => String(x.session_id) === item.dataset.session);
        const title = prompt('Название чата (до 35 символов):', current?.title || '');
        if (title === null) return;
        const clean = title.trim();
        if (!clean || clean.length > 35) { EduAI
          .toast('Название должно содержать от 1 до 35 символов', 'error'); return; }
        try { await EduAI.api(`/api/v1/tutor/sessions/${item.dataset.session}`, { method: 'PATCH',
           body: JSON.stringify({ title: clean }) }); await this.loadSessions(item.dataset.session); }
        catch (error) { EduAI.toast(error.message, 'error'); }
        return;
      }
      this.state.activeId = item.dataset.session; this.renderThreads(); this.closeThreadsDrawer();
         await this.loadMessages();
    }

    async newChat() {
      try { const session = await EduAI.api('/api/v1/tutor/sessions', { method: 'POST', body: JSON
        .stringify({ title: 'Новый чат' }) }); await this.loadSessions(String(session.session_id)); this
        .closeThreadsDrawer(); this.$('inputId').focus(); }
      catch (error) { EduAI.toast(error.message, 'error'); }
    }

    formatBytes(value) {
      const bytes = Number(value || 0);
      if (!bytes) return '';
      if (bytes < 1024) return `${bytes} Б`;
      if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} КБ`;
      return `${(bytes / 1048576).toFixed(1)} МБ`;
    }

    attachmentHtml(attachment) {
      const name = attachment.original_name || attachment.name || 'Вложение';
      const meta = [attachment.mime_type || attachment.type, this.formatBytes(attachment.size_bytes ||
         attachment.size)].filter(Boolean).join(' · ');
      if (!attachment.download_url && !attachment.preview_url) {
        return `<div class="mt-2 rounded-xl bg-white/[.05] px-3 py-2 text-xs"><strong>📎 ${EduAI
          .escapeHtml(name)}</strong>${meta ? `<span class="ml-2 muted">${EduAI.escapeHtml(meta)}</span>` : ''}</div>`;
      }
      return `<div class="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-white/[.05] px-3 py-2 text-xs">
        <span class="min-w-0 flex-1"><strong class="break-all">📎 ${EduAI.escapeHtml(name)}
          </strong>${meta ? `<span class="ml-2 muted">${EduAI.escapeHtml(meta)}</span>` : ''}</span>
        ${attachment.preview_url ? `<button type="button" class="attachment-action"
           data-chat-attachment="preview" data-url="${EduAI.escapeHtml(attachment.preview_url)}
          " data-name="${EduAI.escapeHtml(name)}">Просмотр</button>` : ''}
        ${attachment.download_url ?
           `<button type="button" class="attachment-action" data-chat-attachment="download" data-url="${EduAI
          .escapeHtml(attachment.download_url)}" data-name="${EduAI.escapeHtml(name)}">Скачать</button>` : ''}
        ${attachment.attachment_id ?
           `<button type="button" class="attachment-action danger" data-chat-attachment="forget"
           data-attachment-id="${Number(attachment.attachment_id)}" data-name="${EduAI.escapeHtml(name)}
          ">Удалить из памяти</button>` : ''}
      </div>`;
    }

    append(sender, text, attachments = [], source = null, interactiveApp = null, options = {}) {
      if (typeof attachments === 'string') attachments = attachments ? [{ original_name: attachments }] : [];
      const follow = options.forceScroll === true || (options.forceScroll !== false && this.isNearBottom());
      const bubble = document.createElement('div');
      bubble.className = `message ${sender === 'user' ? 'user' : ''}`;
      if (options.messageId) bubble.dataset.messageId = String(options.messageId);
      const sourceBadge = source === 'telegram' ? '<span class="message-source">Telegram</span>' : '';
      const senderName = options.senderName || (sender === 'user' ? (this.state.profile
        ?.display_name || this.state.profile?.tg_id || 'Пользователь') : 'ИИ-тьютор');
      const session = EduAI.readSession?.();
      const canCreateTask = sender === 'ai' && ['parent', 'admin'].includes(session?.user?.role) && options.messageId;
      const taskAction = canCreateTask ?
         `<button type="button" class="message-action" data-create-task-from-ai data-message-id="${EduAI
        .escapeHtml(String(options.messageId))}">Создать задание</button>` : '';
      bubble.innerHTML = `<div class="message-meta"><strong>${EduAI.escapeHtml(String(senderName))}
        </strong>${sourceBadge}</div><div class="message-content">${EduAI.markdown(text)}
        </div>${(attachments || []).map(item => this.attachmentHtml(item)).join('')}${this
        .interactiveCardHtml(interactiveApp)}${taskAction ? `<div class="message-actions">${taskAction}</div>` : ''}`;
      this.$('logId').append(bubble);
      EduAI.renderMath?.(bubble);
      if (follow) this.scrollToBottom(options.behavior || 'smooth');
      else this.updateJumpButton();
      return bubble;
    }

    async loadMessages() {
      try {
        const messages = await EduAI.api(`/api/v1/tutor/sessions/${this.state.activeId}/messages`);
        this.$('logId').innerHTML = '';
        // Приветствие является UI-элементом истории: оно не записывается в БД и поэтому не дублируется.
        const displayName = this.state.profile?.display_name || this.state.profile?.tg_id || '';
        this.append('ai', `Добрый день, ${displayName}`, [], null, null, { forceScroll: false,
           senderName: 'ИИ-тьютор' });
        messages.forEach(item => this.append(
          item.sender,
          item.message_text,
          item.attachments?.length ? item.attachments : (item.attachment_name || ''),
          item.message_source,
          item.interactive_app || null,
          { forceScroll: false, behavior: 'auto', senderName: item.sender_name, messageId: item.message_id }
        ));
        requestAnimationFrame(() => this.scrollToBottom('auto'));
      } catch (error) { EduAI.toast(error.message, 'error'); }
    }

    async fetchProtected(url) {
      const session = EduAI.readSession?.();
      const headers = new Headers();
      if (session?.token) headers.set('Authorization', `Bearer ${session.token}`);
      const response = await fetch(url, { headers });
      if (!response.ok) {
        let message = `Ошибка ${response.status}`;
        try { const body = await response.json(); message = body.detail || body.message || message; } catch (_) {}
        throw new Error(message);
      }
      return response.blob();
    }


    interactiveCardHtml(app) {
      if (!app?.app_id) return '';
      const session = EduAI.readSession?.();
      const canAssign = ['parent', 'admin'].includes(session?.user?.role);
      const version = Number(app.version_no || app.current_version || 1);
      const assignAction = canAssign
        ? '<button type="button" class="interactive-card-action" ' +
          'data-interactive-assign>Отправить Ученику</button>'
        : '';
      return `<div class="interactive-chat-card mt-3" data-interactive-app="${EduAI.escapeHtml(app
        .app_id)}" data-interactive-version="${version}">
        <div class="interactive-card-head min-w-0">
          <strong class="interactive-card-title">🧩 ${EduAI.markdown(app.title || 'Интерактивное задание')}</strong>
          <div class="text-xs muted">v${version}${app.question_count ? ` · ${Number(app
            .question_count)} вопросов` : ''}</div>
        </div>
        <div class="interactive-card-actions">
          <button type="button" class="interactive-card-action" data-interactive-open>Открыть</button>
          <button type="button" class="interactive-card-action" data-interactive-edit>Изменить</button>
          <button type="button" class="interactive-card-action" data-interactive-download>Скачать HTML</button>
          ${assignAction}
        </div>
      </div>`;
    }

    async messageAction(event) {
      const taskButton = event.target.closest('[data-create-task-from-ai]');
      if (taskButton) {
        const bubble = taskButton.closest('.message');
        document.dispatchEvent(new CustomEvent('eduai:create-task-from-ai', { detail: {
          messageId: Number(taskButton.dataset.messageId),
          text: bubble?.querySelector('.message-content')?.innerText?.trim() || ''
        }}));
        return;
      }
      const card = event.target.closest('[data-interactive-app]');
      if (card) {
        const appId = card.dataset.interactiveApp;
        const version = Number(card.dataset.interactiveVersion || 1);
        if (event.target.closest('[data-interactive-open]')) {
          window.open(`/interactive/${encodeURIComponent(appId)}?version=${version}`, '_blank',
             'noopener,noreferrer'); return;
        }
        if (event.target.closest('[data-interactive-edit]')) {
          this.startInteractiveCompose('edit', appId, version);
          this.$('inputId').value = '';
          EduAI.toast('Опишите изменение и отправьте сообщение', 'success'); return;
        }
        if (event.target.closest('[data-interactive-download]')) {
          try {
            const blob = await this
              .fetchProtected(`/api/v1/interactive/${encodeURIComponent(appId)}/download?version=${version}`);
            const url = URL.createObjectURL(blob); const link = document.createElement('a');
            link.href = url; link.download = 'interactive.html'; document.body
              .appendChild(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          } catch (error) { EduAI.toast(error.message, 'error'); }
          return;
        }
        if (event.target.closest('[data-interactive-assign]')) { await this.assignInteractive(appId, version); return; }
      }
      await this.attachmentAction(event);
    }
    async assignInteractive(appId, version = 1) {
      try {
        const students = await EduAI.api('/api/v1/interactive/students');
        if (!students.length) { EduAI.toast('Нет привязанных Учеников', 'error'); return; }
        let modal = document.getElementById('interactive-assign-modal');
        if (!modal) {
          modal = document.createElement('div');
          modal.id = 'interactive-assign-modal';
          modal.className = 'modal-backdrop';
          modal.innerHTML = `<div class="modal-panel glass-strong interactive-assign-sheet">
            <div class="flex items-start justify-between gap-3"><div>
            <p class="text-xs font-bold uppercase tracking-wider muted">Интерактивное приложение</p>
            <h2 class="text-xl font-extrabold">Отправить как задание</h2></div>
            <button class="icon-btn" type="button" data-assign-close aria-label="Закрыть">×</button></div>
            <form data-interactive-assign-form class="mt-5 grid gap-4"><div class="field"><label>
            Название</label><input class="input" name="title" maxlength="255" value="Интерактивное задание">
            </div><div class="field"><label>Комментарий Ученику</label>
            <textarea class="textarea" name="comment" maxlength="4000" placeholder="Необязательно"></textarea>
            </div><div class="field"><label>Ученики</label>
            <div data-assign-students class="grid sm:grid-cols-2 gap-2"></div></div>
            <div class="flex flex-col-reverse sm:flex-row justify-end gap-2">
            <button type="button" class="btn-secondary" data-assign-preview>Проверить приложение</button>
            <button type="submit" class="btn-primary">Отправить Ученикам</button></div></form></div>`;
          document.body.appendChild(modal);
          modal.addEventListener('click', event => { if (event.target === modal || event.target
            .closest('[data-assign-close]')) EduAI.closeModal('interactive-assign-modal'); });
        }
        modal.dataset.appId = appId;
        modal.dataset.version = String(version);
        modal.querySelector('[data-assign-students]').innerHTML = students.map(item =>
           `<label class="flex items-center gap-3 rounded-xl bg-white/[.04] p-3">
          <input type="checkbox" name="students" value="${item.tg_id}"><span class="text-sm font-bold">${EduAI
          .escapeHtml(item.username ? '@' + item.username : 'ID ' + item.tg_id)}</span></label>`).join('');
        const form = modal.querySelector('[data-interactive-assign-form]');
        modal.querySelector('[data-assign-preview]').onclick = () => window
          .open(`/interactive/${encodeURIComponent(appId)}?version=${version}`, '_blank', 'noopener,noreferrer');
        form.onsubmit = async event => {
          event.preventDefault();
          const button = event.submitter;
          const studentIds = Array.from(form.querySelectorAll('input[name="students"]:checked'))
            .map(input => Number(input.value));
          if (!studentIds.length) { EduAI.toast('Выберите хотя бы одного Ученика', 'error'); return; }
          EduAI.setBusy(button, true, 'Отправляем…');
          try {
            await EduAI.api(`/api/v1/interactive/${encodeURIComponent(appId)}/assign?version=${version}`, {
              method: 'POST',
              body: JSON.stringify({ student_ids: studentIds, title: form.elements.title.value
                .trim(), comment: form.elements.comment.value.trim() })
            });
            EduAI.closeModal('interactive-assign-modal');
            EduAI.toast('Интерактивное приложение отправлено как задание', 'success');
          } catch (error) { EduAI.toast(error.message, 'error'); }
          finally { EduAI.setBusy(button, false); }
        };
        EduAI.openModal('interactive-assign-modal');
      } catch (error) { EduAI.toast(error.message, 'error'); }
    }

    async attachmentAction(event) {
      const button = event.target.closest('[data-chat-attachment]');
      if (!button) return;
      if (button.dataset.chatAttachment === 'forget') {
        const attachmentId = Number(button.dataset.attachmentId);
        if (!attachmentId) return;
        const fileName = button.dataset.name || 'файл';
        const confirmation =
          `Удалить «${fileName}» из памяти этого пользователя? ` +
          'Вложение исчезнет из истории чата.';
        if (!confirm(confirmation)) return;
        EduAI.setBusy(button, true, 'Удаляем…');
        try {
          const result = await EduAI.api(`/api/v1/attachments/${attachmentId}/memory`, { method: 'DELETE' });
          const message = result.retained_for_tasks
            ? 'Файл удалён из памяти чата; копия сохранена для задания'
            : 'Файл удалён из памяти и хранилища';
          EduAI.toast(message, 'success');
          await this.loadMessages();
          await this.loadSessions(this.state.activeId, { loadMessages: false });
        } catch (error) {
          EduAI.toast(error.message, 'error');
        } finally {
          if (button.isConnected) EduAI.setBusy(button, false);
        }
        return;
      }
      try {
        const blob = await this.fetchProtected(button.dataset.url);
        const objectUrl = URL.createObjectURL(blob);
        if (button.dataset.chatAttachment === 'preview') {
          window.open(objectUrl, '_blank', 'noopener,noreferrer');
          setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
        } else {
          const link = document.createElement('a');
          link.href = objectUrl; link.download = button.dataset.name || 'attachment';
          document.body.appendChild(link); link.click(); link.remove();
          setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        }
      } catch (error) { EduAI.toast(error.message, 'error'); }
    }

    voiceButton() {
      return this.$('formId')?.querySelector('[data-chat-voice]') || null;
    }

    preferredVoiceMimeType() {
      if (!window.MediaRecorder?.isTypeSupported) return '';
      return [
        'audio/webm;codecs=opus',
        'audio/ogg;codecs=opus',
        'audio/mp4',
        'audio/webm',
      ].find(type => MediaRecorder.isTypeSupported(type)) || '';
    }

    async toggleVoiceRecording() {
      const recorder = this.state.voiceRecorder;
      if (recorder && recorder.state === 'recording') {
        recorder.stop();
        return;
      }
      if (this.state.pendingRequest) {
        EduAI.toast('Дождитесь ответа Umnix или остановите текущий запрос.', 'info');
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        EduAI.toast('Этот браузер не поддерживает запись голосовых сообщений.', 'error');
        return;
      }

      const button = this.voiceButton();
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = this.preferredVoiceMimeType();
        const recorderOptions = mimeType ? { mimeType } : undefined;
        const nextRecorder = new MediaRecorder(stream, recorderOptions);
        this.state.voiceStream = stream;
        this.state.voiceRecorder = nextRecorder;
        this.state.voiceChunks = [];

        nextRecorder.addEventListener('dataavailable', event => {
          if (event.data?.size) this.state.voiceChunks.push(event.data);
        });
        nextRecorder.addEventListener('stop', () => this.finishVoiceRecording(), { once: true });
        nextRecorder.start(250);
        button?.classList.add('is-recording');
        button?.setAttribute('aria-pressed', 'true');
        button?.setAttribute('aria-label', 'Остановить запись и отправить голосовое сообщение');
        button?.setAttribute('title', 'Остановить и отправить');
        if (button) button.innerHTML = '<span aria-hidden="true">■</span>';
        this.state.voiceStopTimer = window.setTimeout(() => {
          if (nextRecorder.state === 'recording') nextRecorder.stop();
        }, 120000);
        EduAI.toast('Запись началась. Нажмите ещё раз, чтобы остановить и отправить.', 'info');
      } catch (error) {
        this.releaseVoiceStream();
        if (error?.name === 'NotAllowedError') {
          EduAI.toast('Разрешите доступ к микрофону в настройках браузера.', 'error');
        } else {
          EduAI.toast('Не удалось начать запись голоса.', 'error');
        }
      }
    }

    releaseVoiceStream() {
      if (this.state.voiceStopTimer) window.clearTimeout(this.state.voiceStopTimer);
      this.state.voiceStopTimer = null;
      this.state.voiceStream?.getTracks?.().forEach(track => track.stop());
      this.state.voiceStream = null;
    }

    async finishVoiceRecording() {
      const button = this.voiceButton();
      const recorder = this.state.voiceRecorder;
      const chunks = this.state.voiceChunks.slice();
      const mimeType = recorder?.mimeType || chunks[0]?.type || 'audio/webm';
      this.state.voiceRecorder = null;
      this.state.voiceChunks = [];
      this.releaseVoiceStream();
      button?.classList.remove('is-recording');
      button?.classList.add('is-transcribing');
      button?.setAttribute('aria-pressed', 'false');
      button?.setAttribute('aria-label', 'Голосовое сообщение');
      button?.setAttribute('title', 'Голосовое сообщение');
      if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="voice-spinner" aria-hidden="true"></span>';
      }

      try {
        const blob = new Blob(chunks, { type: mimeType });
        if (!blob.size) throw new Error('Запись получилась пустой');
        const extension = mimeType.includes('ogg') ? 'ogg' : mimeType.includes('mp4') ? 'm4a' : 'webm';
        const form = new FormData();
        form.append('audio', blob, `voice.${extension}`);
        const result = await EduAI.api('/api/v1/tutor/transcribe', { method: 'POST', body: form });
        const text = String(result?.text || '').trim();
        if (!text) throw new Error('Не удалось распознать речь');
        const input = this.$('inputId');
        input.value = text;
        this.resizeComposer();
        const chatForm = this.$('formId');
        if (typeof chatForm.requestSubmit === 'function') chatForm.requestSubmit();
        else chatForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      } catch (error) {
        EduAI.toast(error.message || 'Не удалось отправить голосовое сообщение', 'error');
      } finally {
        button?.classList.remove('is-transcribing');
        if (button) {
          button.disabled = false;
          button.innerHTML = '<span aria-hidden="true">🎙</span>';
        }
      }
    }

    async send(event) {
      event.preventDefault();
      const formElement = this.$('formId');
      const button = event.submitter || formElement.querySelector('button[type="submit"], button:not([type])');
      const input = this.$('inputId');
      if (this.state.voiceRecorder?.state === 'recording') {
        EduAI.toast('Сначала остановите запись голосового сообщения.', 'info');
        return;
      }
      if (this.state.pendingRequest) {
        EduAI.toast('Дождитесь ответа Umnix или нажмите «Остановить».', 'info');
        return;
      }
      let stopThinking = () => {};
      let abortedByUser = false;
      const controller = new AbortController();
      this.state.pendingRequest = controller;
      const originalText = input.value;
      const text = originalText.trim();
      const file = this.$('attachId').files[0];
      const interactiveAction = this.interactiveActionInput()?.value || this.state.interactiveAction || '';
      try {
        if (!this.state.activeId) await this.loadSessions();
        if (!this.state.activeId) throw new Error('Не удалось создать чат. Обновите страницу.');
        if (!text && !file) {
          if (interactiveAction) EduAI
            .toast('Сначала опишите, какое интерактивное приложение нужно создать или изменить', 'error');
          return;
        }
        const isPdf = file && (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'));
        const sizeLimit = isPdf ? 100 * 1024 * 1024 : 15 * 1024 * 1024;
        if (file && file.size > sizeLimit) throw new Error(`Максимальный размер ${isPdf ? 'PDF' :
           'файла'} — ${isPdf ? 100 : 15} МБ`);

        // Clear the composer immediately after the user sends the request. This
        // prevents repeated accidental submits while the AI is still working.
        input.value = '';
        this.resizeComposer();
        EduAI.setFormDisabled?.(formElement, true);
        this.append('user', text || 'Проанализируй вложение', file ? [{ original_name: file.name,
           mime_type: file.type, size_bytes: file.size }] : [], null, null, { forceScroll: true, senderName:
           this.state.profile?.display_name });

        const form = new FormData();
        form.append('session_id', this.state.activeId);
        form.append('message_text', text);
        if (interactiveAction) form.append('interactive_action', interactiveAction);
        if (this.state.editingInteractiveId) form.append('interactive_app_id', this.state.editingInteractiveId);
        if (this.state.editingInteractiveVersion) form.append('interactive_version', String(this
          .state.editingInteractiveVersion));
        if (file) form.append('attachment', file);
        const mapping = [['classId','book_class'],['subjectId','book_program'],['bookId','book_id'],
          ['pageId','page_id']];
        mapping.forEach(([id,key]) => { const element = this.$(id); if (element && element
          .value) form.append(key, element.value); });
        EduAI.setBusy(button, true, interactiveAction ? 'Создаём…' : 'Отправляем…');
        stopThinking = EduAI.startThinking(
          interactiveAction === 'edit' ? 'Umnix думает · изменяет приложение' :
          interactiveAction === 'create' ? 'Umnix думает · создаёт приложение' :
          file ? 'Umnix думает · анализирует вложение' : 'Umnix думает · формулирует ответ',
          { onCancel: () => { abortedByUser = true; controller.abort(); } }
        );
        const result = await EduAI.api('/api/v1/tutor/messages', { method: 'POST', body: form,
           signal: controller.signal });
        this.append('ai', result.message_text, [], null, result.interactive_app || null, {
           senderName: result.sender_name || 'Umnix', messageId: result.message_id });
        if (!result.interactive_error) {
          this.clearAttachment();
          this.clearInteractiveCompose();
        } else {
          // Keep the failed request editable, but do not leave it in the box while
          // the request is in flight.
          input.value = originalText;
          this.resizeComposer();
          EduAI.toast('Интерактивное приложение не создано. Запрос возвращён в поле — можно уточнить.', 'error');
        }
        await this.loadSessions(result.session_id, { loadMessages: false });
      } catch (error) {
        const aborted = error?.name === 'AbortError' || abortedByUser || controller.signal.aborted;
        if (aborted) {
          input.value = originalText;
          this.resizeComposer();
          EduAI.toast('Запрос остановлен. Текст возвращён в поле ввода.', 'info');
        } else {
          console.error('Umnix tutor submit failed', error);
          input.value = originalText;
          this.resizeComposer();
          EduAI.toast(error.message || 'Не удалось отправить сообщение', 'error');
        }
      } finally {
        stopThinking();
        this.state.pendingRequest = null;
        EduAI.setBusy(button, false);
        EduAI.setFormDisabled?.(formElement, false);
        input.focus();
      }
    }

    previewAttachment() {
      const file = this.$('attachId').files[0];
      this.$('attachmentPreviewId').hidden = !file;
      this.$('attachmentNameId').textContent = file ? `📎 ${file.name} · ${(file.size / 1048576).toFixed(1)} МБ` : '';
    }
    clearAttachment() { this.$('attachId').value = ''; this.$('attachmentPreviewId').hidden = true; }

    async loadClasses() {
      try { const values = await EduAI.api('/api/v1/tutor/context/classes'); this.$('classId')
        .innerHTML = '<option value="">Класс (необязательно)</option>' + values.map(x => `<option value="${x}
        ">${x} класс</option>`).join(''); }
      catch (error) { EduAI.toast(error.message, 'error'); }
    }
    async loadSubjects() {
      this.resetSelect('subjectId', 'Предмет (необязательно)'); this.resetSelect('bookId',
         'Учебник (необязательно)'); this.resetSelect('pageId', 'Страница / параграф');
      if (!this.$('classId').value) return;
      const values = await EduAI.api(`/api/v1/tutor/context/subjects?book_class=${this.$('classId').value}`);
      this.$('subjectId').innerHTML += values.map(x => `<option value="${EduAI.escapeHtml(x)}">${EduAI
        .escapeHtml(x)}</option>`).join('');
    }
    async loadBooks() {
      this.resetSelect('bookId', 'Учебник (необязательно)'); this.resetSelect('pageId', 'Страница / параграф');
      if (!this.$('subjectId').value) return;
      const query = new URLSearchParams({ book_class: this.$('classId').value, book_program: this
        .$('subjectId').value });
      const values = await EduAI.api(`/api/v1/tutor/context/books?${query}`);
      this.$('bookId').innerHTML += values.map(x => `<option value="${x.book_id}">${EduAI.escapeHtml(x
        .book_title)} · ${EduAI.escapeHtml(x.book_author)}</option>`).join('');
    }
    async loadPages() {
      this.resetSelect('pageId', 'Страница / параграф'); if (!this.$('bookId').value) return;
      const values = await EduAI.api(`/api/v1/tutor/context/pages?book_id=${this.$('bookId').value}`);
      this.$('pageId').innerHTML += values.map(x => `<option value="${x.page_id}">стр. ${x
        .page_number}${x.page_paragraph ? ' · ' + EduAI.escapeHtml(x.page_paragraph) : ''}</option>`).join('');
    }
    resetSelect(id, label) { this.$(id).innerHTML = `<option value="">${label}</option>`; }
    async lockContext() {
      if (!this.$('bookId').value) { EduAI.toast('Выберите учебник', 'error'); return; }
      const payload = { book_id: Number(this.$('bookId').value) };
      if (this.$('pageId').value) payload.page_id = Number(this.$('pageId').value);
      try { await EduAI.api(`/api/v1/tutor/sessions/${this.state.activeId}/context`, { method: 'PUT',
         body: JSON.stringify(payload) }); this.layout?.classList.remove('book-panel-open'); EduAI
        .toast('Учебник закреплён', 'success'); await this.loadSessions(this.state.activeId); }
      catch (error) { EduAI.toast(error.message, 'error'); }
    }
    async exitContext() {
      try { await EduAI.api(`/api/v1/tutor/sessions/${this.state.activeId}/context`, { method:
         'DELETE' }); EduAI.toast('Учебник откреплён', 'success'); await this.loadSessions(this.state.activeId); }
      catch (error) { EduAI.toast(error.message, 'error'); }
    }
    renderContextState(session) {
      const locked = Boolean(session?.context_locked);
      const mode = session?.active_context_mode || (locked ? 'book' : 'general');
      this.$('contextStatusId').textContent = locked ? `🔒 ${session.book_title}${session
        .page_number ? ', стр. ' + session.page_number : ''}` : mode === 'attachment' ?
         '📎 Активен файловый контекст' : 'Автопоиск по тексту вопроса';
      this.$('exitId').hidden = !locked;
    }
  }
  window.EduAIChat = ChatUI;
})();
