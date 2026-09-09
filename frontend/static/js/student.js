document.addEventListener('DOMContentLoaded', async () => {
  EduAI.initShell();

  const user = await EduAI.guard(['student']);
  if (!user) return;

  window.Telegram?.WebApp?.ready();
  window.Telegram?.WebApp?.expand();

  const state = { dashboard: null };
  const byId = id => document.getElementById(id);

  function empty(text) {
    return `
      <div class="empty-state glass col-span-full">
        <div>
          <div class="text-3xl mb-3">○</div>
          <p>${EduAI.escapeHtml(text)}</p>
        </div>
      </div>
    `;
  }

  function formatFileSize(bytes) {
    const size = Number(bytes || 0);
    if (size < 1024) return `${size} Б`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
    return `${(size / 1024 / 1024).toFixed(1)} МБ`;
  }

  function isPreviewable(file) {
    const mime = String(file.mime_type || '').toLowerCase();
    return (
      mime.startsWith('image/') ||
      mime === 'application/pdf' ||
      mime.startsWith('text/')
    );
  }

  async function fetchProtectedFile(url) {
    const session = EduAI.readSession();
    const headers = new Headers();

    if (session?.token) {
      headers.set('Authorization', `Bearer ${session.token}`);
    }

    const response = await fetch(url, { headers });

    if (!response.ok) {
      let message = `Ошибка ${response.status}`;
      try {
        const body = await response.json();
        message = body.detail || body.message || message;
      } catch (_) {}
      throw new Error(message);
    }

    return response.blob();
  }

  async function previewProtectedFile(url) {
    const blob = await fetchProtectedFile(url);
    const objectUrl = URL.createObjectURL(blob);
    const opened = window.open(objectUrl, '_blank', 'noopener');

    if (!opened) {
      URL.revokeObjectURL(objectUrl);
      throw new Error('Разрешите открытие новой вкладки для просмотра файла');
    }

    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  }

  async function downloadProtectedFile(url, filename) {
    const blob = await fetchProtectedFile(url);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = objectUrl;
    link.download = filename || 'attachment';
    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  function renderTaskAttachments(task) {
    const attachments = task.attachments || [];

    if (!attachments.length) return '';

    return `
      <div class="mt-4 grid gap-2">
        <p class="text-xs font-bold muted">Материалы задания</p>

        ${attachments.map(file => `
          <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-white/[.04] p-3">
            <div class="min-w-0">
              <p class="truncate text-sm font-bold">
                📎 ${EduAI.escapeHtml(file.original_name)}
              </p>
              <p class="text-xs muted">
                ${formatFileSize(file.size_bytes)}
              </p>
            </div>

            <div class="flex flex-wrap gap-2">
              ${isPreviewable(file) ? `
                <button
                  type="button"
                  class="btn-secondary task-file-preview"
                  data-url="${EduAI.escapeHtml(file.preview_url)}"
                >
                  Открыть
                </button>
              ` : ''}

              <button
                type="button"
                class="btn-secondary task-file-download"
                data-url="${EduAI.escapeHtml(file.download_url)}"
                data-name="${EduAI.escapeHtml(file.original_name)}"
              >
                Скачать
              </button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function taskMentorLabel(task) {
    return task?.mentor_kind === 'parent' ? 'Родителя' : 'Учителя';
  }

  function taskStatusLabel(status, task = null) {
    if (status === 'pending_review' && task
      ?.assignment_source === 'teacher') return `Ожидает проверки ${taskMentorLabel(task)}`;
    return ({ created: 'Новое', in_progress: 'В процессе', pending_review: 'На проверке', completed:
       'Выполнено', evaluated: 'Проверено' })[status] || 'Задание';
  }

  function taskPreviewText(task) {
    const questions = task.questions_json || {};
    const items = Array.isArray(questions.items) ? questions.items : [];
    return questions.question_text || items[0]?.question_text || items[0]?.question || task.topic ||
       'Откройте карточку, чтобы посмотреть условие.';
  }

  function renderTaskCards(tasks) {
    return tasks.length
      ? tasks.map(task => {
          const questions = task.questions_json || {};
          const context = task.topic_context || {};
          const title = task.title || questions.title || `Задание №${task.task_id}`;
          const subject = task.subject || context.subject || 'Учёба';
          const sourceLabel = `От ${taskMentorLabel(task)}`;
          return `
            <article class="glass compact-record-card" data-task-summary="${task.task_id}
              " tabindex="0" role="button" aria-label="Открыть ${EduAI.escapeHtml(title)}">
              <div class="flex items-center justify-between gap-2">
                <span class="badge">${sourceLabel}</span>
                <span class="text-xs muted">${EduAI.escapeHtml(taskStatusLabel(task.status, task))}</span>
              </div>
              <h3 class="record-title mt-3 text-base font-extrabold">${EduAI.escapeHtml(title)}</h3>
              <p class="mt-1 text-xs muted">${EduAI.escapeHtml(subject)}${task.topic ?
                 ` · ${EduAI.escapeHtml(task.topic)}` : ''}</p>
              <div class="record-preview mt-2 text-sm muted">${EduAI
                .escapeHtml(String(taskPreviewText(task)).replace(/[#*_`]/g, ''))}</div>
              <div class="record-footer flex items-center justify-between gap-2 text-xs
                 muted"><span>${EduAI.formatDate(task.created_at)}</span><span>Открыть →</span></div>
            </article>`;
        }).join('')
      : empty('Здесь пока ничего нет.');
  }

  function ensureTaskDetailModal() {
    let modal = document.getElementById('student-task-detail-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'student-task-detail-modal';
    modal.className = 'modal-backdrop record-detail-modal';
    modal.innerHTML = `<div class="modal-panel glass-strong">
      <div class="flex items-start justify-between gap-3"><div>
      <p class="text-xs font-bold uppercase tracking-wider muted">Подробности</p>
      <h2 data-student-task-title class="text-xl font-extrabold">Задание</h2></div>
      <button class="icon-btn" type="button" data-close-modal="student-task-detail-modal"
       aria-label="Закрыть">×</button></div><div data-student-task-body class="mt-5"></div></div>`;
    document.body.append(modal);
    modal.querySelector('[data-close-modal]')?.addEventListener('click', () => EduAI
      .closeModal('student-task-detail-modal'));
    modal.addEventListener('click', event => { if (event.target === modal) EduAI
      .closeModal('student-task-detail-modal'); });
    return modal;
  }

  function renderTaskDetail(task) {
    const questions = task.questions_json || {};
    const context = task.topic_context || {};
    const items = Array.isArray(questions.items) ? questions.items : [];
    const body = questions.question_text || (items.length ? items.map((item, index) => `${index + 1}
      . ${item.question_text || item.question || ''}`).join('\n\n') : 'Условие не указано.');
    return `
      <div class="grid gap-4">
        <div class="flex flex-wrap gap-2"><span class="badge">От ${taskMentorLabel(task)}
          </span><span class="badge">${EduAI.escapeHtml(taskStatusLabel(task.status, task))}</span>${task
          .subject ? `<span class="badge">${EduAI.escapeHtml(task.subject)}</span>` : ''}</div>
        ${task.topic ? `<p class="text-sm"><span class="muted">Тема:</span> ${EduAI.escapeHtml(task.topic)}</p>` : ''}
        <section class="rounded-2xl bg-white/[.035] p-4"><h3 class="font-extrabold">Условие</h3>
          <div class="mt-3 leading-7">${EduAI.markdown(body)}</div></section>
        ${task.parent_comment ? `<section class="rounded-2xl bg-violet-300/[.07] p-4">
          <p class="text-xs font-bold text-violet-200">Комментарий ${taskMentorLabel(task)}
          </p><p class="mt-2">${EduAI.escapeHtml(task.parent_comment)}</p></section>` : ''}
        ${renderTaskAttachments(task)}
        ${questions.interactive_app_id ?
           `<a class="btn-primary" href="/interactive/${encodeURIComponent(questions.interactive_app_id)}
          ${questions.interactive_version ? `?version=${encodeURIComponent(questions.interactive_version)}` :
           ''}" target="_blank" rel="noopener noreferrer">Открыть интерактивное задание</a>` : ''}
        ${task.student_answers_json?.verification_feedback ?
           `<section class="rounded-2xl bg-white/[.04] p-4"><h3 class="font-extrabold">Последняя проверка</h3>
          <div class="mt-2 text-sm muted">${EduAI.markdown(task.student_answers_json.verification_feedback)}
          </div></section>` : ''}
        <form class="task-form grid gap-2" data-task-id="${task.task_id}" ${questions
          .interactive_app_id ? 'hidden' : ''}>
          <label class="text-xs font-bold muted" for="answer-${task.task_id}">Ваш ответ</label>
          <input id="answer-${task.task_id}" class="input" maxlength="4000" required placeholder="Введите ответ">
          <label class="text-xs font-bold muted" for="submission-files-${task.task_id}
            ">Файлы или фотографии (необязательно, до 10)</label>
          <input id="submission-files-${task.task_id}
            " class="input" type="file" name="attachments" multiple
             accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.txt,.md,.csv,.rtf">
          <button class="btn-primary justify-self-start" type="submit">Отправить ${taskMentorLabel(task)}</button>
        </form>
      </div>`;
  }

  function openTaskDetail(taskId) {
    const task = (state.dashboard?.tasks || []).find(item => String(item.task_id) === String(taskId));
    if (!task) return;
    const modal = ensureTaskDetailModal();
    modal.querySelector('[data-student-task-title]').textContent = task.title || task.questions_json
      ?.title || `Задание №${task.task_id}`;
    modal.querySelector('[data-student-task-body]').innerHTML = renderTaskDetail(task);
    EduAI.openModal('student-task-detail-modal');
  }


  function renderDashboard(data) {
    state.dashboard = data;

    byId('task-count-badge').textContent = data.tasks.length;
    byId('tasks-list').innerHTML = renderTaskCards(data.tasks || []);
  }

  async function loadDashboard() {
    try {
      const data = await EduAI.api('/api/v1/student/dashboard');
      renderDashboard(data);
    } catch (error) {
      EduAI.toast(error.message, 'error');
    }
  }

  document.addEventListener('submit', async event => {
    const form = event.target.closest('.task-form');
    if (!form) return;

    event.preventDefault();

    const button = form.querySelector('button[type="submit"]');
    const answer = form.querySelector('input').value.trim();

    if (!answer) {
      EduAI.toast('Введите ответ', 'error');
      return;
    }

    EduAI.setBusy(button, true, 'Проверяем…');

    try {
      const body = new FormData();
      body.append('student_answer', answer);
      const files = Array.from(form.querySelector('input[type="file"]')?.files || []);
      if (files.length > 10) throw new Error('Можно прикрепить не более 10 файлов');
      files.forEach(file => body.append('attachments', file));
      const result = await EduAI.api(
        `/api/v1/student/tasks/${form.dataset.taskId}/submit`,
        { method: 'POST', body }
      );

      EduAI.toast(result.message || 'Ответ отправлен Учителю на проверку.', 'success');

      await loadDashboard();
    } catch (error) {
      EduAI.toast(error.message, 'error');
    } finally {
      EduAI.setBusy(button, false);
    }
  });

  document.addEventListener('click', async event => {
    const summary = event.target.closest('[data-task-summary]');
    if (summary && !event.target.closest('button,a,input,form')) { openTaskDetail(summary.dataset
      .taskSummary); return; }
    const previewButton = event.target.closest('.task-file-preview');
    const downloadButton = event.target.closest('.task-file-download');

    if (!previewButton && !downloadButton) return;

    const button = previewButton || downloadButton;
    EduAI.setBusy(button, true, previewButton ? 'Открываем…' : 'Скачиваем…');

    try {
      if (previewButton) {
        await previewProtectedFile(button.dataset.url);
      } else {
        await downloadProtectedFile(
          button.dataset.url,
          button.dataset.name
        );
      }
    } catch (error) {
      EduAI.toast(error.message, 'error');
    } finally {
      EduAI.setBusy(button, false);
    }
  });

  document.addEventListener('keydown', event => {
    const summary = event.target.closest?.('[data-task-summary]');
    if (summary && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault();
       openTaskDetail(summary.dataset.taskSummary); }
  });

  byId('refresh-dashboard').addEventListener('click', loadDashboard);
  byId('refresh-tasks').addEventListener('click', loadDashboard);

  const chat = new EduAIChat({
    newChatId: 'new-chat',
    threadsId: 'chat-threads',
    formId: 'chat-form',
    inputId: 'chat-input',
    logId: 'chat-log',
    attachId: 'chat-attachment',
    removeAttachId: 'chat-remove-attachment',
    attachmentPreviewId: 'chat-attachment-preview',
    attachmentNameId: 'chat-attachment-name',
    classId: 'chat-class',
    subjectId: 'chat-subject',
    bookId: 'chat-book',
    pageId: 'chat-page',
    lockId: 'chat-lock-context',
    exitId: 'chat-exit-context',
    contextStatusId: 'chat-context-status',
    welcome: 'Добрый день' 
  });

  await Promise.all([
    loadDashboard(),
    chat.init()
  ]);
});
