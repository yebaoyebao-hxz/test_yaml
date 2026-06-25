// ── 状态 ──
let activeTab = 'curl';
let imageBase64 = null;
let attachedImages = [];
let currentResult = { summary: '', yaml: '', yaml_body: '', raw: '', model: '' };
let history = [];
let rawMode = false;
let normalizeAsserts = false;

function toggleNormalize() {
  normalizeAsserts = document.getElementById('normalize-switch').checked;
}

// ── 标签切换 ──
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeTab = btn.dataset.tab;
    ['curl','text','image'].forEach(t => {
      const el = document.getElementById(t + '-group');
      if (el) el.classList.toggle('hidden', t !== activeTab);
    });
  });
});

// ── 图片上传 ──
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const previewImg = document.getElementById('preview-img');

uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault(); uploadZone.classList.remove('drag-over');
  handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', e => { if (e.target.files[0]) handleFile(e.target.files[0]); });

function handleFile(file) {
  if (!file || !file.type.startsWith('image/')) return showToast('请选择图片文件', 'err');
  const reader = new FileReader();
  reader.onload = () => {
    imageBase64 = reader.result;
    previewImg.src = reader.result;
    uploadZone.classList.add('has-image');
    addAttachedImageByData(reader.result);
  };
  reader.readAsDataURL(file);
}

// ── 通用截图附件管理 ──
const attachStrip = document.getElementById('attach-strip');
const attachAddBtn = document.getElementById('attach-add-btn');
const attachHint = document.getElementById('attach-hint');
const attachFileInput = document.getElementById('attach-file-input');

attachAddBtn.addEventListener('click', () => attachFileInput.click());
attachFileInput.addEventListener('change', e => {
  [...e.target.files].forEach(f => addAttachedImage(f));
  attachFileInput.value = '';
});

// 图片tab的上传也走统一附件
const origHandleFile = handleFile;
handleFile = function(file) {
  if (!file || !file.type.startsWith('image/')) return showToast('请选择图片文件', 'err');
  const reader = new FileReader();
  reader.onload = () => {
    imageBase64 = reader.result;
    previewImg.src = reader.result;
    uploadZone.classList.add('has-image');
    // 同时添加到通用附件
    addAttachedImageByData(reader.result);
  };
  reader.readAsDataURL(file);
};

function addAttachedImage(file) {
  const reader = new FileReader();
  reader.onload = () => addAttachedImageByData(reader.result);
  reader.readAsDataURL(file);
}

function addAttachedImageByData(dataUrl) {
  if (attachedImages.includes(dataUrl)) return;
  attachedImages.push(dataUrl);
  renderAttachedImages();
}

function removeAttachedImage(idx) {
  attachedImages.splice(idx, 1);
  // 如果删除的是当前图片tab预览，同步清理
  if (imageBase64 && !attachedImages.includes(imageBase64)) {
    imageBase64 = null;
    previewImg.src = '';
    uploadZone.classList.remove('has-image');
  }
  renderAttachedImages();
}

function renderAttachedImages() {
  attachStrip.innerHTML = '';
  attachedImages.forEach((dataUrl, idx) => {
    const thumb = document.createElement('div');
    thumb.className = 'attach-thumb';
    thumb.innerHTML = `<img src="${dataUrl}" alt="screenshot ${idx+1}"><div class="del-badge" data-idx="${idx}">&times;</div>`;
    thumb.querySelector('.del-badge').addEventListener('click', (e) => {
      e.stopPropagation();
      removeAttachedImage(idx);
    });
    thumb.addEventListener('click', () => {
      // 点击预览大图
      const w = window.open('', '_blank');
      w.document.write(`<html><body style="margin:0;display:flex;align-items:center;justify-content:center;background:#000;min-height:100vh;"><img src="${dataUrl}" style="max-width:100%;max-height:100vh;"></body></html>`);
    });
    attachStrip.appendChild(thumb);
  });
  attachStrip.appendChild(attachAddBtn);
  attachStrip.appendChild(attachHint);
  attachHint.style.display = attachedImages.length === 0 ? '' : 'none';
}

// 粘贴事件：支持 Ctrl+V 粘贴图片
document.addEventListener('paste', (e) => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const blob = item.getAsFile();
      const reader = new FileReader();
      reader.onload = () => addAttachedImageByData(reader.result);
      reader.readAsDataURL(blob);
      break; // 一次只处理一张
    }
  }
});

// 通用拖拽上传（input-card区域）
document.querySelector('.input-card').addEventListener('dragover', e => {
  e.preventDefault();
  attachStrip.style.background = '#f0f5ff';
});
document.querySelector('.input-card').addEventListener('dragleave', () => {
  attachStrip.style.background = '';
});
document.querySelector('.input-card').addEventListener('drop', e => {
  e.preventDefault();
  attachStrip.style.background = '';
  [...e.dataTransfer.files].forEach(f => {
    if (f.type.startsWith('image/')) addAttachedImage(f);
  });
});


// ── 核心调用 ──
async function doGenerate() {
  const btn = document.getElementById('submit-btn');
  const spinner = document.getElementById('spinner');
  const submitText = document.getElementById('submit-text');
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  submitText.textContent = 'AI 生成中...';

  let type, content;
  if (activeTab === 'curl') {
    type = 'curl';
    content = document.getElementById('curl-input').value.trim();
  } else if (activeTab === 'text') {
    type = 'text';
    content = document.getElementById('text-input').value.trim();
  } else {
    type = 'image';
    content = imageBase64 || '';
  }

  // 合并通用附件中的截图
  const allImages = [...attachedImages];
  if (activeTab === 'image' && imageBase64 && !allImages.includes(imageBase64)) {
    allImages.unshift(imageBase64);
  }

  if (!content && allImages.length === 0) {
    showToast('请输入内容或附加截图', 'err');
    resetBtn(); return;
  }

  // 如果只传了图片没传文本，自动切到 image 模式
  if (!content && allImages.length > 0) {
    type = 'image';
    content = allImages[0] || '';
  }

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type,
        content,
        images: allImages.length > 0 ? allImages : undefined,
        normalize_asserts: normalizeAsserts
      }),
    });
    const data = await resp.json();

    currentResult = {
      summary: data.summary || '',
      yaml: data.yaml_body || data.yaml || '',
      raw: data.yaml || '',
      model: data.model || '',
    };

    // 显示摘要
    document.getElementById('summary-box').textContent = data.summary || '(无摘要)';
    document.getElementById('model-tag').textContent = data.model || '';

    // 显示 YAML
    const yamlBox = document.getElementById('yaml-output');
    const statusBadge = document.getElementById('status-badge');

    if (data.success) {
      yamlBox.value = rawMode ? (data.yaml || '') : (data.yaml_body || '');
      yamlBox.readOnly = false;
      statusBadge.innerHTML = '<span class="badge badge-success">✓ 生成成功</span>';
    } else {
      yamlBox.value = data.error || '未知错误';
      yamlBox.readOnly = true;
      statusBadge.innerHTML = '<span class="badge badge-error">✗ 生成失败</span>';
    }

    // 写入历史
    addHistory(currentResult);
  } catch (e) {
    document.getElementById('yaml-output').value = '网络错误: ' + e.message;
    document.getElementById('status-badge').innerHTML = '<span class="badge badge-error">✗ 网络错误</span>';
  } finally {
    resetBtn();
  }
}

function resetBtn() {
  const btn = document.getElementById('submit-btn');
  const spinner = document.getElementById('spinner');
  const submitText = document.getElementById('submit-text');
  btn.disabled = false;
  spinner.style.display = 'none';
  submitText.textContent = '⚡ 生成 YAML';
}

// ── 工具函数 ──
function copyYaml() {
  const text = currentResult.yaml || currentResult.raw || '';
  copyToClipboard(text, 'YAML 已复制');
}

function copySummary() {
  copyToClipboard(currentResult.summary || '', '摘要已复制');
}

function downloadYaml() {
  downloadFile(currentResult.yaml || currentResult.raw || '', 'test_case.yaml');
}

function downloadRawYaml() {
  downloadFile(currentResult.raw || '', 'test_case_raw.txt');
}

function clearAll() {
  document.getElementById('curl-input').value = '';
  document.getElementById('text-input').value = '';
  imageBase64 = null;
  previewImg.src = '';
  uploadZone.classList.remove('has-image');
  attachedImages = [];
  renderAttachedImages();
  currentResult = { summary: '', yaml: '', yaml_body: '', raw: '', model: '' };
  const yb = document.getElementById('yaml-output');
  yb.value = '';
  yb.readOnly = true;
  document.getElementById('summary-box').textContent = '等待生成...';
  document.getElementById('status-badge').innerHTML = '';
  document.getElementById('model-tag').textContent = '';
}

function addHistory(result) {
  history.unshift({ ...result, time: new Date().toLocaleString() });
  if (history.length > 20) history.length = 20;
  document.getElementById('history-count').textContent = history.length;
}

function toggleHistory() {
  if (history.length === 0) { showToast('暂无历史记录', 'err'); return; }
  const w = window.open('', '_blank', 'width=700,height=500');
  w.document.write('<html><head><meta charset=utf-8><title>生成历史</title><style>body{font-family:monospace;padding:20px;background:#1e1e2e;color:#cdd6f4} .item{border-bottom:1px solid #333;padding:12px 0} .time{color:#585b70;font-size:12px} pre{white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto}</style></head><body>');
  w.document.write('<h2>📜 生成历史 (' + history.length + ')</h2>');
  history.forEach((h, i) => {
    w.document.write('<div class=item><div class=time>' + h.time + ' | ' + (h.model||'') + '</div>');
    w.document.write('<div><b>摘要:</b> ' + (h.summary||'') + '</div>');
    w.document.write('<pre>' + (h.raw||h.yaml||'') + '</pre></div>');
  });
  w.document.write('</body></html>');
}

function toggleRaw() {
  rawMode = !rawMode;
  const yamlBox = document.getElementById('yaml-output');
  if (rawMode) {
    yamlBox.value = currentResult.raw || '';
    showToast('已切换为原文模式');
  } else {
    yamlBox.value = currentResult.yaml || '';
    showToast('已切换为精简模式');
  }
}

function copyToClipboard(text, msg) {
  if (!text) { showToast('无内容可复制', 'err'); return; }
  navigator.clipboard.writeText(text).then(() => showToast(msg || '已复制', 'ok')).catch(() => showToast('复制失败，请手动选择', 'err'));
}

function downloadFile(content, filename) {
  if (!content) { showToast('无内容可下载', 'err'); return; }
  const blob = new Blob([content], { type: 'text/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + (type === 'ok' ? 'ok' : 'err') + ' show';
  setTimeout(() => t.classList.remove('show'), 2000);
}

// ── 快捷键 ──
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); doGenerate(); }
});

