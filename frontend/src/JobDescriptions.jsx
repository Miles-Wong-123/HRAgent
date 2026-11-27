import React, { useCallback, useEffect, useState } from 'react';
import JDReview from './JDReview.jsx';
import './jd.css';

const base = '/job-descriptions';
const PAGE_SIZE = 12;
const active = ['extracting', 'analyzing', 'validating'];
const labels = {
  pending: '待解析', extracting: '读取原文中', analyzing: '模型解析中', validating: '校验引用中',
  failed: '解析失败', needs_ocr: '需要文字识别', awaiting_review: '待审核', published: '已发布', archived: '已归档',
};
function status(jd) {
  return jd.review_status && jd.review_status !== 'not_ready' ? jd.review_status : jd.parse_status;
}
function Badge({ jd }) {
  return <span className={'jd-badge jd-' + status(jd)}>{labels[status(jd)]}</span>;
}

function NewVersion({ position, call, onCreated, onCancel }) {
  const [mode, setMode] = useState('text');
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    if (mode === 'text' && !text.trim()) { setError('请填写岗位说明原文。'); return; }
    if (mode === 'file' && !file) { setError('请选择文件。'); return; }
    setError(''); setBusy(true);
    let body = { position_id: position.id, text: text.trim() };
    if (mode === 'file') {
      body = new FormData();
      body.append('position_id', position.id);
      body.append('file', file);
    }
    try {
      const jd = await call(base + '/' + mode, { method: 'POST', body });
      // 先保留已创建的版本；启动失败时用户可对同一版本重试。
      let message = '';
      try { await call(base + '/' + jd.id + '/parse', { method: 'POST' }); }
      catch (err) { message = '版本已保存，启动解析时遇到问题：' + err.message; }
      onCreated(jd, message);
    } catch (err) { setError(err.message); setBusy(false); }
  }
  return <form className="jd-card jd-form" onSubmit={submit}>
    <h2>新增 JD 版本</h2>
    <fieldset disabled={busy}>
      <div className="jd-switch">{[['text','粘贴文本'], ['file','上传文件']].map(([key, name]) =>
        <button key={key} type="button" aria-pressed={mode === key} onClick={() => { setMode(key); setError(''); }}>{name}</button>)}</div>
      {mode === 'text' ? <label>岗位说明原文<textarea autoFocus required maxLength={60000} rows={10} value={text} onChange={e => setText(e.target.value)} placeholder="粘贴岗位职责、任职要求和优先条件…" /></label>
        : <label>选择 JD 文件<input type="file" required accept=".pdf,.docx,.txt,.md" onChange={e => setFile(e.target.files[0] ?? null)} /><small>支持 PDF、DOCX、TXT 和 Markdown。</small></label>}
    </fieldset>
    {error && <p className="alert error" role="alert">{error}</p>}
    <div className="jd-actions"><button type="button" className="button" disabled={busy} onClick={onCancel}>取消</button><button className="button primary" disabled={busy}>{busy ? '提交中…' : '提交并解析'}</button></div>
  </form>;
}

