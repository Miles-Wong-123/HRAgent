import React, { useEffect, useRef, useState } from 'react';

function DepartmentForm({ call, onClose, onCreated, Icon }) {
  const dialog = useRef(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { dialog.current.showModal(); }, []);

  const submit = async event => {
    event.preventDefault();
    if (saving) return;
    if (!name.trim()) { setError('请输入部门名称。'); return; }
    setSaving(true); setError('');
    try {
      await call('/departments', {
        method: 'POST',
        body: { name: name.trim(), description: description.trim() || null },
      });
      onCreated();
    } catch (err) { setError(err.message); setSaving(false); }
  };

  return <dialog ref={dialog} className="editor-dialog" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="dialog-heading"><div><p className="eyebrow">DEPARTMENT DETAILS</p><h2>新增部门</h2></div><button type="button" className="icon-button" disabled={saving} onClick={onClose} aria-label="关闭"><Icon name="close" /></button></div>
    <p className="muted editor-intro">新部门将归属于当前公司，保存后可在新增岗位时选择。</p>
    <form onSubmit={submit}>
      <fieldset disabled={saving}><div className="form-grid">
        <label className="full">部门名称<input autoFocus required maxLength={100} value={name} onChange={event => setName(event.target.value)} placeholder="例如：研发部" /></label>
        <label className="full">部门说明 <span className="optional">选填</span><textarea rows={4} maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} placeholder="填写部门的主要职责" /></label>
      </div></fieldset>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="dialog-footer"><button className="button" type="button" disabled={saving} onClick={onClose}>取消</button><button className="button primary" type="submit" disabled={saving}>{saving ? '保存中…' : '创建部门'}</button></div>
    </form>
  </dialog>;
}

export default function DepartmentManagement({ departments, loading, error, call, onRefresh, onCreated, Icon }) {
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 10;
  const filtered = departments.filter(department =>
    department.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
    && (status === '' || String(department.is_active) === status));
  const lastPage = Math.max(0, Math.ceil(filtered.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const rows = filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize);

  return <>
    <section className="positions-card">
      <div className="card-heading"><div><h2>公司部门 <span className="count">{error ? '—' : departments.length}</span></h2><p>仅管理员可见，管理本公司的部门信息。</p></div><div className="department-actions"><button className="button refresh-button" disabled={loading} onClick={onRefresh}><Icon name="refresh" size={15} />刷新</button><button className="button primary" disabled={loading} onClick={() => setCreating(true)}><Icon name="plus" size={17} />新增部门</button></div></div>
      <div className="toolbar"><div className="search-box"><Icon name="search" size={17} /><input aria-label="搜索部门名称" value={search} maxLength={100} onChange={event => { setSearch(event.target.value); setPage(0); }} placeholder="搜索部门名称…" /></div><select aria-label="按部门状态筛选" value={status} onChange={event => { setStatus(event.target.value); setPage(0); }}><option value="">全部状态</option><option value="true">启用中</option><option value="false">已停用</option></select></div>
      {loading ? <div className="empty-state" role="status"><span className="spinner" /><p>正在加载部门…</p></div> : error ? <div className="empty-state" role="alert"><h3>暂时无法加载部门</h3><p>{error}</p><button className="button" onClick={onRefresh}>重新加载</button></div> : rows.length ? <div className="table-wrap"><table><thead><tr><th>部门名称</th><th>部门说明</th><th>状态</th><th>更新时间</th></tr></thead><tbody>{rows.map(department => <tr key={department.id}><td><strong className="position-title">{department.name}</strong></td><td className="department-description">{department.description || '—'}</td><td><span className={`status-badge ${department.is_active ? 'open' : 'closed'}`}><span />{department.is_active ? '启用中' : '已停用'}</span></td><td className="date-cell">{new Date(department.updated_at).toLocaleDateString('zh-CN')}</td></tr>)}</tbody></table></div> : <div className="empty-state"><span className="empty-icon"><Icon name="building" size={32} /></span><h3>{search || status ? '没有符合条件的部门' : '添加公司的第一个部门'}</h3><p>{search || status ? '试试调整搜索词或筛选条件。' : '建立部门后，就可以为团队添加招聘岗位。'}</p><button className="button primary" onClick={() => setCreating(true)}><Icon name="plus" size={16} />新增部门</button></div>}
      <div className="table-footer"><span>{error ? '加载失败' : `共 ${filtered.length} 个符合条件的部门`}</span><div className="pagination"><button className="icon-button previous" aria-label="部门上一页" disabled={loading || currentPage === 0} onClick={() => setPage(currentPage - 1)}><Icon name="chevron" size={15} /></button><span>第 {currentPage + 1} / {lastPage + 1} 页</span><button className="icon-button" aria-label="部门下一页" disabled={loading || currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}><Icon name="chevron" size={15} /></button></div></div>
    </section>
    {creating && <DepartmentForm call={call} Icon={Icon} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); setSearch(''); setStatus(''); setPage(0); onCreated(); }} />}
  </>;
}