// ── 执行用例 ──
async function doExecute() {
  const yb = document.getElementById('yaml-output');
  const yamlBody = yb.value.trim();
  if (!yamlBody) {
    showToast('请先生成 YAML 用例', 'err'); return;
  }
  const btn = document.getElementById('execute-btn');
  const spinner = document.getElementById('exec-spinner');
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  setConsole('<span class="c-info">⏳ 正在保存 YAML → 生成测试文件 → 执行用例...</span>');

  // 从摘要提取文件名
  const summary = currentResult.summary || 'auto_case';
  const filename = summary.replace(/[\\/:*?"<>|]/g, '').substring(0, 30) || 'auto_yaml_case';

  try {
    const resp = await fetch('/api/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        yaml_body: yamlBody,
        filename: filename,
        input_type: activeTab,
        input_content: getInputContent(),
        summary: currentResult.summary,
        model: currentResult.model,
      }),
    });
    const data = await resp.json();

    if (data.success) {
      const reportLink = data.report_url
        ? `<br><a href="${data.report_url}" target="_blank" style="color:#1890ff;">📊 打开 Allure 报告 →</a>`
        : '';
      const stdoutText = data.stdout || '';
      const stderrText = data.stderr || '';
      let html = `<span class="c-ok">✅ 执行完成 (返回码: ${data.pytest_rc})</span>\n`;
      html += `<span class="c-dim">YAML: ${data.yaml_file} | 测试: ${data.test_file}</span>\n`;
      if (data.report_url) html += `<a href="${data.report_url}" target="_blank" style="color:#1890ff;">📊 打开 Allure 报告 →</a>\n`;
      html += `\n<span style="color:#fff;font-weight:600;">── stdout ──</span>\n`;
      html += `<span class="c-dim">${escapeHtml(stdoutText || '(空)')}</span>\n`;
      if (stderrText) {
        html += `\n<span class="c-warn">── stderr ──</span>\n`;
        html += `<span class="c-warn">${escapeHtml(stderrText)}</span>\n`;
      }
      html += reportLink;
      setConsole(html);
      showToast('用例执行完成', 'ok');
      loadDbCount();
    } else {
      let html = `<span class="c-err">❌ 执行失败</span>\n`;
      html += `<span class="c-err">${escapeHtml(data.error || '未知错误')}</span>\n`;
      if (data.stderr) html += `<span class="c-warn">${escapeHtml(data.stderr)}</span>\n`;
      setConsole(html);
      showToast('执行失败: ' + (data.error || '未知错误'), 'err');
    }
  } catch (e) {
    setConsole(`<span class="c-err">❌ 网络错误: ${escapeHtml(e.message)}</span>`);
    showToast('网络错误', 'err');
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
  }
}

async function doAiAssert() {
  const yamlBody = document.getElementById('yaml-output').value.trim();
  if (!yamlBody) {
    showToast('请先生成 YAML 用例', 'err'); return;
  }
  const btn = document.getElementById('ai-assert-btn');
  const spinner = document.getElementById('ai-spinner');
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  setConsole('<span class="c-info">⏳ AI 正在分析响应结果...</span>');

  try {
    const resp = await fetch('/api/ai_assert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml_body: yamlBody, normalize_asserts: normalizeAsserts }),
    });
    const data = await resp.json();

    if (data.results) {
      const ok = data.status === '通过';
      const icon = ok ? '✅' : '❌';
      let html = `<span class="${ok ? 'c-ok' : 'c-err'}" style="font-size:14px;font-weight:600;">${icon} AI断言结果: ${escapeHtml(data.summary || '')}</span>\n`;
      html += '<hr class="c-hr">\n';
      data.results.forEach(r => {
        const ok2 = r.status === '通过';
        const i2 = ok2 ? '✅' : r.status === '错误' ? '⚠️' : '❌';
        const cls = ok2 ? 'c-ok' : 'c-err';
        html += `<span class="${cls}">${i2} <b>${escapeHtml(r.case_id)}</b> — HTTP ${r.response_code || '-'}</span>\n`;
        html += `<span class="c-dim">  断言: ${escapeHtml(r.assert_desc || '-')}</span>\n`;
        html += `<span>  💡 ${escapeHtml(r.reason)}</span>\n`;
      });
      setConsole(html);
      showToast('AI断言完成: ' + (data.summary || ''), ok ? 'ok' : 'err');
    } else {
      setConsole(`<span class="c-err">❌ ${escapeHtml(data.error || 'AI断言失败')}</span>`);
      showToast('AI断言失败', 'err');
    }
  } catch (e) {
    setConsole(`<span class="c-err">❌ 网络错误: ${escapeHtml(e.message)}</span>`);
    showToast('网络错误', 'err');
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
  }
}

function getInputContent() {
  if (activeTab === 'curl') return document.getElementById('curl-input').value.trim();
  if (activeTab === 'text') return document.getElementById('text-input').value.trim();
  return '';
}

// ── 数据库配置 ──
async function loadDbConfig() {
  try {
    const resp = await fetch('/api/db/config');
    const data = await resp.json();
    if (data.db_path) document.getElementById('db-path').value = data.db_path;
  } catch (e) { /* ignore */ }
}

async function loadDbCount() {
  try {
    const resp = await fetch('/api/db/records?limit=1');
    const data = await resp.json();
    document.getElementById('db-count').textContent = data.count ? `(${data.count} 条记录)` : '';
  } catch (e) { /* ignore */ }
}

async function setDbPath() {
  const path = document.getElementById('db-path').value.trim();
  if (!path) { showToast('请输入数据库路径', 'err'); return; }
  try {
    const resp = await fetch('/api/db/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ db_path: path }),
    });
    const data = await resp.json();
    if (data.success) { showToast('数据库路径已更新', 'ok'); loadDbCount(); }
    else { showToast('设置失败: ' + (data.error || ''), 'err'); }
  } catch (e) { showToast('网络错误', 'err'); }
}

// ── 页签切换 ──
function switchPage(page) {
  document.querySelectorAll('.page-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.page === page);
  });
  document.getElementById('view-generate').classList.toggle('hidden', page !== 'generate');
  document.getElementById('view-records').classList.toggle('hidden', page !== 'records');
  document.getElementById('view-perf').classList.toggle('hidden', page !== 'perf');
  document.getElementById('view-danmaku').classList.toggle('hidden', page !== 'danmaku');
  document.getElementById('view-danmaku-ws').classList.toggle('hidden', page !== 'danmaku-ws');
  document.getElementById('view-protobuf').classList.toggle('hidden', page !== 'protobuf');
  if (page === 'records') loadRecords();
  if (page === 'danmaku') loadDanmakuProjects();
  if (page === 'danmaku-ws') loadDanmakuWsProjects();
  if (page === 'protobuf') protoRefreshMessages();
}

let allRecords = [];

async function loadRecords() {
  const empty = document.getElementById('records-empty');
  const table = document.getElementById('records-table');
  const tbody = document.getElementById('records-tbody');
  const countEl = document.getElementById('records-count');
  empty.style.display = ''; empty.textContent = '加载中...';
  table.style.display = 'none';
  try {
    const resp = await fetch('/api/db/records?limit=200');
    const data = await resp.json();
    if (!data.success) { empty.textContent = '查询失败'; return; }
    allRecords = data.records || [];
    countEl.textContent = '共 ' + allRecords.length + ' 条';
    filterRecords();
  } catch (e) {
    empty.textContent = '加载异常: ' + e.message;
  }
}

function filterRecords() {
  const kw = (document.getElementById('records-search')?.value || '').toLowerCase();
  const empty = document.getElementById('records-empty');
  const table = document.getElementById('records-table');
  const tbody = document.getElementById('records-tbody');
  const filtered = kw ? allRecords.filter(r =>
    (r.filename||'').toLowerCase().includes(kw) ||
    (r.summary||'').toLowerCase().includes(kw) ||
    (r.input_type||'').toLowerCase().includes(kw)
  ) : allRecords;
  if (filtered.length === 0) {
    empty.style.display = ''; empty.textContent = kw ? '无匹配记录' : '暂无记录';
    table.style.display = 'none';
    return;
  }
  empty.style.display = 'none';
  table.style.display = '';
  tbody.innerHTML = filtered.map(r => {
    const execDone = r.exec_status && r.exec_status !== 'generated';
    const execTag = execDone
      ? '<span class="tag-exec-ok">' + escapeHtml(r.exec_status) + '</span>'
      : '<span class="tag-exec-no">未执行</span>';
    const reExecDisabled = !execDone || !r.yaml_body ? 'disabled' : '';
    const reExecTitle = reExecDisabled ? 'title="尚未执行或无YAML内容"' : 'title="重新执行此用例"';
    const summary = (r.summary || '').substring(0, 50);
    return '<tr>' +
      '<td>' + r.id + '</td>' +
      '<td><div class="cell-wrap" title="' + escapeHtml(r.filename||'') + '">' + escapeHtml(r.filename||'-') + '</div></td>' +
      '<td>' + escapeHtml(r.input_type||'-') + '</td>' +
      '<td><div class="cell-summary" title="' + escapeHtml(r.summary||'') + '">' + escapeHtml(summary||'-') + '</div></td>' +
      '<td>' + execTag + '</td>' +
      '<td style="font-size:12px;color:#888;white-space:nowrap;">' + (r.created_at||'-') + '</td>' +
      '<td><label class="normalize-toggle" title="永久保留此记录"><input type="checkbox" ' + (r.keep_flag ? 'checked' : '') + ' onchange="toggleRecordKeep(' + r.id + ', this.checked)"><span class="toggle-track"></span></label></td>' +
      '<td class="cell-actions"><button ' + reExecDisabled + ' ' + reExecTitle + ' onclick="reExecute(' + r.id + ')">🔄 再次执行</button></td>' +
    '</tr>';
  }).join('');
}

async function reExecute(id) {
  const record = allRecords.find(r => r.id === id);
  if (!record || !record.yaml_body) { showToast('无 YAML 内容，无法执行', 'err'); return; }

  // 切到生成页
  switchPage('generate');

  // 填充输入区（根据原始输入类型）
  const inputType = record.input_type || 'curl';
  activeTab = ['curl', 'text', 'image'].includes(inputType) ? inputType : 'curl';
  if (activeTab === 'curl') {
    document.getElementById('curl-input').value = record.input_content || '';
  } else if (activeTab === 'text') {
    document.getElementById('text-input').value = record.input_content || '';
  }
  // 同步 generate 页的标签按钮和输入面板
  document.querySelectorAll('#view-generate .tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === activeTab);
  });
  ['curl', 'text', 'image'].forEach(t => {
    const el = document.getElementById(t + '-group');
    if (el) el.classList.toggle('hidden', t !== activeTab);
  });

  // 填 YAML
  document.getElementById('yaml-output').value = record.yaml_body;

  // 设 currentResult 供 doExecute 使用
  currentResult = {
    summary: record.summary || record.filename || 're_exec_' + id,
    yaml: record.yaml_body,
    yaml_body: record.yaml_body,
    raw: record.yaml_body,
    model: record.model || ''
  };

  // 拉起控制台执行
  doExecute();
}

