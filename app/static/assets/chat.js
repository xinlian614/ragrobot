(() => {
  const chatWindow = document.getElementById('chatWindow');
  const welcome = document.getElementById('welcome');
  const input = document.getElementById('questionInput');
  const sendBtn = document.getElementById('sendBtn');

  /** 对话历史，仅保留最近的问答用于多轮上下文 */
  const history = [];
  let pending = false;

  /** 滚动到对话底部 */
  function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  /** 自动调整输入框高度 */
  function autoResize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  }

  /**
   * 创建一条消息 DOM
   * @param {'user'|'bot'} role 消息角色
   * @param {string} text 消息内容
   * @param {boolean} isError 是否为错误提示
   * @returns {{root: HTMLElement, bubble: HTMLElement}}
   */
  function createMessage(role, text, isError = false) {
    const root = document.createElement('div');
    root.className = `message ${role}${isError ? ' error' : ''}`;

    const avatar = document.createElement('div');
    avatar.className = `avatar ${role}`;
    avatar.textContent = role === 'user' ? '我' : 'AI';

    const wrap = document.createElement('div');
    wrap.className = 'bubble-wrap';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;

    wrap.appendChild(bubble);
    root.appendChild(avatar);
    root.appendChild(wrap);
    chatWindow.appendChild(root);
    scrollToBottom();
    return { root, bubble, wrap };
  }

  /**
   * 在气泡内创建等待回复的打字动画
   * @param {HTMLElement} bubble 消息气泡
   */
  function createTyping(bubble) {
    const typing = document.createElement('div');
    typing.className = 'typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    bubble.appendChild(typing);
    scrollToBottom();
    return typing;
  }

  /**
   * 渲染回答引用的知识库片段
   * @param {HTMLElement} wrap 消息容器
   * @param {Array} sources 引用列表
   */
  function renderSources(wrap, sources) {
    if (!sources || !sources.length) return;

    const box = document.createElement('div');
    box.className = 'sources';

    const head = document.createElement('div');
    head.className = 'sources-head';
    const headText = document.createElement('span');
    headText.textContent = `引用来源 ${sources.length} 条`;
    const toggle = document.createElement('span');
    toggle.className = 'sources-toggle';
    toggle.textContent = '展开';
    head.appendChild(headText);
    head.appendChild(toggle);

    const list = document.createElement('div');
    list.className = 'source-list';
    list.hidden = true;

    sources.forEach((source, index) => {
      const item = document.createElement('div');
      item.className = 'source-item';

      const meta = document.createElement('div');
      meta.className = 'source-meta';
      const name = document.createElement('span');
      name.className = 'source-name';
      name.textContent = `[${index + 1}] ${source.filename}`;
      const score = document.createElement('span');
      score.textContent = `相关度 ${(source.score * 100).toFixed(1)}%`;
      meta.appendChild(name);
      meta.appendChild(score);

      const text = document.createElement('div');
      text.className = 'source-text';
      text.textContent = source.content;

      item.appendChild(meta);
      item.appendChild(text);
      item.addEventListener('click', () => item.classList.toggle('open'));
      list.appendChild(item);
    });

    head.addEventListener('click', () => {
      list.hidden = !list.hidden;
      toggle.textContent = list.hidden ? '展开' : '收起';
    });

    box.appendChild(head);
    box.appendChild(list);
    wrap.appendChild(box);
  }

  /** 切换发送按钮可用状态 */
  function setPending(value) {
    pending = value;
    sendBtn.disabled = value;
    sendBtn.textContent = value ? '思考中' : '发送';
  }

  /**
   * 发送问题并渲染回答
   * @param {string} question 用户问题
   */
  async function ask(question) {
    const text = question.trim();
    if (!text || pending) return;

    if (welcome) welcome.remove();
    createMessage('user', text);
    input.value = '';
    autoResize();
    setPending(true);

    const { root, wrap, bubble } = createMessage('bot', '');
    const typing = createTyping(bubble);

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, history: history.slice(-6) }),
      });
      const data = await resp.json().catch(() => ({}));
      typing.remove();

      if (!resp.ok) {
        throw new Error(data.detail || `请求失败（${resp.status}）`);
      }

      bubble.textContent = data.answer;
      renderSources(wrap, data.sources);

      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: data.answer });
    } catch (error) {
      typing.remove();
      bubble.textContent = `请求出错：${error.message}`;
      root.classList.add('error');
    } finally {
      setPending(false);
      scrollToBottom();
      input.focus();
    }
  }

  sendBtn.addEventListener('click', () => ask(input.value));

  input.addEventListener('input', autoResize);

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(input.value);
    }
  });

  document.querySelectorAll('.suggestion').forEach((button) => {
    button.addEventListener('click', () => ask(button.textContent));
  });

  autoResize();
  input.focus();
})();
