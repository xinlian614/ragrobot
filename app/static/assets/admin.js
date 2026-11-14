(() => {
  const el = {
    statDocs: document.getElementById('statDocs'),
    statReady: document.getElementById('statReady'),
    statChunks: document.getElementById('statChunks'),
    dropzone: document.getElementById('dropzone'),
    fileInput: document.getElementById('fileInput'),
    pendingList: document.getElementById('pendingList'),
    uploadBtn: document.getElementById('uploadBtn'),
    clearBtn: document.getElementById('clearBtn'),
    uploadState: document.getElementById('uploadState'),
    uploadLog: document.getElementById('uploadLog'),
    docTableBody: document.getElementById('docTableBody'),
    refreshBtn: document.getElementById('refreshBtn'),
    configGrid: document.getElementById('configGrid'),
    uploadHint: document.getElementById('uploadHint'),
    toast: document.getElementById('toast'),
  };

  const TOKEN_KEY = 'rag_admin_token';
  const API = new URLSearchParams(location.search).get('token');
  if (API) sessionStorage.setItem(TOKEN_KEY, API);

  let selectedFiles = [];
  let pollTimer = null;
  let maxFileMb = 20;

  /** 读取管理口令 */
  const getToken = () => sessionStorage.getItem(TOKEN_KEY) || '';

  /** 带管理口令的请求，遇到 401 时提示输入口令并重试一次 */
  async function request(url, options = {}, retry = true) {
    const headers = new Headers(options.headers || {});
    const token = getToken();
    if (token) headers.set('X-Admin-Token', token);

    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401 && retry) {
      const pwd = window.prompt('请输入管理口令');
      if (pwd) {
        sessionStorage.setItem(TOKEN_KEY, pwd);
        return request(url, options, false);
      }
    }
    return resp;
  }

  /** 解析响应 JSON，失败时抛出带服务端信息的异常 */
  async function readJson(resp) {
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `请求失败（${resp.status}）`);
    }
    return data;
  }

  /** 显示底部提示 */
  function showToast(message) {
    el.toast.textContent = message;
    el.toast.classList.add('show');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => el.toast.classList.remove('show'), 2200);
  }

  /** 字节数转可读文本 */
  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }

  /** 转义展示用文本 */
  function textNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  /** 渲染模型配置卡片 */
  function renderConfig(config) {
    const isBm25 = config.embedding_provider === 'bm25';
    const items = [
      ['对话模型', config.chat_model],
      ['接口地址', config.openai_base_url],
      ['检索方式', isBm25 ? 'BM25 关键词检索（本地）' : '向量检索（API）'],
      ['向量模型', isBm25 ? '无需向量模型' : config.embedding_model],
      ['向量接口地址', isBm25 ? '-' : config.embedding_base_url],
      ['API 密钥', config.api_key],
      ['分块大小 / 重叠', `${config.chunk_size} / ${config.chunk_overlap} 字符`],
      ['检索条数', `Top ${config.top_k}`],
      ['管理口令', config.admin_password_enabled ? '已启用' : '未启用'],
    ];
    el.configGrid.innerHTML = '';
    items.forEach(([label, value]) => {
      const item = document.createElement('div');
      item.className = 'config-item';
      item.appendChild(textNode('div', 'config-key', label));
      item.appendChild(textNode('div', 'config-val', String(value)));
      el.configGrid.appendChild(item);
    });
  }

  /** 加载统计与模型配置 */
  async function loadOverview() {
    try {
      const data = await readJson(await request('/api/admin/overview'));
      el.statDocs.textContent = data.stats.documents;
      el.statReady.textContent = data.stats.ready_documents;
      el.statChunks.textContent = data.stats.chunks;
      maxFileMb = data.config.max_file_mb;
      el.uploadHint.textContent = `支持 PDF、DOCX、TXT、Markdown，单文件不超过 ${maxFileMb}MB`;
      renderConfig(data.config);
    } catch (error) {
      showToast(error.message);
    }
  }

  /** 渲染文档表格行 */
  function renderDocuments(documents) {
    el.docTableBody.innerHTML = '';
    if (!documents.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.className = 'empty';
      cell.colSpan = 7;
      cell.textContent = '知识库还没有文档，先上传一份试试';
      row.appendChild(cell);
      el.docTableBody.appendChild(row);
      return;
    }

    const statusMap = {
      ready: ['ready', '已就绪'],
      processing: ['processing', '解析中'],
      failed: ['failed', '失败'],
    };

    documents.forEach((doc) => {
      const row = document.createElement('tr');

      const fileCell = document.createElement('td');
      const fileBox = document.createElement('div');
      fileBox.className = 'file-cell';
      fileBox.appendChild(textNode('span', 'file-name', doc.filename));
      if (doc.status === 'failed' && doc.error) {
        fileBox.appendChild(textNode('span', 'file-error', doc.error));
      }
      fileCell.appendChild(fileBox);

      const [statusClass, statusText] = statusMap[doc.status] || ['processing', doc.status];
      const statusCell = document.createElement('td');
      statusCell.appendChild(textNode('span', `badge ${statusClass}`, statusText));

      const actionCell = document.createElement('td');
      const deleteBtn = textNode('button', 'icon-btn', '删除');
      deleteBtn.addEventListener('click', () => removeDocument(doc));
      actionCell.appendChild(deleteBtn);

      row.appendChild(fileCell);
      row.appendChild(textNode('td', '', doc.ext.toUpperCase()));
      row.appendChild(textNode('td', '', formatSize(doc.size)));
      row.appendChild(textNode('td', '', doc.status === 'ready' ? String(doc.chunk_count) : '-'));
      row.appendChild(statusCell);
      row.appendChild(textNode('td', '', doc.created_at));
      row.appendChild(actionCell);
      el.docTableBody.appendChild(row);
    });

    if (documents.some((doc) => doc.status === 'processing')) {
      startPolling();
    } else {
      stopPolling();
    }
  }

  /** 加载文档列表 */
  async function loadDocuments() {
    try {
      const data = await readJson(await request('/api/admin/documents'));
      renderDocuments(data.documents);
    } catch (error) {
      el.docTableBody.innerHTML = '';
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.className = 'empty';
      cell.colSpan = 7;
      cell.textContent = error.message;
      row.appendChild(cell);
      el.docTableBody.appendChild(row);
    }
  }

  /** 轮询刷新，直到没有解析中的文档 */
  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setTimeout(async () => {
      pollTimer = null;
      await Promise.all([loadOverview(), loadDocuments()]);
    }, 2500);
  }

  /** 停止轮询 */
  function stopPolling() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  /** 删除文档 */
  async function removeDocument(doc) {
    if (!window.confirm(`确定删除「${doc.filename}」及其全部知识分块吗？`)) return;
    try {
      await readJson(await request(`/api/admin/documents/${doc.id}`, { method: 'DELETE' }));
      showToast('已删除');
      await Promise.all([loadOverview(), loadDocuments()]);
    } catch (error) {
      showToast(error.message);
    }
  }

  /** 更新待上传列表与按钮状态 */
  function renderPending() {
    el.pendingList.innerHTML = '';
    selectedFiles.forEach((file, index) => {
      const item = document.createElement('div');
      item.className = 'pending-item';
      item.appendChild(textNode('span', 'name', file.name));
      item.appendChild(textNode('span', 'size', formatSize(file.size)));

      const removeBtn = textNode('button', 'remove-file', '×');
      removeBtn.title = '移除';
      removeBtn.addEventListener('click', () => {
        selectedFiles.splice(index, 1);
        renderPending();
      });
      item.appendChild(removeBtn);
      el.pendingList.appendChild(item);
    });
    el.uploadBtn.disabled = selectedFiles.length === 0;
    el.clearBtn.disabled = selectedFiles.length === 0;
  }

  /** 追加文件到待上传列表（按名称与大小去重） */
  function addFiles(files) {
    const existing = new Set(selectedFiles.map((file) => `${file.name}:${file.size}`));
    Array.from(files).forEach((file) => {
      const key = `${file.name}:${file.size}`;
      if (!existing.has(key)) {
        selectedFiles.push(file);
        existing.add(key);
      }
    });
    renderPending();
  }

  /** 上传选中的文件 */
  async function uploadFiles() {
    if (!selectedFiles.length) return;

    const form = new FormData();
    selectedFiles.forEach((file) => form.append('files', file));

    el.uploadBtn.disabled = true;
    el.uploadState.textContent = '上传中...';
    el.uploadLog.innerHTML = '';

    try {
      const data = await readJson(await request('/api/admin/documents', { method: 'POST', body: form }));
      data.results.forEach((result) => {
        const line = document.createElement('div');
        line.className = result.ok ? 'ok' : 'fail';
        line.textContent = `${result.ok ? '成功' : '跳过'}：${result.filename} - ${result.message}`;
        el.uploadLog.appendChild(line);
      });
      selectedFiles = [];
      el.fileInput.value = '';
      renderPending();
      await Promise.all([loadOverview(), loadDocuments()]);
    } catch (error) {
      const line = document.createElement('div');
      line.className = 'fail';
      line.textContent = error.message;
      el.uploadLog.appendChild(line);
    } finally {
      el.uploadState.textContent = '';
      el.uploadBtn.disabled = selectedFiles.length === 0;
    }
  }

  el.fileInput.addEventListener('change', (event) => {
    addFiles(event.target.files);
    el.fileInput.value = '';
  });

  el.dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    el.dropzone.classList.add('dragover');
  });

  el.dropzone.addEventListener('dragleave', () => el.dropzone.classList.remove('dragover'));

  el.dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    el.dropzone.classList.remove('dragover');
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  });

  el.uploadBtn.addEventListener('click', uploadFiles);

  el.clearBtn.addEventListener('click', () => {
    selectedFiles = [];
    el.uploadLog.innerHTML = '';
    renderPending();
  });

  el.refreshBtn.addEventListener('click', () => {
    loadOverview();
    loadDocuments();
  });

  renderPending();
  loadOverview();
  loadDocuments();
})();