async function toggleRecordKeep(id, checked) {
  try {
    const resp = await fetch('/api/db/records/' + id + '/keep', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep_flag: checked ? 1 : 0 })
    });
    const data = await resp.json();
    if (!data.success) { showToast('更新失败: ' + data.error, 'err'); return; }
    const rec = allRecords.find(r => r.id === id);
    if (rec) rec.keep_flag = checked ? 1 : 0;
    showToast(checked ? '已设为永久保留' : '已取消保留');
  } catch (e) { showToast('操作异常: ' + e.message, 'err'); }
}

// ── 性能测试 ──
let perfAbort = false;
let perfMode = 'http';  // 'http' or 'ws'
let wsSockets = [];     // 活跃的 WebSocket 连接池

function switchPerfMode(mode) {
  perfMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));

  const isWs = mode === 'ws';
  // HTTP 专属
  document.querySelectorAll('#view-perf .http-only').forEach(el => {
    el.style.display = isWs ? 'none' : '';
  });
  // WebSocket 专属
  document.querySelectorAll('#view-perf .ws-only').forEach(el => {
    el.classList.toggle('show', isWs);
  });

  // 标签文案切换
  document.getElementById('perf-body-label').textContent = isWs ? '消息体（每条连接发送的消息）' : 'Body（POST/PUT/PATCH 时使用）';
  document.getElementById('perf-concurrency-label').textContent = isWs ? '并发连接数' : '并发数';
  document.getElementById('perf-total-label').textContent = isWs ? '每连接消息数' : '总请求';
  document.getElementById('perf-run-label').textContent = isWs ? '🔌 开始长链接压测' : '🚀 开始压测';
  document.getElementById('perf-metric-l1').textContent = isWs ? '总消息' : '总请求';
  document.getElementById('perf-metric-l2').textContent = isWs ? '发送成功' : '成功';
  document.getElementById('perf-metric-l3').textContent = isWs ? '发送失败' : '失败';
  document.getElementById('perf-metric-l4').textContent = isWs ? '消息吞吐' : 'TPS';
  document.getElementById('perf-tps-unit').textContent = isWs ? ' msg/s' : ' req/s';
  document.getElementById('perf-latency-title-suffix').textContent = isWs ? '(消息往返 RTT)' : '';

  // WebSocket 连接指标面板
  document.getElementById('ws-conn-metrics').style.display = isWs ? '' : 'none';

  // URL placeholder
  document.getElementById('perf-url').placeholder = isWs
    ? 'ws://192.168.1.47:94/game/ws/xxx?token=...'
    : 'https://api.example.com/endpoint';

  // 重置结果
  resetPerfResults();
}

function resetPerfResults() {
  ['perf-total-req','perf-ok','perf-err'].forEach(id => { document.getElementById(id).textContent = '-'; });
  document.getElementById('perf-tps').innerHTML = '-<span class="unit" id="perf-tps-unit"> req/s</span>';
  ['perf-avg','perf-p50','perf-p90','perf-p95','perf-p99','perf-min','perf-max'].forEach(id => { document.getElementById(id).textContent = '- ms'; });
  ['ws-conn-total','ws-conn-ok','ws-conn-err'].forEach(id => { document.getElementById(id).textContent = '-'; });
  document.getElementById('ws-conn-avg').innerHTML = '-<span class="unit"> ms</span>';
  document.getElementById('perf-status').textContent = '';
}

function addPerfHeader() {
  const list = document.getElementById('perf-headers');
  const div = document.createElement('div');
  div.className = 'perf-header-item';
  div.innerHTML = '<input placeholder="Key"><input placeholder="Value"><button class="btn-remove" onclick="removePerfHeader(this)">×</button>';
  list.appendChild(div);
}

function removePerfHeader(btn) {
  btn.parentElement.remove();
}

function getPerfHeaders() {
  const h = {};
  document.querySelectorAll('#perf-headers .perf-header-item').forEach(row => {
    const inputs = row.querySelectorAll('input');
    if (inputs[0].value.trim()) h[inputs[0].value.trim()] = inputs[1].value;
  });
  return h;
}

async function doPerfTest() {
  if (perfMode === 'ws') {
    doWsPerfTest(); return;
  }
  const url = document.getElementById('perf-url').value.trim();
  if (!url) { showToast('请输入目标 URL', 'err'); return; }

  const method = document.getElementById('perf-method').value;
  const concurrency = parseInt(document.getElementById('perf-concurrency').value);
  const total = parseInt(document.getElementById('perf-total').value);
  const headers = getPerfHeaders();
  const bodyStr = document.getElementById('perf-body').value.trim();

  const runBtn = document.getElementById('perf-run-btn');
  const stopBtn = document.getElementById('perf-stop-btn');
  const spinner = document.getElementById('perf-spinner');
  const progDiv = document.getElementById('perf-progress');
  const progBar = document.getElementById('perf-progress-bar');

  perfAbort = false;
  runBtn.disabled = true;
  spinner.style.display = 'inline-block';
  stopBtn.style.display = 'inline-block';
  progDiv.style.display = '';
  progBar.style.width = '0%';
  document.getElementById('perf-status').textContent = '运行中...';

  // Reset results
  ['perf-total-req','perf-ok','perf-err','perf-tps','perf-avg','perf-p50','perf-p90','perf-p95','perf-p99','perf-min','perf-max'].forEach(id => {
    document.getElementById(id).textContent = id.startsWith('perf-t') ? '-' : '- ms';
  });
  // Reset TPS unit
  document.getElementById('perf-tps').innerHTML = '-<span class="unit"> req/s</span>';

  const latencies = [];
  let completed = 0, success = 0, failed = 0;
  const startTime = performance.now();

  // Build fetch options
  const fetchOpts = { method, headers };
  if (['POST','PUT','PATCH'].includes(method) && bodyStr) {
    fetchOpts.body = bodyStr;
  }

  const tasks = [];
  let idx = 0;

  async function worker() {
    while (!perfAbort) {
      const i = idx++;
      if (i >= total) break;
      const t0 = performance.now();
      try {
        const resp = await fetch(url, fetchOpts);
        const ms = Math.round(performance.now() - t0);
        latencies.push(ms);
        if (resp.ok) success++; else failed++;
      } catch (e) {
        latencies.push(Math.round(performance.now() - t0));
        failed++;
      }
      completed++;
      const pct = Math.round(completed / total * 100);
      progBar.style.width = pct + '%';
      // Update live metrics
      const elapsed = (performance.now() - startTime) / 1000;
      document.getElementById('perf-total-req').textContent = completed;
      document.getElementById('perf-ok').textContent = success;
      document.getElementById('perf-err').textContent = failed;
      document.getElementById('perf-tps').innerHTML = (elapsed > 0 ? (completed / elapsed).toFixed(1) : '0') + '<span class="unit"> req/s</span>';
    }
  }

  for (let w = 0; w < concurrency; w++) tasks.push(worker());
  await Promise.all(tasks);

  const elapsed = (performance.now() - startTime) / 1000;
  // Calculate percentiles
  if (latencies.length > 0) latencies.sort((a, b) => a - b);
  const p = (pct) => latencies.length > 0 ? latencies[Math.min(Math.floor(latencies.length * pct / 100), latencies.length - 1)] : 0;
  const avg = latencies.length > 0 ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : 0;

  document.getElementById('perf-total-req').textContent = completed;
  document.getElementById('perf-ok').textContent = success;
  document.getElementById('perf-err').textContent = failed;
  document.getElementById('perf-tps').innerHTML = (elapsed > 0 ? (completed / elapsed).toFixed(1) : '0') + '<span class="unit"> req/s</span>';
  document.getElementById('perf-avg').textContent = avg + ' ms';
  document.getElementById('perf-p50').textContent = p(50) + ' ms';
  document.getElementById('perf-p90').textContent = p(90) + ' ms';
  document.getElementById('perf-p95').textContent = p(95) + ' ms';
  document.getElementById('perf-p99').textContent = p(99) + ' ms';
  document.getElementById('perf-min').textContent = (latencies.length > 0 ? latencies[0] : '-') + ' ms';
  document.getElementById('perf-max').textContent = (latencies.length > 0 ? latencies[latencies.length - 1] : '-') + ' ms';

  document.getElementById('perf-status').textContent = perfAbort ? '已停止' : '完成';
  progBar.style.width = '100%';
  runBtn.disabled = false;
  spinner.style.display = 'none';
  stopBtn.style.display = 'none';
}

