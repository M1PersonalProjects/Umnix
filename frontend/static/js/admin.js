document.addEventListener('DOMContentLoaded', async () => {
  EduAI.initShell(); const user = await EduAI.guard(['admin']); if (!user) return;
  const $=id=>document.getElementById(id); const state={books:[],pages:[],bookStep:1};
  const empty=text=>`<div class="empty-state glass col-span-full"><p>${EduAI.escapeHtml(text)}</p></div>`;
  async function loadOverview(){try{const d=await EduAI.api('/api/v1/admin/overview');['users','books',
    'pages','tasks'].forEach(k=>$(`count-${k}`).textContent=d[k].toLocaleString('ru-RU'));}catch(e){EduAI
    .toast(e.message,'error');}}
  async function loadBooks(){
    try{
      state.books=await EduAI.api('/api/v1/admin/books');

      const folderStateKey='eduai.admin.bookFolders.v1';
      let folderState={};
      try{
        folderState=JSON.parse(localStorage.getItem(folderStateKey)||'{}');
      }catch(_){
        folderState={};
      }

      const saveFolderState=()=>{
        localStorage.setItem(folderStateKey,JSON.stringify(folderState));
      };

      const normalize=value=>String(value??'').trim()||'Без предмета';

      const grouped=new Map();
      for(const book of state.books){
        const classKey=String(book.book_class??'Без класса');
        const subjectKey=normalize(book.book_program);

        if(!grouped.has(classKey)){
          grouped.set(classKey,new Map());
        }
        const subjects=grouped.get(classKey);
        if(!subjects.has(subjectKey)){
          subjects.set(subjectKey,[]);
        }
        subjects.get(subjectKey).push(book);
      }

      const classSort=(a,b)=>{
        const na=Number(a),nb=Number(b);
        if(Number.isFinite(na)&&Number.isFinite(nb))return na-nb;
        return String(a).localeCompare(String(b),'ru');
      };

      const renderBookCard=b=>`
        <article class="glass card flex flex-col">
          <div class="flex justify-between">
            <span class="badge">
              ${b.book_class} класс · ${EduAI.escapeHtml(b.book_program)}
            </span>
            <span class="text-xs muted">${b.pages_count} стр.</span>
          </div>
          <h3 class="mt-4 font-extrabold">
            ${EduAI.escapeHtml(b.book_title)}
          </h3>
          <p class="mt-2 text-sm muted flex-1">
            ${EduAI.escapeHtml(b.book_author)}
          </p>
          <div class="mt-4 grid grid-cols-3 gap-2">
            <button class="btn-secondary edit-book" data-id="${b.book_id}">
              Править
            </button>
            <button class="btn-secondary upload-book-action" data-id="${b.book_id}">
              PDF
            </button>
            <button class="btn-danger delete-book" data-id="${b.book_id}">
              Удалить
            </button>
          </div>
        </article>`;

      const renderSubjectFolder=(classKey,subject,books)=>{
        const folderKey=`subject:${classKey}:${subject}`;
        const isOpen=folderState[folderKey]!==false;

        return `
          <section class="book-subject-folder rounded-2xl bg-white/[.025] border border-white/5">
            <button
              type="button"
              class="book-folder-toggle flex w-full items-center justify-between gap-3 p-4 text-left"
              data-folder-key="${EduAI.escapeHtml(folderKey)}"
              aria-expanded="${isOpen?'true':'false'}"
            >
              <span class="flex min-w-0 items-center gap-3">
                <span class="text-xl">${isOpen?'📂':'📁'}</span>
                <span class="min-w-0">
                  <strong class="block truncate">${EduAI.escapeHtml(subject)}</strong>
                  <span class="text-xs muted">
                    ${books.length} ${books.length===1?'учебник':'учебников'}
                  </span>
                </span>
              </span>
              <span class="muted">${isOpen?'▾':'▸'}</span>
            </button>

            <div
              class="book-folder-content px-4 pb-4"
              data-folder-content="${EduAI.escapeHtml(folderKey)}"
              ${isOpen?'':'hidden'}
            >
              <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
                ${books
                  .slice()
                  .sort((a,b)=>String(a.book_title).localeCompare(String(b.book_title),'ru'))
                  .map(renderBookCard)
                  .join('')}
              </div>
            </div>
          </section>`;
      };

      const renderClassFolder=(classKey,subjects)=>{
        const folderKey=`class:${classKey}`;
        const isOpen=folderState[folderKey]!==false;
        const bookCount=Array.from(subjects.values())
          .reduce((sum,items)=>sum+items.length,0);

        return `
          <section class="book-class-folder glass overflow-hidden">
            <button
              type="button"
              class="book-folder-toggle flex w-full items-center justify-between gap-3 p-4 sm:p-5 text-left"
              data-folder-key="${EduAI.escapeHtml(folderKey)}"
              aria-expanded="${isOpen?'true':'false'}"
            >
              <span class="flex min-w-0 items-center gap-3">
                <span class="text-2xl">${isOpen?'📂':'📁'}</span>
                <span class="min-w-0">
                  <strong class="block text-lg">
                    ${EduAI.escapeHtml(classKey)} класс
                  </strong>
                  <span class="text-xs muted">
                    ${subjects.size} предметов · ${bookCount} учебников
                  </span>
                </span>
              </span>
              <span class="text-lg muted">${isOpen?'▾':'▸'}</span>
            </button>

            <div
              class="book-folder-content border-t border-white/5 p-3 sm:p-4"
              data-folder-content="${EduAI.escapeHtml(folderKey)}"
              ${isOpen?'':'hidden'}
            >
              <div class="grid gap-3">
                ${Array.from(subjects.entries())
                  .sort(([a],[b])=>a.localeCompare(b,'ru'))
                  .map(([subject,books])=>renderSubjectFolder(classKey,subject,books))
                  .join('')}
              </div>
            </div>
          </section>`;
      };

      $('books-grid').className='grid gap-4';
      $('books-grid').innerHTML=state.books.length
        ? Array.from(grouped.entries())
            .sort(([a],[b])=>classSort(a,b))
            .map(([classKey,subjects])=>renderClassFolder(classKey,subjects))
            .join('')
        : empty('Учебников пока нет.');

      if(!$('books-grid').dataset.folderHandler){
        $('books-grid').dataset.folderHandler='1';
        $('books-grid').addEventListener('click',event=>{
          const toggle=event.target.closest('.book-folder-toggle');
          if(!toggle)return;

          const key=toggle.dataset.folderKey;
          const content=Array.from(
            $('books-grid').querySelectorAll('[data-folder-content]')
          ).find(item=>item.dataset.folderContent===key);
          if(!content)return;

          const open=content.hidden;
          content.hidden=!open;
          toggle.setAttribute('aria-expanded',String(open));
          folderState[key]=open;
          saveFolderState();

          const icon=toggle.querySelector('.text-2xl, .text-xl');
          if(icon)icon.textContent=open?'📂':'📁';

          const arrow=toggle.lastElementChild;
          if(arrow)arrow.textContent=open?'▾':'▸';
        });
      }

      const opts='<option value="">Выберите учебник</option>'+
        state.books
          .slice()
          .sort((a,b)=>
            Number(a.book_class)-Number(b.book_class) ||
            String(a.book_program).localeCompare(String(b.book_program),'ru') ||
            String(a.book_title).localeCompare(String(b.book_title),'ru')
          )
          .map(b=>`
            <option value="${b.book_id}">
              ${b.book_class} кл. · ${EduAI.escapeHtml(b.book_program)} · ${EduAI.escapeHtml(b.book_title)}
            </option>`)
          .join('');

      $('editor-book').innerHTML=opts;
    }catch(e){
      EduAI.toast(e.message,'error');
    }
  }
  function setBookStep(n){state.bookStep=Math.max(1,Math.min(4,n));document.querySelectorAll('.book-step')
    .forEach(x=>x.hidden=Number(x.dataset.bookStep)!==state.bookStep);$('book-step-label').textContent=state
    .bookStep;$('book-progress').style.width=`${state.bookStep*25}%`;$('book-prev').disabled=state
    .bookStep===1;$('book-next').hidden=state.bookStep===4;$('book-save').hidden=state.bookStep!==4;}
  function openBook(book=null){$('book-form').reset();$('book-id').value=book?.book_id||'';
    $('book-modal-title').textContent=book?'Изменить учебник':'Новый учебник';if(book){$('book-class')
    .value=book.book_class;$('book-program').value=book.book_program;$('book-author').value=book.book_author;
    $('book-title').value=book.book_title;}setBookStep(1);EduAI.openModal('book-modal');}
  $('new-book').addEventListener('click',()=>openBook());$('book-prev').addEventListener('click',()=>
    setBookStep(state.bookStep-1));$('book-next').addEventListener('click',()=>{const ids=['book-class',
    'book-program','book-author'];const field=$(ids[state.bookStep-1]);if(!field.value.trim()){EduAI
    .toast('Заполните текущий шаг','error');return;}setBookStep(state.bookStep+1);});
  $('book-form').addEventListener('submit',async e=>{e.preventDefault();const id=$('book-id').value;
    const b=e.submitter;const payload={book_class:Number($('book-class').value),book_program:$('book-program')
    .value.trim(),book_author:$('book-author').value.trim(),book_title:$('book-title').value.trim()};EduAI
    .setBusy(b,true,'Сохраняем…');try{await EduAI.api(id?`/api/v1/admin/books/${id}`:'/api/v1/admin/books',{
    method:id?'PUT':'POST',body:JSON.stringify(payload)});EduAI.closeModal('book-modal');EduAI
    .toast('Учебник сохранён','success');await Promise.all([loadBooks(),loadOverview()]);}catch(err){EduAI
    .toast(err.message,'error');}finally{EduAI.setBusy(b,false);}});
  $('books-grid').addEventListener('click',async e=>{const edit=e.target.closest('.edit-book');const del=e
    .target.closest('.delete-book');const upload=e.target.closest('.upload-book-action');
    if(edit)openBook(state.books.find(b=>b.book_id===Number(edit.dataset.id)));if(upload){document
    .querySelector('[data-section="digitization"]').click();}if(del&&
    confirm('Удалить учебник и все его страницы? Это действие нельзя отменить.')){try{await EduAI
    .api(`/api/v1/admin/books/${del.dataset.id}`,{method:'DELETE'});EduAI.toast('Учебник удалён','success');
    await Promise.all([loadBooks(),loadOverview()]);}catch(err){EduAI.toast(err.message,'error');}}});

  await window.UmnixDigitization?.init({refreshBooks: loadBooks});
  async function loadPages(bookId){if(!bookId){state.pages=[];$('editor-page')
    .innerHTML='<option>Выберите учебник</option>';return;}try{state.pages=await EduAI
    .api(`/api/v1/admin/books/${bookId}/pages`);$('editor-page')
    .innerHTML='<option value="">Выберите страницу</option>'+state.pages.map(p=>`<option value="${p.page_id}
    ">Страница ${p.page_number} · ${EduAI.escapeHtml(p.page_title||'Без заголовка')}</option>`).join('');}
    catch(e){EduAI.toast(e.message,'error');}}
  $('editor-book').addEventListener('change',e=>loadPages(e.target.value));$('editor-page')
    .addEventListener('change',e=>{const p=state.pages.find(x=>x.page_id===Number(e.target.value));
    $('editor-empty').hidden=!!p;$('editor-workspace').hidden=!p;if(!p)return;$('page-id').value=p.page_id;
    $('page-number').value=p.page_number;$('page-title').value=p.page_title||'';$('page-paragraph').value=p
    .page_paragraph||'';$('page-markdown').value=p.page_markdown||'';$('page-html').value=p.page_html||'';
    $('page-text').value=p.page_text||'';$('page-image').src=p.page_image||'';});
  document.querySelectorAll('.editor-tab').forEach(b=>b.addEventListener('click',()=>{document
    .querySelectorAll('.editor-tab').forEach(x=>x.classList.toggle('btn-primary',x===b));document
    .querySelectorAll('.editor-pane').forEach(x=>x.hidden=x.dataset.pane!==b.dataset.tab);}));document
    .querySelector('.editor-tab').click();
  $('page-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;
    const payload={page_number:Number($('page-number').value),page_title:$('page-title').value||null,
    page_paragraph:$('page-paragraph').value||null,page_markdown:$('page-markdown').value.replaceAll('$',''),
    page_html:$('page-html').value,page_text:$('page-text').value};EduAI.setBusy(b,true,'Сохраняем…');try{
    await EduAI.api(`/api/v1/admin/pages/${$('page-id').value}`,{method:'PUT',body:JSON.stringify(payload)});
    EduAI.toast('Страница сохранена','success');await loadPages($('editor-book').value);}catch(err){EduAI
    .toast(err.message,'error');}finally{EduAI.setBusy(b,false);}});

  async function loadUsers(){const q=new URLSearchParams();if($('user-role').value)q.set('role',
    $('user-role').value);if($('user-search').value.trim())q.set('search',$('user-search').value.trim());try{
    const [users,families]=await Promise.all([EduAI.api('/api/v1/admin/users?'+q),EduAI
    .api('/api/v1/admin/family-tree')]);const roleText=u=>u.role==='parent'?(u.mentor_kind==='parent'?
    'Родитель':'Учитель'):(EduAI.roleLabel?.(u.role)||u.role);$('users-body').innerHTML=users.map(u=>
    `<tr><td>${u.tg_id}</td><td>${EduAI.escapeHtml(u.username?'@'+u.username:'—')}
    </td><td><span class="badge">${EduAI.escapeHtml(roleText(u))}</span></td><td>${u.parent_id||'—'}
    </td><td>${EduAI.formatDate(u.created_at)}</td></tr>`).join('')||
    '<tr><td colspan="5" class="text-center muted">Ничего не найдено</td></tr>';$('family-tree')
    .innerHTML=families.length?families.map(f=>{const mentor=f.mentor_kind==='parent'?'Родитель':'Учитель';
    return `<article class="glass card"><p class="font-extrabold">${EduAI.escapeHtml(f.parent_username?'@'+f
    .parent_username:mentor+' '+f.parent_id)}</p><span class="badge mt-2">${mentor}
    </span><div class="mt-3 grid gap-2">${f.children.length?f.children.map(c=>
    `<div class="rounded-xl bg-white/[.04] p-2 text-sm">↳ ${EduAI.escapeHtml(c.username?'@'+c.username:
    'Ученик '+c.tg_id)}</div>`).join(''):'<p class="text-sm muted">Нет привязанных Учеников</p>'}
    </div></article>`}).join(''):empty('Связей наставник–Ученик пока нет.');}catch(e){EduAI.toast(e.message,'error');}}
  $('find-users').addEventListener('click',loadUsers);$('user-search').addEventListener('keydown',e=>{if(e
    .key==='Enter')loadUsers();});
  const ACTIVITY_PREVIEW_LIMIT = 260;

  function activityRoleLabel(role, sender, mentorKind = null) {
    if (sender === 'assistant') return 'ИИ-тьютор';
    if (role === 'parent') return mentorKind === 'parent' ? 'Родитель' : 'Учитель';
    return {
      student: 'Ученик',
      admin: 'Администратор'
    }[role] || 'Пользователь';
  }

  function activityTypeLabel(type, sender) {
    if (type === 'chat') {
      return sender === 'assistant' ? 'Ответ ИИ' : 'Сообщение чата';
    }
    return {
      task: 'Задание',
      event: 'Событие',
      file: 'Файл',
      session: 'Чат-сессия'
    }[type] || type;
  }

  function activityUserLabel(item) {
    const role = activityRoleLabel(item.user_role, item.sender, item.mentor_kind);
    const name = item.username
      ? `@${item.username}`
      : `ID ${item.user_id}`;
    return `${role} · ${name}`;
  }

  function activityPreview(text, limit = ACTIVITY_PREVIEW_LIMIT) {
    const value = String(text || '');
    if (value.length <= limit) return value;

    let cut = value.slice(0, limit);
    const lastSpace = cut.lastIndexOf(' ');
    if (lastSpace > Math.floor(limit * 0.72)) {
      cut = cut.slice(0, lastSpace);
    }
    return `${cut.trimEnd()}…`;
  }

  function renderActivityDetail(text) {
    const renderer = EduAI.renderRichContent || EduAI.markdown;
    return renderer
      ? renderer(String(text || ''))
      : EduAI.escapeHtml(String(text || ''));
  }

  function renderActivityCard(item) {
    const detail = String(item.detail || '');
    const isLong = detail.length > ACTIVITY_PREVIEW_LIMIT;
    const preview = isLong ? activityPreview(detail) : detail;

    const sessionMeta = item.session_id
      ? `
        <p class="mt-1 text-xs muted break-words">
          Чат: ${
            item.session_title
              ? EduAI.escapeHtml(item.session_title)
              : 'Без названия'
          }
          · ${EduAI.escapeHtml(String(item.session_id))}
        </p>`
      : '';

    return `
      <article
        class="activity-card glass card min-w-0"
        data-activity-id="${EduAI.escapeHtml(`${item.type}:${item.id}`)}"
        data-expanded="false"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="badge">
                ${EduAI.escapeHtml(activityTypeLabel(item.type, item.sender))}
              </span>
              <strong class="text-sm">
                ${EduAI.escapeHtml(activityUserLabel(item))}
              </strong>
            </div>
            ${sessionMeta}
          </div>

          <time class="text-xs muted shrink-0">
            ${EduAI.formatDate(item.created_at)}
          </time>
        </div>

        <div class="activity-message-preview mt-4 text-sm leading-6 break-words">
          ${renderActivityDetail(preview)}
        </div>

        ${isLong ? `
          <div
            class="activity-message-full mt-4 text-sm leading-6 break-words"
            hidden
          >
            ${renderActivityDetail(detail)}
          </div>

          <button
            type="button"
            class="activity-toggle btn-secondary mt-4 text-sm"
            aria-expanded="false"
          >
            Показать полностью
          </button>` : ''}
      </article>
    `;
  }

  async function loadActivity() {
    try {
      const params = new URLSearchParams();
      const tgId = $('activity-tg-id')?.value.trim();
      const query = $('activity-search')?.value.trim();
      if (tgId) params.set('tg_id', tgId);
      if (query) params.set('q', query);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const items = await EduAI.api(`/api/v1/admin/activity${suffix}`);
      $('activity-list').innerHTML = items.length
        ? items.map(renderActivityCard).join('')
        : empty('Событий пока нет.');

      if (EduAI.renderMath) {
        EduAI.renderMath($('activity-list'));
      }
    } catch (e) {
      EduAI.toast(e.message, 'error');
    }
  }

    $('activity-filter')?.addEventListener('click', loadActivity);
  $('activity-search')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') loadActivity();
  });
  $('activity-tg-id')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') loadActivity();
  });

  $('activity-list').addEventListener('click', event => {
    const button = event.target.closest('.activity-toggle');
    if (!button) return;

    const card = button.closest('.activity-card');
    if (!card) return;

    const preview = card.querySelector('.activity-message-preview');
    const full = card.querySelector('.activity-message-full');
    if (!preview || !full) return;

    const expanded = card.dataset.expanded === 'true';

    card.dataset.expanded = String(!expanded);
    preview.hidden = !expanded;
    full.hidden = expanded;
    button.textContent = expanded
      ? 'Показать полностью'
      : 'Свернуть';
    button.setAttribute('aria-expanded', String(!expanded));

    if (!expanded && EduAI.renderMath) {
      EduAI.renderMath(full);
    }
  });

  $('refresh-activity').addEventListener('click',loadActivity);$('refresh-admin')
    .addEventListener('click',()=>Promise.all([loadOverview(),loadBooks()]));document
    .querySelectorAll('.jump-section').forEach(b=>b.addEventListener('click',()=>document
    .querySelector(`[data-section="${b.dataset.target}"]`).click()));
  await Promise.all([loadOverview(),loadBooks(),loadUsers(),loadActivity()]);
});
