/* ============================================================
   Knowledge Page — 文档上传 + 列表 + 删除
   ============================================================ */

const KnowledgePage = (() => {

  function render() {
    const container = document.getElementById('page-container');
    document.getElementById('navbar').classList.remove('hidden');

    container.innerHTML = `
      <div class="knowledge-page">
        <h1>📚 知识库管理</h1>

        <!-- Upload Zone -->
        <div id="upload-zone" class="upload-zone">
          <div class="upload-icon">📁</div>
          <p><strong>点击选择文件</strong> 或将 TXT 文件拖拽到此处</p>
          <p class="hint">仅支持 .txt 格式（UTF-8 编码）</p>
          <input type="file" id="file-input" accept=".txt" hidden>
          <div id="upload-status" class="hidden mt-sm"></div>
        </div>

        <!-- Document Table -->
        <div class="card" style="padding:0;overflow:hidden">
          <table class="doc-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>MD5</th>
                <th>分块数</th>
                <th>上传时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody id="doc-tbody">
              <tr class="doc-table-empty"><td colspan="5">加载中...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    // 事件绑定
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    uploadZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) handleUpload(e.target.files[0]);
      fileInput.value = ''; // 重置，允许重复选同一文件
    });

    // 拖拽上传
    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.classList.add('dragover');
    });
    uploadZone.addEventListener('dragleave', () => {
      uploadZone.classList.remove('dragover');
    });
    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file) handleUpload(file);
    });

    // 加载文档列表
    loadDocuments();
  }

  async function loadDocuments() {
    const tbody = document.getElementById('doc-tbody');
    if (!tbody) return;
    try {
      const data = await API.getDocuments();
      const docs = data.documents || [];
      if (!docs.length) {
        tbody.innerHTML = `<tr class="doc-table-empty"><td colspan="5">暂无文档，上传一个 TXT 文件开始吧 📄</td></tr>`;
        return;
      }
      tbody.innerHTML = docs.map(d => `
        <tr>
          <td><strong>${escapeHtml(d.filename)}</strong></td>
          <td class="text-secondary"><code style="font-size:0.75rem">${escapeHtml(d.md5_hash?.substring(0, 16) || '-')}...</code></td>
          <td>${d.chunk_count}</td>
          <td class="text-secondary">${formatDate(d.created_at)}</td>
          <td><button class="btn btn-sm btn-outline btn-del-doc" data-id="${d.id}" data-name="${escapeAttr(d.filename)}">🗑 删除</button></td>
        </tr>
      `).join('');

      // 删除按钮事件
      tbody.querySelectorAll('.btn-del-doc').forEach(btn => {
        btn.addEventListener('click', async () => {
          const docId = btn.dataset.id;
          const docName = btn.dataset.name;
          if (!confirm(`确定删除文档「${docName}」？删除后对应的知识库内容也将移除。`)) return;
          try {
            await API.deleteDocument(docId);
            Toast.success(`文档「${docName}」已删除`);
            loadDocuments();
          } catch (err) {
            Toast.error(err.message);
          }
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr class="doc-table-empty"><td colspan="5">加载失败: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function handleUpload(file) {
    // 校验
    if (!file.name.toLowerCase().endsWith('.txt')) {
      Toast.error('仅支持 TXT 格式文件');
      return;
    }

    const statusEl = document.getElementById('upload-status');
    statusEl.classList.remove('hidden');
    statusEl.innerHTML = `<span style="color:var(--color-primary)">⏳ 正在上传「${escapeHtml(file.name)}」...</span>`;

    try {
      const result = await API.uploadDocument(file);
      statusEl.innerHTML = `<span style="color:var(--color-success)">✅ ${result.message}（共 ${result.chunk_count} 个语义块）</span>`;
      Toast.success(`上传成功，共 ${result.chunk_count} 个语义块`);
      loadDocuments();
    } catch (err) {
      statusEl.innerHTML = `<span style="color:var(--color-danger)">❌ ${escapeHtml(err.message)}</span>`;
      Toast.error(err.message);
    }

    // 3 秒后自动隐藏状态
    setTimeout(() => { statusEl.classList.add('hidden'); }, 5000);
  }

  /* ---- Helpers ---- */
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function formatDate(isoString) {
    try {
      const d = new Date(isoString);
      return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch { return '-'; }
  }

  return { render };
})();