// ── WebSocket 长链接压测（纯客户端）──
async function doWsPerfTest() {
  const url = document.getElementById('perf-url').value.trim();
  if (!url) { showToast('请输入 WebSocket URL', 'err'); return; }
  if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
    showToast('WebSocket URL 必须以 ws:// 或 wss:// 开头', 'err'); return;
  }

  const concurrency = parseInt(document.getElementById('perf-concurrency').value);
  const msgsPerConn = parseInt(document.getElementById('perf-total').value);
  const timeoutSec = parseInt(document.getElementById('ws-timeout').value) || 10;
  const pingInterval = parseInt(document.getElementById('ws-ping-interval').value) || 0;
  const bodyStr = document.getElementById('perf-body').value.trim();

  const runBtn = document.getElementById('perf-run-btn');
  const stopBtn = document.getElementById('perf-stop-btn');
  const spinner = document.getElementById('perf-spinner');
  const progDiv = document.getElementById('perf-progress');
  const progBar = document.getElementById('perf-progress-bar');

  perfAbort = false;
  wsSockets = [];
  runBtn.disabled = true;
  spinner.style.display = 'inline-block';
  stopBtn.style.display = 'inline-block';
  progDiv.style.display = '';
  progBar.style.width = '0%';
  document.getElementById('perf-status').textContent = '连接中...';
  resetPerfResults();

  const msgLatencies = [];   // 消息 RTT (ms)
  const connLatencies = [];  // 连接耗时 (ms)
  let connSuccess = 0, connFailed = 0;
  let msgSent = 0, msgOk = 0, msgFailed = 0;
  const totalMessages = concurrency * msgsPerConn;
  const startTime = performance.now();

  function updateLiveMetrics() {
    const elapsed = (performance.now() - startTime) / 1000;
    document.getElementById('perf-total-req').textContent = msgSent;
    document.getElementById('perf-ok').textContent = msgOk;
    document.getElementById('perf-err').textContent = msgFailed;
    document.getElementById('perf-tps').innerHTML = (elapsed > 0 ? (msgSent / elapsed).toFixed(1) : '0') + '<span class="unit"> msg/s</span>';
    document.getElementById('ws-conn-total').textContent = concurrency;
    document.getElementById('ws-conn-ok').textContent = connSuccess;
    document.getElementById('ws-conn-err').textContent = connFailed;
    if (connLatencies.length > 0) {
      const avgConn = Math.round(connLatencies.reduce((a,b)=>a+b,0) / connLatencies.length);
      document.getElementById('ws-conn-avg').innerHTML = avgConn + '<span class="unit"> ms</span>';
    }
    if (msgSent > 0) {
      const pct = Math.round(msgSent / totalMessages * 100);
      progBar.style.width = pct + '%';
    }
  }

  // 使用 Array 控制并发连接建立
  const promises = [];
  for (let c = 0; c < concurrency; c++) {
    promises.push((async () => {
      let ws = null;
      let pingTimer = null;
      try {
        // 建立连接（带超时）
        const connT0 = performance.now();
        ws = new WebSocket(url);
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => {
            if (ws.readyState !== WebSocket.OPEN) {
              ws.close();
              reject(new Error('连接超时 (' + timeoutSec + 's)'));
            }
          }, timeoutSec * 1000);
          ws.onopen = () => {
            clearTimeout(timer);
            const connMs = Math.round(performance.now() - connT0);
            connLatencies.push(connMs);
            connSuccess++;
            resolve();
          };
          ws.onerror = () => {
            clearTimeout(timer);
            reject(new Error('连接错误'));
          };
        });

        wsSockets.push(ws);
        updateLiveMetrics();

        // 心跳
        if (pingInterval > 0 && bodyStr) {
          pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              try { ws.send(bodyStr); } catch(e) {}
            }
          }, pingInterval * 1000);
        }

        // 发送消息 & 测量 RTT
        const pendingRTT = new Map();

        ws.onmessage = (e) => {
          const now = performance.now();
          // 尝试匹配请求-响应（用序列号）
          msgOk++;
          try {
            const data = JSON.parse(e.data);
            if (data._seq !== undefined && pendingRTT.has(data._seq)) {
              const t0 = pendingRTT.get(data._seq);
              msgLatencies.push(Math.round(now - t0));
              pendingRTT.delete(data._seq);
            }
          } catch (_) {
            // 非 JSON 消息，记录收到时间
          }
          updateLiveMetrics();
        };

        ws.onclose = () => {
          if (pingTimer) clearInterval(pingTimer);
        };

        ws.onerror = () => {
          if (pingTimer) clearInterval(pingTimer);
        };

        // 逐条发送消息
        for (let m = 0; m < msgsPerConn && !perfAbort; m++) {
          if (ws.readyState !== WebSocket.OPEN) break;
          const seq = c * 10000 + m;
          let payload;
          if (bodyStr) {
            try {
              const obj = JSON.parse(bodyStr);
              obj._seq = seq;
              payload = JSON.stringify(obj);
            } catch (_) {
              payload = bodyStr;
            }
          } else {
            payload = JSON.stringify({ _seq: seq, ts: Date.now() });
          }

          const t0 = performance.now();
          pendingRTT.set(seq, t0);
          try {
            ws.send(payload);
            msgSent++;
          } catch (e) {
            msgFailed++;
            pendingRTT.delete(seq);
          }
          updateLiveMetrics();

          // 小延迟避免粘包
          if (m < msgsPerConn - 1) {
            await new Promise(r => setTimeout(r, 1));
          }
        }

        // 等待收尾消息（最多 3 秒）
        if (!perfAbort && pendingRTT.size > 0) {
          await new Promise(r => setTimeout(r, 3000));
          // 未收到回复的计入失败
          msgFailed += pendingRTT.size;
          pendingRTT.clear();
          updateLiveMetrics();
        }

      } catch (e) {
        connFailed++;
        updateLiveMetrics();
      } finally {
        if (pingTimer) clearInterval(pingTimer);
        // 不主动关闭连接，让用户观察长链接状态
      }
    })());
  }

  await Promise.all(promises);

  // 收尾统计
  const elapsed = (performance.now() - startTime) / 1000;
  if (msgLatencies.length > 0) msgLatencies.sort((a, b) => a - b);
  const p = (pct) => msgLatencies.length > 0 ? msgLatencies[Math.min(Math.floor(msgLatencies.length * pct / 100), msgLatencies.length - 1)] : 0;
  const avg = msgLatencies.length > 0 ? Math.round(msgLatencies.reduce((a, b) => a + b, 0) / msgLatencies.length) : 0;

  document.getElementById('perf-total-req').textContent = msgSent;
  document.getElementById('perf-ok').textContent = msgOk;
  document.getElementById('perf-err').textContent = msgFailed;
  document.getElementById('perf-tps').innerHTML = (elapsed > 0 ? (msgSent / elapsed).toFixed(1) : '0') + '<span class="unit"> msg/s</span>';
  document.getElementById('ws-conn-total').textContent = concurrency;
  document.getElementById('ws-conn-ok').textContent = connSuccess;
  document.getElementById('ws-conn-err').textContent = connFailed;
  if (connLatencies.length > 0) {
    document.getElementById('ws-conn-avg').innerHTML = Math.round(connLatencies.reduce((a,b)=>a+b,0) / connLatencies.length) + '<span class="unit"> ms</span>';
  }
  document.getElementById('perf-avg').textContent = avg + ' ms';
  document.getElementById('perf-p50').textContent = p(50) + ' ms';
  document.getElementById('perf-p90').textContent = p(90) + ' ms';
  document.getElementById('perf-p95').textContent = p(95) + ' ms';
  document.getElementById('perf-p99').textContent = p(99) + ' ms';
  document.getElementById('perf-min').textContent = (msgLatencies.length > 0 ? msgLatencies[0] : '-') + ' ms';
  document.getElementById('perf-max').textContent = (msgLatencies.length > 0 ? msgLatencies[msgLatencies.length - 1] : '-') + ' ms';

  document.getElementById('perf-status').textContent = perfAbort ? '已停止' : '完成';
  progBar.style.width = '100%';
  runBtn.disabled = false;
  spinner.style.display = 'none';
  stopBtn.style.display = 'none';
}

function stopPerfTest() {
  perfAbort = true;
  // 关闭所有 WebSocket 连接
  wsSockets.forEach(ws => { try { ws.close(); } catch(e) {} });
  wsSockets = [];
  document.getElementById('perf-stop-btn').disabled = true;
  document.getElementById('perf-status').textContent = '停止中...';
}

// ── 弹幕项目管理 ──
let dmAllItems = [];
let dmActiveCat = '';
let dmEditingId = null;
let dmConsoleShown = true;

function dmConsoleLog(type, msg, detail) {
  const el = document.getElementById('dm-global-console');
  el.style.display = dmConsoleShown ? '' : 'none';
  const log = document.getElementById('dm-console-log');
  if (!dmConsoleShown) return;
  const t = new Date().toLocaleTimeString();
  const colors = { ok: '#27ae60', err: '#e74c3c', info: '#3498db', warn: '#e67e22', req: '#9b59b6' };
  const icons = { ok: '✅', err: '❌', info: 'ℹ️', warn: '⚠️', req: '📤' };
  const color = colors[type] || '#ccc';
  const icon = icons[type] || '➜';
  let html = `<div style="margin-bottom:4px;"><span style="color:#666;">${t}</span> <span style="color:${color};">${icon} ${escapeHtml(msg)}</span>`;
  if (detail) html += `<div style="color:#999;margin:2px 0 0 16px;white-space:pre-wrap;word-break:break-all;">${escapeHtml(detail)}</div>`;
  html += `</div>`;
  log.innerHTML += html;
  log.scrollTop = log.scrollHeight;
  // 限制 200 条
  const lines = log.children;
  while (lines.length > 200) lines[0].remove();
}

function dmToggleConsole() {
  dmConsoleShown = !dmConsoleShown;
  document.getElementById('dm-global-console').style.display = dmConsoleShown ? '' : 'none';
}
let dmViewMode = false;

async function loadDanmakuProjects() {
  document.getElementById('dm-project-list').innerHTML = '<div class="dm-empty">加载中...</div>';
  try {
    const resp = await fetch('/api/danmaku/projects');
    const data = await resp.json();
    if (!data.success) { showToast('加载失败: ' + data.error, 'err'); return; }
    dmAllItems = data.items || [];
    renderDmCategories();
    renderDmProjects();
  } catch (e) { showToast('加载异常: ' + e.message, 'err'); }
}

function renderDmCategories() {
  const cats = [...new Set(dmAllItems.map(r => r.project_category || '默认'))];
  const container = document.getElementById('dm-cat-tabs');
  container.innerHTML = '<button class="dm-cat-btn active" onclick="filterDmCategory(\'\')">全部</button>' +
    cats.map(c => '<button class="dm-cat-btn" onclick="filterDmCategory(\'' + escapeHtml(c) + '\')">' + escapeHtml(c) + '</button>').join('');
  // 更新新增表单的分类下拉
  const sel = document.getElementById('dm-category');
  sel.innerHTML = cats.map(c => '<option>' + escapeHtml(c) + '</option>').join('') || '<option>默认</option>';
}

function filterDmCategory(cat) {
  dmActiveCat = cat;
  document.querySelectorAll('.dm-cat-btn').forEach(b => b.classList.toggle('active', b.textContent === (cat || '全部')));
  renderDmProjects();
}

function renderDmProjects() {
  const list = document.getElementById('dm-project-list');
  const filtered = dmActiveCat ? dmAllItems.filter(r => (r.project_category || '默认') === dmActiveCat) : dmAllItems;
  document.getElementById('dm-count').textContent = '共 ' + filtered.length + ' 个';
  if (filtered.length === 0) {
    list.innerHTML = '<div class="dm-empty">暂无项目</div>';
    return;
  }
  list.innerHTML = filtered.map(r => {
    const method = r.method || 'GET';
    const cat = r.project_category || '默认';
    return '<div class="dm-project-card">' +
      '<div class="dm-pname">' + escapeHtml(r.project_name) + '</div>' +
      '<div class="dm-ename">' + escapeHtml(r.endpoint_name) + '</div>' +
      '<div class="dm-url" title="' + escapeHtml(r.endpoint_url) + '">' + escapeHtml(r.endpoint_url) + '</div>' +
      '<div class="dm-meta">' +
        '<span class="dm-method dm-method-' + method + '">' + method + '</span>' +
        '<span style="font-size:10px;color:#aaa;">' + escapeHtml(cat) + '</span>' +
        '<span style="font-size:10px;color:#aaa;margin-left:auto;">' + (r.created_at || '') + '</span>' +
      '</div>' +
      '<div class="dm-actions">' +
        '<button onclick="event.stopPropagation();viewDmProject(' + r.id + ')">📋 查看</button>' +
        '<button onclick="event.stopPropagation();runDmPerfFor(' + r.id + ', \'' + escapeHtml(r.endpoint_name) + '\')">⚡ 压测</button>' +
        '<button onclick="event.stopPropagation();editDmProject(' + r.id + ')">✏ 编辑</button>' +
        '<button onclick="event.stopPropagation();deleteDmProject(' + r.id + ')" style="color:#ff4d4f;">🗑 删除</button>' +
      '</div></div>';
  }).join('');
}

