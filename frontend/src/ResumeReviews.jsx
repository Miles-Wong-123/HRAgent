import React, { useEffect, useRef, useState } from 'react';

import ResumeReviewDetail from './ResumeReviewDetail.jsx';

const PAGE_SIZE = 10;
const STATUS = { pending: '待评审', processing: '评审中', completed: '已完成', failed: '失败' };

export default function ResumeReviews({ position, call, onBack, onOpenJD }) {
  const [selection, setSelection] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [selectedTask, setSelectedTask] = useState(null);
  const [rows, setRows] = useState([]);
  const [page, setPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const inFlight = useRef(false);
  const picker = useRef(null);

  useEffect(() => {
    if (selectedTask) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ position_id: position.id, limit: PAGE_SIZE + 1, offset: page * PAGE_SIZE });
    setLoading(true);
    setListError('');
    call(`/resume-reviews?${params}`, { signal: controller.signal })
      .then(items => { if (!controller.signal.aborted) setRows(items); })
      .catch(err => { if (!controller.signal.aborted) setListError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [call, position.id, page, refresh, selectedTask]);

  function selectFile(event) {
    const file = event.target.files[0];
    setSelection(file ? { file, key: crypto.randomUUID() } : null);
    setUploadError('');
  }

  async function upload(event) {
    event.preventDefault();
    if (!selection || inFlight.current) return;
    inFlight.current = true;
    setUploading(true);
    setUploadError('');
    try {
      const body = new FormData();
      body.append('position_id', position.id);
      body.append('request_key', selection.key);
      body.append('file', selection.file);
      const task = await call('/resume-reviews', { method: 'POST', body });
      setSelectedTask(task);
      setSelection(null);
      if (picker.current) picker.current.value = '';
      setPage(0);
      setRefresh(value => value + 1);
    } catch (err) {
      setUploadError(err.message);
    } finally {
      inFlight.current = false;
      setUploading(false);
    }
  }

  if (selectedTask) {
    return <ResumeReviewDetail key={selectedTask.id} task={selectedTask} position={position} call={call} onBack={() => setSelectedTask(null)} />;
  }

  return <div className="jd-page">
    <button type="button" className="text-button" onClick={onBack}>← 返回岗位管理</button>
    <header className="page-heading"><div>
      <h1>{position.title}</h1><p className="muted">{position.department_name} · 简历审查</p>
    </div><button className="button" onClick={onOpenJD}>查看岗位 JD</button></header>
    <form className="jd-card" onSubmit={upload}>
      <h2>上传简历</h2>
      <label>选择可复制文字的 PDF<input ref={picker} required type="file" accept=".pdf,application/pdf" onChange={selectFile} disabled={uploading} /></label>
      <p>每份简历创建一个待审查任务，并绑定提交时该岗位已发布的 JD 版本。</p>
      {uploadError && <div className="alert error" role="alert">{uploadError}</div>}
      <div className="jd-actions"><button type="submit" className="button primary" disabled={!selection || uploading}>{uploading ? '上传中…' : '上传并创建任务'}</button></div>
    </form>
    <section className="positions-card resume-history">
      <div className="card-heading"><h2>审查任务</h2><button className="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>刷新</button></div>
      {listError ? <p className="alert error" role="alert">{listError}</p>
        : loading ? <p className="empty-state" role="status">正在加载任务…</p>
        : rows.length === 0 ? <p className="empty-state">暂无简历审查任务。</p>
        : <div className="table-wrap"><table><thead><tr>
          <th>简历文件</th><th>审查依据</th><th>审查任务</th><th>任务编号</th><th>提交时间</th><th>操作</th>
        </tr></thead><tbody>{rows.slice(0, PAGE_SIZE).map(task => <tr key={task.id}>
          <td><strong className="position-title">{task.original_filename}</strong><small>{task.page_count} 页</small></td>
          <td>JD v{task.jd_version}</td><td><span className="jd-badge">{STATUS[task.status]}</span></td>
          <td><code>{task.id}</code></td><td>{new Date(task.created_at).toLocaleString('zh-CN')}</td>
          <td><button className="text-button" onClick={() => setSelectedTask(task)}>查看任务</button></td>
        </tr>)}</tbody></table></div>}
      {(page > 0 || rows.length > PAGE_SIZE) && <div className="table-footer"><span>第 {page + 1} 页</span><div className="pagination">
        <button className="button" disabled={loading || page === 0} onClick={() => setPage(value => value - 1)}>上一页</button>
        <button className="button" disabled={loading || !!listError || rows.length <= PAGE_SIZE} onClick={() => setPage(value => value + 1)}>下一页</button>
      </div></div>}
    </section>
  </div>;
}