function VersionDetail({ id, call, refreshList, initialNotice }) {
  const [jd, setJd] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [cycle, setCycle] = useState(0);
  const [actionNotice, setActionNotice] = useState(initialNotice);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const result = await call(base + '/' + id, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJd(result); setError('');
        if (active.includes(result.parse_status)) timer = setTimeout(load, 2000);
        else refreshList();
      } catch (err) { if (!controller.signal.aborted) setError(err.message); }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [call, id, cycle, refreshList]);

  async function parse() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await call(base + '/' + id + '/parse', { method: 'POST' });
      setActionNotice('');
      setJd(prev => ({ ...prev, parse_status: 'extracting', error: null, validation_issues: [] }));
      refreshList();
      setCycle(value => value + 1);
    } catch (err) {
      setActionNotice(err.message);
      setCycle(value => value + 1);
    } finally { setBusy(false); }
  }
  return <section className="jd-card">
    {actionNotice && <p className="alert" role="status">{actionNotice}</p>}
    {error && <div className="alert error" role="alert">{error} <button className="text-button" onClick={() => setCycle(v => v + 1)}>刷新详情</button></div>}
    {!jd ? !error && <p role="status">正在读取 JD…</p> : <>
      <header className="jd-detail-heading"><div><h2>JD 版本 {jd.version}</h2><small>{jd.original_filename || '粘贴文本'} · {new Date(jd.created_at).toLocaleString('zh-CN')}</small></div><Badge jd={jd} /></header>
      {!!jd.warnings?.length && <ul className="alert">{jd.warnings.map((w,i) => <li key={i}>{w}</li>)}</ul>}
      <details className="jd-source"><summary>查看提交的原文</summary><pre>{jd.raw_text || jd.source_text || '文件正文将在读取后显示。'}</pre></details>
      {active.includes(jd.parse_status) && <p role="status">解析进行中，完成后会自动显示结果。</p>}
      {jd.error && <div className="alert error" role="alert">{jd.error.message}{jd.validation_issues?.map((issue,i) => <p key={i}>{issue.message}（{issue.field_path}）</p>)}</div>}
      {jd.parse_status === 'needs_ocr' && <p>请将图片内容转换为文字后提交新版本。</p>}
      {['pending','failed'].includes(jd.parse_status) && <button className="button primary" disabled={busy} onClick={parse}>{jd.parse_status === 'failed' ? '重新解析' : '开始解析'}</button>}
      {jd.parse_status === 'completed' && <JDReview key={id + jd.publication_status} jd={jd} call={call} onPublished={result => { setJd(result); setError(''); refreshList(); }} onConflict={() => setCycle(v => v + 1)} />}
    </>}
  </section>;
}

export default function JobDescriptions({ position, call, onBack }) {
  const [versions, setVersions] = useState([]);
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const refreshList = useCallback(() => setRevision(r => r + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    call(base + '?' + new URLSearchParams({ position_id: position.id, limit: PAGE_SIZE + 1, offset: page * PAGE_SIZE }), { signal: controller.signal })
      .then(rows => {
        if (controller.signal.aborted) return;
        setVersions(rows.slice(0,PAGE_SIZE)); setMore(rows.length > PAGE_SIZE);
        setSelected(prev => prev || rows[0]?.id || '');
      }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [position.id, call, page, revision]);
  function changePage(delta) { setPage(current => current + delta); setVersions([]); setSelected(''); setNotice(''); setCreating(false); }
  return <div className="jd-page">
    <button className="text-button" onClick={onBack}>← 返回岗位管理</button>
    <div className="page-heading"><div><h1>{position.title}</h1><p className="muted">{position.department_name} · 岗位 JD</p></div>
      <button className="button primary" disabled={creating || position.department_is_active === false} onClick={() => setCreating(true)}>新增 JD 版本</button></div>
    <div className="jd-layout">
      <aside className="jd-card jd-history"><h2>版本记录</h2>
        {error && <p className="alert error" role="alert">{error} <button className="text-button" onClick={refreshList}>重试</button></p>}
        {!versions.length && !error && <p>{loading ? '读取版本中…' : '暂无 JD 版本'}</p>}
        {versions.map(jd => <button type="button" key={jd.id} className="jd-version" aria-current={!creating && selected === jd.id ? 'true' : undefined}
          onClick={() => { setSelected(jd.id); setCreating(false); setNotice(''); }}>
          <strong>版本 {jd.version}</strong><Badge jd={jd} /><small>{new Date(jd.created_at).toLocaleDateString('zh-CN')}</small>
        </button>)}
        {(page > 0 || more) && <div className="jd-pager"><button className="text-button" disabled={page === 0 || loading} onClick={() => changePage(-1)}>上一页</button><button className="text-button" disabled={!more || loading} onClick={() => changePage(1)}>下一页</button></div>}
      </aside>
      {creating ? <NewVersion position={position} call={call} onCancel={() => setCreating(false)} onCreated={(jd,message) => { setSelected(jd.id); setNotice(message); setCreating(false); setPage(0); refreshList(); }} />
        : selected ? <VersionDetail key={selected} id={selected} call={call} refreshList={refreshList} initialNotice={notice} />
        : <section className="jd-card"><h2>岗位说明</h2><p>{position.department_is_active === false ? '部门已停用。' : '提交该岗位的第一份 JD，开始解析任职条件。'}</p></section>}
    </div>
  </div>;
}