function showDmForm() {
  dmEditingId = null;
  dmViewMode = false;
  document.getElementById('dm-form-title').textContent = '📝 新增弹幕项目';
  document.getElementById('dm-edit-id').value = '';
  document.getElementById('dm-project-name').value = '';
  document.getElementById('dm-endpoint-name').value = '';
  document.getElementById('dm-url').value = '';
  document.getElementById('dm-method').value = 'GET';
  document.getElementById('dm-body').value = '';
  document.getElementById('dm-new-cat').value = '';
  document.getElementById('dm-keep-flag').checked = false;
  document.getElementById('dm-headers').innerHTML = '<div class="perf-header-item"><input placeholder="Key" value="User-Agent"><input placeholder="Value" value="UnityPlayer/2023.1.13f1 (UnityWebRequest/1.0, libcurl/8.1.1-DEV)"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>' +
    '<div class="perf-header-item"><input placeholder="Key" value="X-Unity-Version"><input placeholder="Value" value="2023.1.13f1"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  document.getElementById('dm-save-btn').textContent = '💾 保存';
  document.getElementById('dm-save-btn').style.display = '';
  document.getElementById('dm-save-btn').onclick = saveDmProject;
  document.getElementById('dm-cancel-btn').style.display = 'none';
  document.getElementById('dm-perf-card').style.display = 'none';
  _setDmFormDisabled(false);
}

function editDmProject(id) {
  const item = dmAllItems.find(r => r.id === id);
  if (!item) return;
  dmEditingId = id;
  dmViewMode = false;
  _setDmFormDisabled(false);
  document.getElementById('dm-form-title').textContent = '✏ 编辑弹幕项目 (#' + id + ')';
  document.getElementById('dm-edit-id').value = id;
  document.getElementById('dm-project-name').value = item.project_name || '';
  document.getElementById('dm-endpoint-name').value = item.endpoint_name || '';
  document.getElementById('dm-url').value = item.endpoint_url || '';
  document.getElementById('dm-method').value = item.method || 'GET';
  document.getElementById('dm-body').value = item.body || '';
  document.getElementById('dm-new-cat').value = '';
  document.getElementById('dm-keep-flag').checked = !!item.keep_flag;
  // Headers
  let headers = item.headers;
  if (typeof headers === 'string') { try { headers = JSON.parse(headers); } catch(e) { headers = {}; } }
  if (headers && typeof headers === 'object' && Object.keys(headers).length > 0) {
    document.getElementById('dm-headers').innerHTML = Object.entries(headers).map(([k, v]) =>
      '<div class="perf-header-item"><input placeholder="Key" value="' + escapeHtml(k) + '"><input placeholder="Value" value="' + escapeHtml(v) + '"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>'
    ).join('');
  } else {
    document.getElementById('dm-headers').innerHTML = '<div class="perf-header-item"><input placeholder="Key"><input placeholder="Value"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  }
  document.getElementById('dm-save-btn').textContent = '💾 更新';
  document.getElementById('dm-save-btn').onclick = saveDmProject;
  document.getElementById('dm-cancel-btn').style.display = 'inline-block';
  document.getElementById('dm-perf-card').style.display = 'none';
}

function cancelDmEdit() { showDmForm(); }

function viewDmProject(id) {
  const item = dmAllItems.find(r => r.id === id);
  if (!item) return;
  dmViewMode = true;
  dmEditingId = null;

  document.getElementById('dm-form-title').textContent = '🔒 查看接口详情 (#' + id + ')';
  document.getElementById('dm-edit-id').value = '';
  document.getElementById('dm-project-name').value = item.project_name || '';
  document.getElementById('dm-endpoint-name').value = item.endpoint_name || '';
  document.getElementById('dm-url').value = item.endpoint_url || '';
  document.getElementById('dm-method').value = item.method || 'GET';
  document.getElementById('dm-body').value = item.body || '';
  document.getElementById('dm-new-cat').value = '';
  document.getElementById('dm-keep-flag').checked = !!item.keep_flag;

  let headers = item.headers;
  if (typeof headers === 'string') { try { headers = JSON.parse(headers); } catch(e) { headers = {}; } }
  if (headers && typeof headers === 'object' && Object.keys(headers).length > 0) {
    document.getElementById('dm-headers').innerHTML = Object.entries(headers).map(([k, v]) =>
      '<div class="perf-header-item"><input placeholder="Key" value="' + escapeHtml(k) + '"><input placeholder="Value" value="' + escapeHtml(v) + '"><span style="display:none;"></span></div>'
    ).join('');
  } else {
    document.getElementById('dm-headers').innerHTML = '<div class="perf-header-item"><input placeholder="Key" value="-"><input placeholder="Value" value="-"><span style="display:none;"></span></div>';
  }

  // 全部只读
  _setDmFormDisabled(true);
  document.getElementById('dm-save-btn').style.display = '';
  document.getElementById('dm-save-btn').textContent = '🔓 切换到编辑';
  document.getElementById('dm-save-btn').onclick = function() { editDmProject(id); };
  document.getElementById('dm-cancel-btn').textContent = '✕ 关闭';
  document.getElementById('dm-cancel-btn').style.display = 'inline-block';
  document.getElementById('dm-perf-card').style.display = 'none';
}

function _setDmFormDisabled(disabled) {
  ['dm-project-name','dm-endpoint-name','dm-url','dm-method','dm-body','dm-new-cat'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
  // keep-flag toggle
  const keepFlag = document.getElementById('dm-keep-flag');
  if (keepFlag) keepFlag.disabled = disabled;
  // Headers 内的 input 和按钮
  document.querySelectorAll('#dm-headers input').forEach(inp => inp.disabled = disabled);
  document.querySelectorAll('#dm-headers .btn-remove').forEach(b => { b.style.display = disabled ? 'none' : ''; });
  // + 添加 Header 按钮
  const addBtn = document.querySelector('#dm-form-title')?.closest('.card')?.querySelector('.btn-outline');
  if (addBtn) addBtn.style.display = disabled ? 'none' : '';
}

function addDmHeader() {
  const list = document.getElementById('dm-headers');
  const div = document.createElement('div');
  div.className = 'perf-header-item';
  div.innerHTML = '<input placeholder="Key"><input placeholder="Value"><button class="btn-remove" onclick="removePerfHeader(this)">×</button>';
  list.appendChild(div);
}

function getDmHeaders() {
  const h = {};
  document.querySelectorAll('#dm-headers .perf-header-item').forEach(row => {
    const inputs = row.querySelectorAll('input');
    if (inputs[0].value.trim()) h[inputs[0].value.trim()] = inputs[1].value;
  });
  return h;
}

async function saveDmProject() {
  if (dmViewMode) return;  // 只读模式不保存
  const project_name = document.getElementById('dm-project-name').value.trim();
  const endpoint_name = document.getElementById('dm-endpoint-name').value.trim();
  const endpoint_url = document.getElementById('dm-url').value.trim();
  if (!project_name) { showToast('请输入项目名称', 'err'); return; }
  if (!endpoint_name) { showToast('请输入接口名称', 'err'); return; }
  if (!endpoint_url) { showToast('请输入接口地址', 'err'); return; }

  const newCat = document.getElementById('dm-new-cat').value.trim();
  const category = newCat || document.getElementById('dm-category').value || '默认';
  const body = {
    project_name, endpoint_name, endpoint_url,
    project_category: category,
    method: document.getElementById('dm-method').value,
    headers: getDmHeaders(),
    body: document.getElementById('dm-body').value.trim(),
    keep_flag: document.getElementById('dm-keep-flag').checked ? 1 : 0
  };

  const id = dmEditingId;
  const url = id ? '/api/danmaku/projects/' + id : '/api/danmaku/projects';
  const method = id ? 'PUT' : 'POST';

  try {
    const resp = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.success) {
      showToast(id ? '已更新' : '已保存');
      showDmForm();
      await loadDanmakuProjects();
    } else {
      showToast(data.error || '保存失败', 'err');
    }
  } catch (e) { showToast('保存异常: ' + e.message, 'err'); }
}

async function deleteDmProject(id) {
  if (!confirm('确定删除该项目？')) return;
  try {
    const resp = await fetch('/api/danmaku/projects/' + id, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) { showToast('已删除'); await loadDanmakuProjects(); }
    else { showToast(data.error || '删除失败', 'err'); }
  } catch (e) { showToast('删除异常: ' + e.message, 'err'); }
}

function runDmPerfFor(id, name) {
  dmCurrentPerfId = id;
  document.getElementById('dm-perf-name').textContent = name;
  document.getElementById('dm-perf-card').style.display = '';
  // Reset
  ['dm-total','dm-ok','dm-err','dm-avg','dm-p50','dm-p90','dm-p95','dm-p99','dm-min','dm-max'].forEach(id => {
    document.getElementById(id).textContent = id.startsWith('dm-t') ? '-' : '- ms';
  });
  document.getElementById('dm-tps').innerHTML = '-<span class="unit"> req/s</span>';
  document.getElementById('dm-perf-progress').style.display = 'none';
  document.getElementById('dm-error-log-box').hidden = true;
}

let dmCurrentPerfId = null;

async function runDmPerf() {
  if (!dmCurrentPerfId) return;
  const concurrency = parseInt(document.getElementById('dm-perf-concurrency').value);
  const total = parseInt(document.getElementById('dm-perf-total').value);
  const runBtn = document.getElementById('dm-perf-run-btn');
  const progDiv = document.getElementById('dm-perf-progress');
  const progBar = document.getElementById('dm-perf-progress-bar');

  runBtn.disabled = true; runBtn.textContent = '⏳ 压测中...';
  progDiv.style.display = ''; progBar.style.width = '0%';

  // Simulate progress
  const progressTimer = setInterval(() => {
    const w = parseFloat(progBar.style.width) || 0;
    if (w < 90) progBar.style.width = (w + 3) + '%';
  }, 200);

  try {
    const resp = await fetch('/api/danmaku/perf/' + dmCurrentPerfId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concurrency, total_req: total })
    });
    clearInterval(progressTimer);
    const data = await resp.json();
    progBar.style.width = '100%';
    if (data.success) {
      document.getElementById('dm-total').textContent = data.completed;
      document.getElementById('dm-ok').textContent = data.ok;
      document.getElementById('dm-err').textContent = data.errors;
      document.getElementById('dm-tps').innerHTML = data.tps + '<span class="unit"> req/s</span>';
      const l = data.latency || {};
      document.getElementById('dm-avg').textContent = l.avg + ' ms';
      document.getElementById('dm-p50').textContent = l.p50 + ' ms';
      document.getElementById('dm-p90').textContent = l.p90 + ' ms';
      document.getElementById('dm-p95').textContent = l.p95 + ' ms';
      document.getElementById('dm-p99').textContent = l.p99 + ' ms';
      document.getElementById('dm-min').textContent = l.min + ' ms';
      document.getElementById('dm-max').textContent = l.max + ' ms';
      // 错误日志
      const elogs = data.error_logs || [];
      const logBox = document.getElementById('dm-error-log-box');
      const logDiv = document.getElementById('dm-error-log');
      if (elogs.length > 0) {
        logBox.hidden = false;
        logDiv.innerHTML = elogs.map(e => {
          const head = e.status === 0
            ? `<span style="color:#e74c3c;">#${e.idx} \u274c \u5f02\u5e38</span>`
            : `<span style="color:#e67e22;">#${e.idx} HTTP ${e.status}</span>`;
          const detail = e.error
            ? `<div style="color:#e74c3c;margin-top:2px;">${escapeHtml(e.error)}</div>`
            : (e.body ? `<div style="color:#999;margin-top:2px;">${escapeHtml(e.body)}</div>` : '');
          return `<div style="margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid #333;">${head}${detail}</div>`;
        }).join('');
      } else {
        logBox.hidden = true;
      }
    } else {
      showToast(data.error || '压测失败', 'err');
    }
  } catch (e) { clearInterval(progressTimer); showToast('压测异常: ' + e.message, 'err'); }
  runBtn.disabled = false; runBtn.textContent = '🚀 开始压测';
}

