(() => {
  const POLL_INTERVAL_MS = 4000;

  function escapeHtml(value) {
    return EduAI.escapeHtml(String(value ?? ''));
  }

  function statusText(status) {
    return {
      matching: 'Предварительный просмотр',
      pending: 'В очереди',
      processing: 'Оцифровывается',
      completed: 'Готово',
      failed: 'Ошибка'
    }[status] || status;
  }

  function metadataPayload(card) {
    return {
      book_class: Number(card.querySelector('[data-field="book_class"]').value),
      book_program: card.querySelector('[data-field="book_program"]').value.trim(),
      book_author: card.querySelector('[data-field="book_author"]').value.trim(),
      book_title: card.querySelector('[data-field="book_title"]').value.trim()
    };
  }

  function metadataCard(job) {
    const error = job.error_text
      ? `<p class="mt-2 text-sm text-rose-200">${escapeHtml(job.error_text)}</p>`
      : '';
    return `
      <article class="digitization-preview-card" data-job-id="${job.job_id}">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h4 class="font-extrabold break-words">${escapeHtml(job.original_name)}</h4>
            <p class="mt-1 text-xs muted">Проверьте данные перед сохранением в Базу Данных.</p>
            ${error}
          </div>
          <span class="badge">${statusText(job.status)}</span>
        </div>
        <div class="mt-4 grid sm:grid-cols-2 gap-3">
          <label class="field">
            <span>Класс</span>
            <input
              class="input"
              data-field="book_class"
              type="number"
              min="1"
              max="11"
              value="${escapeHtml(job.proposed_book_class || '')}"
              required
            >
          </label>
          <label class="field">
            <span>Предмет</span>
            <input
              class="input"
              data-field="book_program"
              value="${escapeHtml(job.proposed_book_program || '')}"
              required
            >
          </label>
          <label class="field">
            <span>Автор</span>
            <input
              class="input"
              data-field="book_author"
              value="${escapeHtml(job.proposed_book_author || '')}"
            >
          </label>
          <label class="field">
            <span>Название</span>
            <input
              class="input"
              data-field="book_title"
              value="${escapeHtml(job.proposed_book_title || '')}"
              required
            >
          </label>
        </div>
      </article>`;
  }

  function queueCard(job) {
    const progress = job.total_pages
      ? `${job.processed_pages || 0}/${job.total_pages} стр.`
      : '';
    const error = job.error_text
      ? `<p class="mt-2 text-sm text-rose-200">${escapeHtml(job.error_text)}</p>`
      : '';
    const retry = job.status === 'failed'
      ? `
        <button class="btn-secondary retry-digitization" data-job-id="${job.job_id}" type="button">
          Повторить
        </button>`
      : '';
    return `
      <article class="digitization-queue-card">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h4 class="font-extrabold break-words">${escapeHtml(job.original_name)}</h4>
            <p class="mt-1 text-sm muted">
              ${statusText(job.status)}${progress ? ` · ${progress}` : ''}
            </p>
            <p class="mt-1 text-xs muted">Этап: ${escapeHtml(job.stage || '—')}</p>
            ${error}
          </div>
          ${retry}
        </div>
      </article>`;
  }

  function validateFiles(files) {
    if (!files.length) {
      return 'Выберите PDF или ZIP.';
    }
    if (files.length > 20) {
      return 'За один пакет можно выбрать не более 20 файлов.';
    }
    const names = files.map((file) => file.name.toLowerCase());
    const zipCount = names.filter((name) => name.endsWith('.zip')).length;
    const invalid = names.some((name) => !name.endsWith('.pdf') && !name.endsWith('.zip'));
    if (invalid) {
      return 'Поддерживаются только PDF и ZIP.';
    }
    if (zipCount && (zipCount !== 1 || files.length !== 1)) {
      return 'ZIP нужно загружать отдельно от PDF.';
    }
    return '';
  }

  async function init(options = {}) {
    const refreshBooks = options.refreshBooks || (async () => {});
    const fileInput = document.getElementById('pdf-file');
    const dropZone = document.getElementById('drop-zone');
    const fileLabel = document.getElementById('file-label');
    const actionButton = document.getElementById('digitization-action');
    const preview = document.getElementById('digitization-preview');
    const queue = document.getElementById('digitization-queue');
    const queueRefresh = document.getElementById('refresh-digitization-queue');
    if (!fileInput || !dropZone || !actionButton || !preview || !queue) {
      return;
    }

    let batchId = null;
    let batchJobs = [];
    let phase = 'select';

    function selectedFiles() {
      return Array.from(fileInput.files || []);
    }

    function renderSelection() {
      const files = selectedFiles();
      fileLabel.textContent = files.length
        ? files.map((file) => file.name).join(', ')
        : 'или выберите несколько PDF или один ZIP';
      actionButton.disabled = !files.length;
      if (phase !== 'select') {
        batchId = null;
        batchJobs = [];
        phase = 'select';
        preview.innerHTML = '';
        actionButton.textContent = 'Предварительный просмотр';
      }
    }

    function renderPreview() {
      const editable = batchJobs.filter((job) => !job.duplicate && job.status === 'matching');
      const duplicates = batchJobs.filter((job) => job.duplicate);
      preview.innerHTML = `
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="font-extrabold">Предварительный просмотр</h3>
            <p class="mt-1 text-sm muted">
              Метаданные извлечены из имени файла. Их можно исправить до оцифровки.
            </p>
          </div>
          ${duplicates.length ? `<span class="badge">Дубликатов: ${duplicates.length}</span>` : ''}
        </div>
        <div class="mt-4 grid gap-4">
          ${editable.map(metadataCard).join('') || '<p class="muted">Нет новых PDF для оцифровки.</p>'}
        </div>`;
      actionButton.disabled = !editable.length;
      actionButton.textContent = 'Оцифровать';
    }

    async function loadQueue() {
      try {
        const jobs = await EduAI.api('/api/v1/admin/digitization/jobs');
        const active = jobs.filter((job) => job.status !== 'matching');
        queue.innerHTML = active.map(queueCard).join('') || '<p class="muted">Очередь пока пуста.</p>';
      } catch (error) {
        EduAI.toast(error.message, 'error');
      }
    }

    async function uploadForPreview() {
      const files = selectedFiles();
      const validationError = validateFiles(files);
      if (validationError) {
        EduAI.toast(validationError, 'error');
        return;
      }
      const form = new FormData();
      files.forEach((file) => form.append('files', file));
      EduAI.setBusy(actionButton, true, 'Анализируем названия…');
      try {
        const result = await EduAI.api('/api/v1/admin/digitization/upload', {
          method: 'POST',
          body: form
        });
        batchId = result.batch_id;
        batchJobs = result.jobs || [];
        phase = 'preview';
        renderPreview();
      } catch (error) {
        EduAI.toast(error.message, 'error');
      } finally {
        EduAI.setBusy(actionButton, false);
      }
    }

    async function saveMetadata() {
      const cards = Array.from(preview.querySelectorAll('[data-job-id]'));
      for (const card of cards) {
        const payload = metadataPayload(card);
        if (!payload.book_class || payload.book_class < 1 || payload.book_class > 11) {
          throw new Error('Проверьте класс: допустимы значения от 1 до 11.');
        }
        if (!payload.book_program || !payload.book_title) {
          throw new Error('Для каждого учебника нужны предмет и название.');
        }
        await EduAI.api(`/api/v1/admin/digitization/jobs/${card.dataset.jobId}/metadata`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
      }
    }

    async function startDigitization() {
      if (!batchId) {
        return;
      }
      EduAI.setBusy(actionButton, true, 'Сохраняем данные…');
      try {
        await saveMetadata();
        if (!window.confirm('Вы точно проверили информацию об Учебнике?')) {
          return;
        }
        await EduAI.api(`/api/v1/admin/digitization/batches/${batchId}/confirm`, {
          method: 'POST'
        });
        EduAI.toast('Учебники поставлены в последовательную очередь оцифровки.', 'success');
        fileInput.value = '';
        fileLabel.textContent = 'или выберите несколько PDF или один ZIP';
        batchId = null;
        batchJobs = [];
        phase = 'select';
        preview.innerHTML = '';
        actionButton.textContent = 'Предварительный просмотр';
        actionButton.disabled = true;
        await Promise.all([loadQueue(), refreshBooks()]);
      } catch (error) {
        EduAI.toast(error.message, 'error');
      } finally {
        EduAI.setBusy(actionButton, false);
      }
    }

    fileInput.addEventListener('change', renderSelection);
    ['dragenter', 'dragover'].forEach((type) => {
      dropZone.addEventListener(type, (event) => {
        event.preventDefault();
        dropZone.classList.add('dragging');
      });
    });
    ['dragleave', 'drop'].forEach((type) => {
      dropZone.addEventListener(type, (event) => {
        event.preventDefault();
        dropZone.classList.remove('dragging');
      });
    });
    dropZone.addEventListener('drop', (event) => {
      const transfer = new DataTransfer();
      Array.from(event.dataTransfer.files || []).forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      renderSelection();
    });
    actionButton.addEventListener('click', async () => {
      if (phase === 'select') {
        await uploadForPreview();
      } else {
        await startDigitization();
      }
    });
    queueRefresh?.addEventListener('click', loadQueue);
    queue.addEventListener('click', async (event) => {
      const retry = event.target.closest('.retry-digitization');
      if (!retry) {
        return;
      }
      try {
        await EduAI.api(`/api/v1/admin/digitization/jobs/${retry.dataset.jobId}/retry`, {
          method: 'POST'
        });
        EduAI.toast('Задача повторно поставлена в очередь.', 'success');
        await loadQueue();
      } catch (error) {
        EduAI.toast(error.message, 'error');
      }
    });

    renderSelection();
    await loadQueue();
    window.setInterval(loadQueue, POLL_INTERVAL_MS);
  }

  window.UmnixDigitization = { init };
})();
