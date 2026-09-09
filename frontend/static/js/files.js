document.addEventListener('DOMContentLoaded', async () => {
  const user = await EduAI.guard(['student', 'parent', 'admin']);
  if (!user) return;

  window.Telegram?.WebApp?.ready();
  window.Telegram?.WebApp?.expand();

  const root = document.getElementById('files-library');
  const search = document.getElementById('files-search');
  const state = { groups: [], query: '' };
  const objectUrls = new Set();

  const tutorSection = user.role === 'student' ? 'tutor' : 'assistant';
  const tutorPath = user.role === 'student' ? '/student.html' : '/parent.html';

  document.getElementById('files-back')?.addEventListener('click', () => {
    location.href = `${tutorPath}?section=${encodeURIComponent(tutorSection)}`;
  });
  document.getElementById('files-refresh')?.addEventListener('click', () => loadLibrary());
  search?.addEventListener('input', event => {
    state.query = String(event.target.value || '').trim().toLocaleLowerCase('ru-RU');
    render();
  });

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
    return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  }

  function formatDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function fileKind(file) {
    const mime = String(file.mime_type || '').toLowerCase();
    if (mime.startsWith('image/')) return { icon: '▧', label: 'Изображение', image: true };
    if (mime === 'application/pdf') return { icon: 'PDF', label: 'PDF', image: false };
    if (mime.includes('word') || /\.docx?$/i.test(file.original_name || '')) return { icon: 'DOC',
       label: 'Документ', image: false };
    return { icon: '▤', label: 'Файл', image: false };
  }

  async function protectedBlob(url) {
    const session = EduAI.readSession();
    const headers = new Headers();
    if (session?.token) headers.set('Authorization', `Bearer ${session.token}`);
    const response = await fetch(url, { headers });
    if (!response.ok) {
      let message = `Ошибка ${response.status}`;
      try { const data = await response.json(); message = data.detail || data.message || message; } catch (_) {}
      throw new Error(message);
    }
    return response.blob();
  }

  async function openProtected(file, mode) {
    const url = mode === 'preview' ? file.preview_url : file.download_url;
    const blob = await protectedBlob(url);
    const objectUrl = URL.createObjectURL(blob);
    objectUrls.add(objectUrl);
    if (mode === 'preview') {
      const opened = window.open(objectUrl, '_blank', 'noopener,noreferrer');
      if (!opened) throw new Error('Разрешите открытие новой вкладки для просмотра файла');
      setTimeout(() => { URL.revokeObjectURL(objectUrl); objectUrls.delete(objectUrl); }, 60000);
      return;
    }
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = file.original_name || 'attachment';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => { URL.revokeObjectURL(objectUrl); objectUrls.delete(objectUrl); }, 1500);
  }

  function chatHref(group) {
    return `${tutorPath}?section=${encodeURIComponent(tutorSection)}&chat=${encodeURIComponent(group.session_id)}`;
  }

  function visibleGroups() {
    if (!state.query) return state.groups;
    return state.groups.map(group => {
      const groupText = `${group.title || ''} ${group.source || ''}`.toLocaleLowerCase('ru-RU');
      const attachments = (group.attachments || []).filter(file =>
        groupText.includes(state.query) || String(file.original_name || '')
          .toLocaleLowerCase('ru-RU').includes(state.query)
      );
      return { ...group, attachments };
    }).filter(group => group.attachments.length);
  }

  function render() {
    const groups = visibleGroups();
    if (!groups.length) {
      root.innerHTML = `<div class="empty-state glass card"><div><div class="text-3xl mb-3">▣</div>
        <p>${state.query ? 'Ничего не найдено' : 'В чатах пока нет сохранённых файлов'}</p></div></div>`;
      return;
    }

    root.innerHTML = groups.map(group => `
      <section class="file-chat-group glass card" data-library-session="${EduAI.escapeHtml(group.session_id)}">
        <header class="file-chat-group-head">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="file-source-badge ${group.source === 'telegram' ? 'telegram' : ''}
                ">${group.source === 'telegram' ? 'Telegram' : 'WebApp'}</span>
              <h2 class="truncate text-lg font-extrabold">${EduAI.escapeHtml(group.title || 'Новый чат')}</h2>
            </div>
            <p class="mt-1 text-xs muted">${group.attachments.length} файл(а/ов)</p>
          </div>
          <a class="btn-secondary file-open-chat" href="${EduAI.escapeHtml(chatHref(group))}">Открыть чат</a>
        </header>
        <div class="file-card-grid">
          ${group.attachments.map(file => {
            const kind = fileKind(file);
            return `<article class="file-card" data-attachment-id="${file.attachment_id}">
              <div class="file-card-preview ${kind.image ? 'has-image' : ''}" ${kind.image ?
                 `data-library-thumb="${EduAI.escapeHtml(file.preview_url)}"` : ''}>
                <span class="file-card-icon">${kind.icon}</span>
              </div>
              <div class="file-card-body">
                <strong class="file-card-name" title="${EduAI.escapeHtml(file
                  .original_name)}">${EduAI.escapeHtml(file.original_name)}</strong>
                <p class="file-card-meta">${EduAI.escapeHtml(kind.label)} · ${EduAI
                  .escapeHtml(formatBytes(file.size_bytes))}</p>
                <p class="file-card-meta">${EduAI.escapeHtml(formatDate(file.created_at))}</p>
                <div class="file-card-actions">
                  <button class="attachment-action" type="button"
                     data-file-preview="${file.attachment_id}">Просмотр</button>
                  <button class="attachment-action" type="button"
                     data-file-download="${file.attachment_id}">Скачать</button>
                  <button class="attachment-action danger" type="button"
                     data-file-forget="${file.attachment_id}">Удалить из памяти</button>
                </div>
              </div>
            </article>`;
          }).join('')}
        </div>
      </section>
    `).join('');

    hydrateThumbnails();
  }

  function findFile(id) {
    const numeric = Number(id);
    for (const group of state.groups) {
      const file = (group.attachments || []).find(item => Number(item.attachment_id) === numeric);
      if (file) return file;
    }
    return null;
  }

  async function hydrateThumbnails() {
    const nodes = [...root.querySelectorAll('[data-library-thumb]')];
    await Promise.all(nodes.map(async node => {
      try {
        const blob = await protectedBlob(node.dataset.libraryThumb);
        const url = URL.createObjectURL(blob);
        objectUrls.add(url);
        node.style.backgroundImage = `url("${url}")`;
        node.classList.add('loaded');
      } catch (_) {
        node.classList.remove('loaded');
      }
    }));
  }

  root.addEventListener('click', async event => {
    const preview = event.target.closest('[data-file-preview]');
    const download = event.target.closest('[data-file-download]');
    const forget = event.target.closest('[data-file-forget]');
    const button = preview || download || forget;
    if (!button) return;
    const id = button.dataset.filePreview || button.dataset.fileDownload || button.dataset.fileForget;
    const file = findFile(id);
    if (!file) return;
    try {
      if (preview) await openProtected(file, 'preview');
      if (download) await openProtected(file, 'download');
      if (forget) {
        if (!confirm(`Удалить «${file.original_name}» из памяти чатов? Файл исчезнет из истории чата.`)) return;
        EduAI.setBusy(forget, true, 'Удаляем…');
        const result = await EduAI.api(`/api/v1/attachments/${file.attachment_id}/memory`, { method: 'DELETE' });
        EduAI.toast(result.retained_for_tasks ?
           'Файл удалён из памяти чата; копия сохранена для задания' : 'Файл удалён из памяти и хранилища', 'success');
        await loadLibrary();
      }
    } catch (error) {
      EduAI.toast(error.message, 'error');
    } finally {
      if (forget?.isConnected) EduAI.setBusy(forget, false);
    }
  });

  async function loadLibrary() {
    try {
      const result = await EduAI.api('/api/v1/attachments/library');
      state.groups = Array.isArray(result?.groups) ? result.groups : [];
      render();
    } catch (error) {
      root.innerHTML = `<div class="empty-state glass card"><p>${EduAI.escapeHtml(error.message)}</p></div>`;
      EduAI.toast(error.message, 'error');
    }
  }

  window.addEventListener('beforeunload', () => objectUrls.forEach(url => URL.revokeObjectURL(url)));
  await loadLibrary();
});