// ── 弹幕长链接压测 ──
let dmWsAllItems = [];
let dmWsActiveCat = '';
let dmWsEditingId = null;
let dmWsViewMode = false;
let dmWsCurrentPerfId = null;

async function loadDanmakuWsProjects() {
  document.getElementById('dmws-project-list').innerHTML = '<div class="dm-empty">加载中...</div>';
  try {
    const resp = await fetch('/api/danmaku/ws-projects');
    const data = await resp.json();
    if (!data.success) { showToast('加载WS项目失败: ' + data.error, 'err'); return; }
    dmWsAllItems = data.items || [];
    renderDmWsCategories();
    renderDmWsProjects();
  } catch (e) { showToast('加载WS项目异常: ' + e.message, 'err'); }
}

function renderDmWsCategories() {
  const cats = [...new Set(dmWsAllItems.map(r => r.project_category || '默认'))];
  const container = document.getElementById('dmws-cat-tabs');
  container.innerHTML = '<button class="dm-cat-btn active" onclick="filterDmWsCategory(\'\')">全部</button>' +
    cats.map(c => '<button class="dm-cat-btn" onclick="filterDmWsCategory(\'' + escapeHtml(c) + '\')">' + escapeHtml(c) + '</button>').join('');
  const sel = document.getElementById('dmws-category');
  sel.innerHTML = cats.map(c => '<option>' + escapeHtml(c) + '</option>').join('') || '<option>默认</option>';
}

function filterDmWsCategory(cat) {
  dmWsActiveCat = cat;
  document.querySelectorAll('#dmws-cat-tabs .dm-cat-btn').forEach(b => b.classList.toggle('active', b.textContent === (cat || '全部')));
  renderDmWsProjects();
}

function renderDmWsProjects() {
  const list = document.getElementById('dmws-project-list');
  const filtered = dmWsActiveCat ? dmWsAllItems.filter(r => (r.project_category || '默认') === dmWsActiveCat) : dmWsAllItems;
  document.getElementById('dmws-count').textContent = '共 ' + filtered.length + ' 个';
  if (filtered.length === 0) {
    list.innerHTML = '<div class="dm-empty">暂无WS压测项目</div>';
    return;
  }
  list.innerHTML = filtered.map(r => {
    const method = r.method || 'POST';
    const cat = r.project_category || '默认';
    return '<div class="dm-project-card">' +
      '<div class="dm-pname">' + escapeHtml(r.project_name) + '</div>' +
      '<div class="dm-ename">' + escapeHtml(r.endpoint_name) + '</div>' +
      '<div class="dm-url" title="' + escapeHtml(r.endpoint_url) + '">' + escapeHtml(r.endpoint_url) + '</div>' +
      '<div class="dm-meta">' +
        '<span class="dm-method dm-method-' + method + '">' + method + '</span>' +
        '<span style="font-size:10px;color:#aaa;">' + escapeHtml(cat) + '</span>' +
        '<span style="font-size:10px;color:#aaa;margin-left:auto;">' + (r.created_at || '') + '</span>' +
      '</div>' +
      '<div class="dm-actions">' +
        '<button onclick="event.stopPropagation();viewDmWsProject(' + r.id + ')">📋 查看</button>' +
        '<button onclick="event.stopPropagation();runDmWsPerfFor(' + r.id + ', \'' + escapeHtml(r.endpoint_name) + '\')">⚡ 压测</button>' +
        '<button onclick="event.stopPropagation();editDmWsProject(' + r.id + ')">✏ 编辑</button>' +
        '<button onclick="event.stopPropagation();deleteDmWsProject(' + r.id + ')" style="color:#ff4d4f;">🗑 删除</button>' +
      '</div></div>';
  }).join('');
}

function showDmWsForm() {
  dmWsEditingId = null;
  dmWsViewMode = false;
  document.getElementById('dmws-form-title').textContent = '📝 新增WS压测项目';
  document.getElementById('dmws-edit-id').value = '';
  document.getElementById('dmws-project-name').value = '';
  document.getElementById('dmws-endpoint-name').value = '';
  document.getElementById('dmws-url').value = '';
  document.getElementById('dmws-method').value = 'POST';
  document.getElementById('dmws-body').value = '';
  document.getElementById('dmws-new-cat').value = '';
  document.getElementById('dmws-keep-flag').checked = false;
  document.getElementById('dmws-headers').innerHTML =
    '<div class="perf-header-item"><input placeholder="Key" value="Content-Type"><input placeholder="Value" value="application/json; charset=utf-8"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  document.getElementById('dmws-save-btn').textContent = '💾 保存';
  document.getElementById('dmws-save-btn').style.display = '';
  document.getElementById('dmws-save-btn').onclick = saveDmWsProject;
  document.getElementById('dmws-cancel-btn').style.display = 'none';
  document.getElementById('dmws-perf-card').style.display = 'none';
  _setDmWsFormDisabled(false);
}

function editDmWsProject(id) {
  const item = dmWsAllItems.find(r => r.id === id);
  if (!item) return;
  dmWsEditingId = id;
  dmWsViewMode = false;
  _setDmWsFormDisabled(false);
  document.getElementById('dmws-form-title').textContent = '✏ 编辑WS项目 (#' + id + ')';
  document.getElementById('dmws-edit-id').value = id;
  document.getElementById('dmws-project-name').value = item.project_name || '';
  document.getElementById('dmws-endpoint-name').value = item.endpoint_name || '';
  document.getElementById('dmws-url').value = item.endpoint_url || '';
  document.getElementById('dmws-method').value = item.method || 'POST';
  document.getElementById('dmws-category').value = item.project_category || '默认';
  document.getElementById('dmws-body').value = item.body || '';
  document.getElementById('dmws-new-cat').value = '';
  document.getElementById('dmws-keep-flag').checked = !!item.keep_flag;
  let headers = item.headers;
  if (typeof headers === 'string') { try { headers = JSON.parse(headers); } catch(e) { headers = {}; } }
  if (headers && typeof headers === 'object' && Object.keys(headers).length > 0) {
    document.getElementById('dmws-headers').innerHTML = Object.entries(headers).map(([k, v]) =>
      '<div class="perf-header-item"><input placeholder="Key" value="' + escapeHtml(k) + '"><input placeholder="Value" value="' + escapeHtml(v) + '"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>'
    ).join('');
  } else {
    document.getElementById('dmws-headers').innerHTML = '<div class="perf-header-item"><input placeholder="Key"><input placeholder="Value"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  }
  document.getElementById('dmws-save-btn').textContent = '💾 更新';
  document.getElementById('dmws-save-btn').onclick = saveDmWsProject;
  document.getElementById('dmws-cancel-btn').style.display = 'inline-block';
  document.getElementById('dmws-perf-card').style.display = 'none';
}

function cancelDmWsEdit() { showDmWsForm(); }

function viewDmWsProject(id) {
  const item = dmWsAllItems.find(r => r.id === id);
  if (!item) return;
  dmWsViewMode = true;
  dmWsEditingId = null;
  document.getElementById('dmws-form-title').textContent = '🔒 查看WS项目详情 (#' + id + ')';
  document.getElementById('dmws-edit-id').value = '';
  document.getElementById('dmws-project-name').value = item.project_name || '';
  document.getElementById('dmws-endpoint-name').value = item.endpoint_name || '';
  document.getElementById('dmws-url').value = item.endpoint_url || '';
  document.getElementById('dmws-method').value = item.method || 'POST';
  document.getElementById('dmws-category').value = item.project_category || '默认';
  document.getElementById('dmws-body').value = item.body || '';
  document.getElementById('dmws-new-cat').value = '';
  document.getElementById('dmws-keep-flag').checked = !!item.keep_flag;
  let headers = item.headers;
  if (typeof headers === 'string') { try { headers = JSON.parse(headers); } catch(e) { headers = {}; } }
  if (headers && typeof headers === 'object' && Object.keys(headers).length > 0) {
    document.getElementById('dmws-headers').innerHTML = Object.entries(headers).map(([k, v]) =>
      '<div class="perf-header-item"><input placeholder="Key" value="' + escapeHtml(k) + '"><input placeholder="Value" value="' + escapeHtml(v) + '"><span style="display:none;"></span></div>'
    ).join('');
  } else {
    document.getElementById('dmws-headers').innerHTML = '<div class="perf-header-item"><input placeholder="Key" value="-"><input placeholder="Value" value="-"><span style="display:none;"></span></div>';
  }
  _setDmWsFormDisabled(true);
  document.getElementById('dmws-save-btn').style.display = '';
  document.getElementById('dmws-save-btn').textContent = '🔓 切换到编辑';
  document.getElementById('dmws-save-btn').onclick = function() { editDmWsProject(id); };
  document.getElementById('dmws-cancel-btn').textContent = '✕ 关闭';
  document.getElementById('dmws-cancel-btn').style.display = 'inline-block';
  document.getElementById('dmws-perf-card').style.display = 'none';
}

function _setDmWsFormDisabled(disabled) {
  ['dmws-project-name','dmws-endpoint-name','dmws-url','dmws-method','dmws-body','dmws-new-cat'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
  // keep-flag toggle
  const keepFlag = document.getElementById('dmws-keep-flag');
  if (keepFlag) keepFlag.disabled = disabled;
  document.querySelectorAll('#dmws-headers input').forEach(inp => inp.disabled = disabled);
  document.querySelectorAll('#dmws-headers .btn-remove').forEach(b => { b.style.display = disabled ? 'none' : ''; });
  const addBtn = document.querySelector('#dmws-form-title')?.closest('.card')?.querySelector('.btn-outline');
  if (addBtn) addBtn.style.display = disabled ? 'none' : '';
}

function addDmWsHeader() {
  const list = document.getElementById('dmws-headers');
  const div = document.createElement('div');
  div.className = 'perf-header-item';
  div.innerHTML = '<input placeholder="Key"><input placeholder="Value"><button class="btn-remove" onclick="removePerfHeader(this)">×</button>';
  list.appendChild(div);
}

function getDmWsHeaders() {
  const h = {};
  document.querySelectorAll('#dmws-headers .perf-header-item').forEach(row => {
    const inputs = row.querySelectorAll('input');
    if (inputs[0].value.trim()) h[inputs[0].value.trim()] = inputs[1].value;
  });
  return h;
}

async function saveDmWsProject() {
  if (dmWsViewMode) return;
  const project_name = document.getElementById('dmws-project-name').value.trim();
  const endpoint_name = document.getElementById('dmws-endpoint-name').value.trim();
  const endpoint_url = document.getElementById('dmws-url').value.trim();
  if (!project_name) { showToast('请输入项目名称', 'err'); return; }
  if (!endpoint_name) { showToast('请输入接口名称', 'err'); return; }
  if (!endpoint_url) { showToast('请输入接口地址', 'err'); return; }
  const newCat = document.getElementById('dmws-new-cat').value.trim();
  const category = newCat || document.getElementById('dmws-category').value || '默认';
  const body = {
    project_name, endpoint_name, endpoint_url,
    project_category: category,
    method: document.getElementById('dmws-method').value,
    headers: getDmWsHeaders(),
    body: document.getElementById('dmws-body').value.trim(),
    keep_flag: document.getElementById('dmws-keep-flag').checked ? 1 : 0
  };
  const id = dmWsEditingId;
  const url = id ? '/api/danmaku/ws-projects/' + id : '/api/danmaku/ws-projects';
  const method = id ? 'PUT' : 'POST';
  try {
    const resp = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.success) {
      showToast(id ? '已更新' : '已保存');
      showDmWsForm();
      await loadDanmakuWsProjects();
    } else {
      showToast(data.error || '保存失败', 'err');
    }
  } catch (e) { showToast('保存异常: ' + e.message, 'err'); }
}

async function deleteDmWsProject(id) {
  if (!confirm('确定删除该项目？')) return;
  try {
    const resp = await fetch('/api/danmaku/ws-projects/' + id, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) { showToast('已删除'); await loadDanmakuWsProjects(); }
    else { showToast(data.error || '删除失败', 'err'); }
  } catch (e) { showToast('删除异常: ' + e.message, 'err'); }
}

// ── 抖音预设 ──
function presetDmWsDy() {
  document.getElementById('dmws-url').value = 'https://zs-bjfyl-dy.danmu.hxzdm.com/game/douyin/anchor_register';
  document.getElementById('dmws-project-name').value = '抖音弹幕登录';
  document.getElementById('dmws-endpoint-name').value = 'anchor_register';
  document.getElementById('dmws-method').value = 'POST';
  document.getElementById('dmws-category').value = '抖音';
  document.getElementById('dmws-body').value = '{"roomId": 888888}';
  document.getElementById('dmws-headers').innerHTML =
    '<div class="perf-header-item"><input placeholder="Key" value="User-Agent"><input placeholder="Value" value="UnityPlayer/2021.3.42f1 (UnityWebRequest/1.0, libcurl/8.6.0-DEV)"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>' +
    '<div class="perf-header-item"><input placeholder="Key" value="Content-Type"><input placeholder="Value" value="application/json; charset=utf-8"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>' +
    '<div class="perf-header-item"><input placeholder="Key" value="X-Unity-Version"><input placeholder="Value" value="2021.3.42f1"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  showToast('已填入抖音预设配置', 'ok');
}

// ── 快手预设 ──
function presetDmWsKs() {
  document.getElementById('dmws-url').value = 'https://zs-bjfyl-dy.danmu.hxzdm.com/game/kuaishou/anchor_register';
  document.getElementById('dmws-project-name').value = '快手弹幕登录';
  document.getElementById('dmws-endpoint-name').value = 'anchor_register';
  document.getElementById('dmws-method').value = 'POST';
  document.getElementById('dmws-body').value = '{}';
  document.getElementById('dmws-headers').innerHTML =
    '<div class="perf-header-item"><input placeholder="Key" value="User-Agent"><input placeholder="Value" value="UnityPlayer/2021.3.42f1 (UnityWebRequest/1.0, libcurl/8.6.0-DEV)"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>' +
    '<div class="perf-header-item"><input placeholder="Key" value="Content-Type"><input placeholder="Value" value="application/json; charset=utf-8"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>' +
    '<div class="perf-header-item"><input placeholder="Key" value="X-Unity-Version"><input placeholder="Value" value="2021.3.42f1"><button class="btn-remove" onclick="removePerfHeader(this)">×</button></div>';
  showToast('已填入快手预设配置', 'ok');
}

function runDmWsPerfFor(id, name) {
  dmWsCurrentPerfId = id;
  document.getElementById('dmws-perf-name').textContent = name;
  document.getElementById('dmws-perf-card').style.display = '';
  // Reset
  ['dmws-total','dmws-ok','dmws-failed','dmws-avg','dmws-p50','dmws-p90','dmws-p95','dmws-p99','dmws-min','dmws-max'].forEach(id => {
    document.getElementById(id).textContent = id.startsWith('dmws-t') ? '-' : '- ms';
  });
  ['dmws-login','dmws-ws-conn','dmws-auth','dmws-room'].forEach(id => {
    document.getElementById(id).textContent = '- ms';
  });
  document.getElementById('dmws-tps').innerHTML = '-<span class="unit"> 连接/秒</span>';
  document.getElementById('dmws-perf-progress').style.display = 'none';
}

async function runDmWsPerf() {
  if (!dmWsCurrentPerfId) return;
  const concurrency = parseInt(document.getElementById('dmws-perf-concurrency').value);
  const timeout_sec = parseInt(document.getElementById('dmws-perf-timeout').value);
  const runBtn = document.getElementById('dmws-perf-run-btn');
  const progDiv = document.getElementById('dmws-perf-progress');
  const progBar = document.getElementById('dmws-perf-progress-bar');

  runBtn.disabled = true; runBtn.textContent = '⏳ 压测中...';
  progDiv.style.display = ''; progBar.style.width = '0%';

  const progressTimer = setInterval(() => {
    const w = parseFloat(progBar.style.width) || 0;
    if (w < 90) progBar.style.width = (w + 3) + '%';
  }, 300);

  try {
    const resp = await fetch('/api/danmaku/ws-perf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: dmWsCurrentPerfId, concurrency, timeout_sec })
    });
    clearInterval(progressTimer);
    const data = await resp.json();
    progBar.style.width = '100%';
    if (data.success) {
      document.getElementById('dmws-total').textContent = data.total;
      document.getElementById('dmws-ok').textContent = data.ok;
      document.getElementById('dmws-failed').textContent = data.failed;
      document.getElementById('dmws-tps').innerHTML = data.tps + '<span class="unit"> 连接/秒</span>';
      const l = data.latency || {};
      document.getElementById('dmws-avg').textContent = l.avg + ' ms';
      document.getElementById('dmws-p50').textContent = l.p50 + ' ms';
      document.getElementById('dmws-p90').textContent = l.p90 + ' ms';
      document.getElementById('dmws-p95').textContent = l.p95 + ' ms';
      document.getElementById('dmws-p99').textContent = l.p99 + ' ms';
      document.getElementById('dmws-min').textContent = l.min + ' ms';
      document.getElementById('dmws-max').textContent = l.max + ' ms';
      // 阶段延迟
      const s = data.stage_breakdown || {};
      const stageMap = { login: 'dmws-login', ws_connect: 'dmws-ws-conn', auth: 'dmws-auth', create_room: 'dmws-room' };
      for (const [key, elId] of Object.entries(stageMap)) {
        const info = s[key] || {};
        document.getElementById(elId).textContent = 'avg:' + (info.avg || 0) + ' / p50:' + (info.p50 || 0) + ' / min:' + (info.min || 0) + ' / max:' + (info.max || 0) + ' ms';
      }
    } else {
      showToast(data.error || '压测失败', 'err');
    }
  } catch (e) { clearInterval(progressTimer); showToast('压测异常: ' + e.message, 'err'); }
  runBtn.disabled = false; runBtn.textContent = '🚀 开始长链接压测';
}

// ── 工具函数 ──
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── 控制台面板 ──
let consoleVisible = false;
let consoleCollapsed = false;
let consoleContent = '';

function showConsole() {
  const panel = document.getElementById('console-panel');
  const body = document.getElementById('console-body');
  panel.style.display = 'flex';
  panel.style.maxHeight = '40vh';
  panel.style.minHeight = '120px';
  body.style.display = '';
  consoleVisible = true;
  consoleCollapsed = false;
  document.getElementById('console-toggle-btn').textContent = '▲ 收起';
}

function toggleConsoleCollapse() {
  const panel = document.getElementById('console-panel');
  const body = document.getElementById('console-body');
  const btn = document.getElementById('console-toggle-btn');
  if (consoleCollapsed) {
    panel.style.maxHeight = '40vh';
    panel.style.minHeight = '120px';
    body.style.display = '';
    btn.textContent = '▲ 收起';
    consoleCollapsed = false;
  } else {
    panel.style.maxHeight = '36px';
    panel.style.minHeight = '36px';
    body.style.display = 'none';
    btn.textContent = '▼ 展开';
    consoleCollapsed = true;
  }
}

function hideConsole() {
  // 改为收起而非关闭
  toggleConsoleCollapse();
  if (!consoleCollapsed) {
    // 如果调用hideConsole时面板是收起状态，重新显示
    showConsole();
  }
}

function clearConsole() {
  consoleContent = '';
  document.getElementById('console-body').innerHTML = '';
}

function appendConsole(html) {
  consoleContent += html;
  const body = document.getElementById('console-body');
  body.innerHTML = consoleContent;
  body.scrollTop = body.scrollHeight;
  showConsole();
}

function setConsole(html) {
  consoleContent = html;
  const body = document.getElementById('console-body');
  body.innerHTML = consoleContent;
  body.scrollTop = 0;
  showConsole();
}

function copyConsole() {
  const body = document.getElementById('console-body');
  const text = body.innerText || body.textContent;
  navigator.clipboard.writeText(text).then(() => showToast('日志已复制', 'ok')).catch(() => showToast('复制失败', 'err'));
}

// ── 控制台拖拽调整高度 ──
(function() {
  let dragging = false, startY, startH;
  const header = document.getElementById('console-header');
  const panel = document.getElementById('console-panel');
  header.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = panel.offsetHeight;
    document.body.style.userSelect = 'none';
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const newH = Math.max(80, Math.min(startH + startY - e.clientY, window.innerHeight * 0.7));
    panel.style.maxHeight = panel.style.minHeight = newH + 'px';
  });
  document.addEventListener('mouseup', () => {
    dragging = false; document.body.style.userSelect = '';
  });
})();

// ── 页面初始化 ──
loadDbConfig();
loadDbCount();

// ═══════════════════════════════════════
// Protobuf 调试器
// ═══════════════════════════════════════
let protoDataTab = 'hex';

function switchProtoDataTab(mode) {
  protoDataTab = mode;
  document.querySelectorAll('.proto-data-tab').forEach(b => b.classList.toggle('active', b.onclick.toString().includes(mode)));
}

async function protoLoad() {
  const text = document.getElementById('proto-text').value.trim();
  if (!text) return showToast('请粘贴 Proto 定义', 'err');

  try {
    const r = await fetch('/api/proto/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proto_text: text })
    });
    const data = await r.json();
    if (data.success) {
      showToast('Proto 加载成功', 'ok');
      protoRefreshMessages();
    } else {
      showToast('加载失败: ' + (data.error || ''), 'err');
      document.getElementById('proto-result').textContent = '加载失败: ' + (data.error || '');
      document.getElementById('proto-result-status').innerHTML = '<span class="badge badge-error">失败</span>';
    }
  } catch (e) {
    showToast('请求失败: ' + e.message, 'err');
  }
}

async function protoRefreshMessages() {
  try {
    const r = await fetch('/api/proto/messages');
    const data = await r.json();
    const list = document.getElementById('proto-msg-list');
    if (!data.messages?.length) {
      list.innerHTML = '<span style="color:#999;font-size:12px;">无注册 message</span>';
      return;
    }
    list.innerHTML = data.messages.map(m =>
      `<span class="proto-msg-chip" onclick="protoSelectMsg('${escapeHtml(m)}')" title="点击填入反序列化/序列化">${escapeHtml(m)}</span>`
    ).join('');
  } catch (e) {
    // ignore
  }
}

function protoSelectMsg(name) {
  document.getElementById('deser-msg-name').value = name;
  document.getElementById('ser-msg-name').value = name;
  // highlight selected chip
  document.querySelectorAll('.proto-msg-chip').forEach(c => c.classList.toggle('selected', c.textContent === name));
}

async function protoDeserialize() {
  const msgName = document.getElementById('deser-msg-name').value.trim();
  const rawData = document.getElementById('deser-data').value.trim();
  if (!msgName || !rawData) return showToast('请填写 Message 类型和数据', 'err');

  const isHex = protoDataTab === 'hex';
  const endpoint = isHex ? '/api/proto/deserialize-hex' : '/api/proto/deserialize';
  const key = isHex ? 'hex_data' : 'binary_data';

  try {
    const r = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_name: msgName, [key]: rawData })
    });
    const data = await r.json();
    const resultEl = document.getElementById('proto-result');
    const statusEl = document.getElementById('proto-result-status');
    if (data.success) {
      resultEl.textContent = JSON.stringify(data.data, null, 2);
      statusEl.innerHTML = '<span class="badge badge-success">成功</span>';
    } else {
      resultEl.textContent = '反序列化失败: ' + (data.error || '');
      statusEl.innerHTML = '<span class="badge badge-error">失败</span>';
    }
  } catch (e) {
    showToast('请求失败: ' + e.message, 'err');
  }
}

async function protoSerialize() {
  const msgName = document.getElementById('ser-msg-name').value.trim();
  const jsonStr = document.getElementById('ser-data').value.trim();
  if (!msgName || !jsonStr) return showToast('请填写 Message 类型和数据', 'err');

  let dataDict;
  try {
    dataDict = JSON.parse(jsonStr);
  } catch (e) {
    return showToast('JSON 格式无效: ' + e.message, 'err');
  }

  try {
    const r = await fetch('/api/proto/serialize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_name: msgName, data: dataDict })
    });
    const data = await r.json();
    const resultEl = document.getElementById('proto-result');
    const statusEl = document.getElementById('proto-result-status');
    if (data.success) {
      resultEl.textContent =
        `序列化成功 (${data.size} 字节)\n\nHex:\n${data.hex}\n\nBase64:\n${data.base64}`;
      statusEl.innerHTML = '<span class="badge badge-success">成功</span>';
    } else {
      resultEl.textContent = '序列化失败: ' + (data.error || '');
      statusEl.innerHTML = '<span class="badge badge-error">失败</span>';
    }
  } catch (e) {
    showToast('请求失败: ' + e.message, 'err');
  }
}

async function protoClear() {
  document.getElementById('proto-text').value = '';
  document.getElementById('deser-msg-name').value = '';
  document.getElementById('deser-data').value = '';
  document.getElementById('ser-msg-name').value = '';
  document.getElementById('ser-data').value = '';
  document.getElementById('proto-result').textContent = '等待操作...';
  document.getElementById('proto-result-status').innerHTML = '';
  document.getElementById('proto-msg-list').innerHTML = '<span style="color:#999;font-size:12px;">未加载</span>';
  try { await fetch('/api/proto/clear', { method: 'POST' }); } catch (e) {}
  showToast('已清空', 'ok');
}
// ═══════ 弹幕 AI 用例生成 ═══════
function openDmAiGenModal() {
  const modal = document.getElementById('dm-ai-gen-modal');
  const listEl = document.getElementById('dm-ai-endpoint-list');
  modal.classList.remove('hidden');
  listEl.innerHTML = '<div class="dm-empty">加载中...</div>';
  document.getElementById('dm-ai-sel-all').checked = false;
  document.getElementById('dm-ai-sel-count').textContent = '已选 0 个';
  document.getElementById('dm-ai-gen-result').hidden = true;
  document.getElementById('dm-ai-gen-progress').style.display = 'none';

  const items = dmAllItems.length > 0 ? dmAllItems : [];
  if (items.length === 0) {
    listEl.innerHTML = '<div class="dm-empty">暂无弹幕项目，请先添加</div>';
    return;
  }
  listEl.innerHTML = items.map(r => {
    const m = r.method || 'GET';
    return '<div class="endpoint-check-row">' +
      '<input type="checkbox" value="' + r.id + '" onchange="dmAiUpdateSelCount()">' +
      '<div class="endpoint-info">' +
        '<div class="ename">' + escapeHtml(r.endpoint_name) + '</div>' +
        '<div class="eurl">' + escapeHtml(r.endpoint_url) + '</div>' +
        '<div class="emeta">' + escapeHtml(r.project_name) + ' · ' + m + ' · ' + escapeHtml(r.project_category || '默认') + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
  dmAiUpdateSelCount();
}

function closeDmAiGenModal() {
  document.getElementById('dm-ai-gen-modal').classList.add('hidden');
}

function dmAiToggleAll(cb) {
  const checks = document.querySelectorAll('#dm-ai-endpoint-list input[type=checkbox]');
  checks.forEach(c => { c.checked = cb.checked; });
  dmAiUpdateSelCount();
}

function dmAiUpdateSelCount() {
  const checks = document.querySelectorAll('#dm-ai-endpoint-list input[type=checkbox]:checked');
  const n = checks.length;
  document.getElementById('dm-ai-sel-count').textContent = '已选 ' + n + ' 个';
  // 压测按钮：选了就能用；冒烟按钮：≥2 个才启用
  document.getElementById('dm-ai-stress-btn').disabled = n === 0;
  document.getElementById('dm-ai-smoke-btn').disabled = n < 2;
}

async function doDmAiGenerate(caseType) {
  const checks = document.querySelectorAll('#dm-ai-endpoint-list input[type=checkbox]:checked');
  const ids = Array.from(checks).map(c => parseInt(c.value));
  if (ids.length === 0) { showToast('请至少选择一个接口', 'err'); return; }

  const isStress = caseType === 'stress';
  const genBtn = document.getElementById(isStress ? 'dm-ai-stress-btn' : 'dm-ai-smoke-btn');
  const otherBtn = document.getElementById(isStress ? 'dm-ai-smoke-btn' : 'dm-ai-stress-btn');
  const progressDiv = document.getElementById('dm-ai-gen-progress');
  const statusSpan = document.getElementById('dm-ai-gen-status');
  const resultDiv = document.getElementById('dm-ai-gen-result');

  genBtn.disabled = true;
  if (otherBtn) otherBtn.disabled = true;
  genBtn.textContent = '⏳ 生成中...';
  progressDiv.style.display = 'flex';
  statusSpan.textContent = '正在生成，请稍候...';
  resultDiv.hidden = true;

  try {
    const resp = await fetch('/api/danmaku/ai-generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, case_type: caseType })
    });
    const data = await resp.json();
    progressDiv.style.display = 'none';

    if (!data.success) {
      resultDiv.hidden = false;
      resultDiv.innerHTML = '<div style="color:#e74c3c;">生成失败: ' + escapeHtml(data.error || '未知错误') + '</div>';
      return;
    }

    const results = data.results || [];
    const okResults = results.filter(r => r.success);
    const errCount = results.length - okResults.length;

    // ── 弹窗展示结果（折叠详情） ──
    let html = '<div style="margin-bottom:8px;font-weight:600;color:#22c55e;">' +
      '✅ 生成完成: ' + okResults.length + ' 成功' +
      (errCount > 0 ? ', <span style="color:#e74c3c;">' + errCount + ' 失败</span>' : '') +
      '</div>';
    html += '<div style="font-size:12px;color:#999;margin-bottom:8px;">' +
      '已自动跳转到「接口用例生成」页签，点击 <b>⚡ 执行用例</b> 即可运行</div>';
    results.forEach(r => {
      if (r.success) {
        html += '<details style="margin:6px 0;border:1px solid #e0e0e0;border-radius:6px;padding:8px;">' +
          '<summary style="cursor:pointer;font-weight:600;color:#333;">' + escapeHtml(r.endpoint_name || r.summary || '用例') + '</summary>' +
          '<pre style="font:11px/1.5 Consolas,monospace;background:#f8f8f8;padding:8px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;">' + escapeHtml(r.yaml_body || r.yaml || '') + '</pre>' +
        '</details>';
      } else {
        html += '<div style="color:#e74c3c;margin:4px 0;font-size:12px;">❌ ' + escapeHtml(r.endpoint_name || '') + ': ' + escapeHtml(r.error || '未知错误') + '</div>';
      }
    });
    resultDiv.hidden = false;
    resultDiv.innerHTML = html;

    // ── 切到「接口用例生成」页签，自动填充第一条成功用例 ──
    if (okResults.length > 0) {
      const first = okResults[0];
      // 填充 currentResult
      currentResult = {
        summary: first.summary || first.endpoint_name || '弹幕用例',
        yaml: first.yaml_body || first.yaml || '',
        yaml_body: first.yaml_body || first.yaml || '',
        raw: first.yaml_body || first.yaml || '',
        model: data.model || ''
      };
      // 写入 HTML 区域
      document.getElementById('yaml-output').value = currentResult.yaml_body;
      document.getElementById('summary-box').textContent = currentResult.summary;
      document.getElementById('model-tag').textContent = currentResult.model || '';
      document.getElementById('status-badge').innerHTML =
        '<span class="badge badge-success">✓ AI 批生成</span>';

      // 模拟文本输入（让 doExecute 的 getInputContent 有值）
      activeTab = 'text';
      document.getElementById('text-input').value =
        first.endpoint_name ? ('弹幕接口: ' + first.endpoint_name) : '';
      // 同步标签按钮
      document.querySelectorAll('#view-generate .tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === 'text');
      });
      ['curl', 'text', 'image'].forEach(t => {
        const el = document.getElementById(t + '-group');
        if (el) el.classList.toggle('hidden', t !== 'text');
      });

      addHistory(currentResult);
      // 关闭弹窗，跳转到生成页
      closeDmAiGenModal();
      switchPage('generate');
    }

    showToast('生成完成: ' + okResults.length + '/' + results.length + ' 成功，已跳转到用例生成页');
  } catch (e) {
    progressDiv.style.display = 'none';
    resultDiv.hidden = false;
    resultDiv.innerHTML = '<div style="color:#e74c3c;">网络错误: ' + escapeHtml(e.message) + '</div>';
    showToast('网络错误', 'err');
  } finally {
    genBtn.disabled = false;
    genBtn.textContent = isStress ? '⚡ 压测用例' : '🧪 冒烟用例';
    // 恢复另一个按钮状态（冒烟需 ≥2 个才启用）
    dmAiUpdateSelCount();
  }
}