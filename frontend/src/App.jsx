import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import DepartmentManagement from './DepartmentManagement.jsx';

const SESSION_KEY = 'hragent.session';
const STATUS = { open: '招聘中', paused: '已暂停', closed: '已关闭' };
const PAGE_SIZE = 10;
const INITIAL_FORM = { title: '', department_id: '', location: '', description: '', target_headcount: 1, hired_headcount: 0, recruitment_status: 'open' };
const time = value => new Date(value).toLocaleDateString('zh-CN');

function Icon({ name, size = 20, ...props }) {
  const paths = {
    briefcase: <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a22 22 0 0 0 18 0M12 11v3" /></>,
    building: <><path d="M4 21V5l8-3v19M12 8h8v13M2 21h20M7 7h2M7 11h2M7 15h2M15 12h2M15 16h2" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    plus: <path d="M12 5v14M5 12h14" />,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5M5.4 7a8 8 0 0 1 13-2L20 7M4 17l1.6 2a8 8 0 0 0 13-2" /></>,
    logout: <><path d="M10 4H5v16h5M10 12h11m-4-4 4 4-4 4" /></>,
    eye: <><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></>,
    chevron: <path d="m9 5 7 7-7 7" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    edit: <><path d="m15 4 5 5-10 10-6 1 1-6L15 4ZM13 6l5 5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] || paths.briefcase}</svg>;
}

function Brand({ light = false }) {
  return <div className={`brand ${light ? 'brand-light' : ''}`}><span className="brand-mark">h<span>.</span></span><span>HRAgent</span></div>;
}

function Login({ onLogin, initialError }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError || '');
  const submit = async event => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await api('/auth/login', { method: 'POST', body: { username: username.trim(), password } });
      const user = await api('/auth/me', { token: result.access_token });
      onLogin({ token: result.access_token, user });
      setPassword('');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return <div className="login-page">
    <section className="login-story">
      <Brand light />
      <div className="story-copy"><span className="eyebrow light">A BETTER WAY TO HIRE</span><h1>好的人才，<br />从清晰的需求开始。</h1><p>连接你的团队与下一个可能。<br />让每一个岗位，都有明确的方向。</p></div>
      <div className="story-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="art-dot" /><div className="art-card"><div className="art-card-icon"><Icon name="briefcase" size={28} /></div><div><span>YOUR NEXT CHAPTER</span><strong>让招聘，井然有序。</strong></div><Icon name="arrow" /></div></div>
      <div className="story-footer"><span className="tiny-dot" /> 为专注招聘的团队而建</div>
    </section>
    <section className="login-main"><div className="login-top"><span>招聘工作空间</span><span className="local-badge">LOCAL</span></div><div className="login-box"><div className="login-symbol"><Icon name="lock" size={25} /></div><p className="eyebrow">WELCOME BACK</p><h2>登录你的工作空间</h2><p className="login-description">使用公司账号登录，开始管理招聘岗位。</p>
      <form onSubmit={submit}>
        <label>用户名或邮箱<input autoComplete="username" autoFocus required maxLength={254} value={username} onChange={e => setUsername(e.target.value)} placeholder="输入用户名或邮箱" disabled={busy} /></label>
        <label>密码<div className="password-field"><input autoComplete="current-password" required maxLength={72} type={visible ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="输入密码" disabled={busy} /><button type="button" className="icon-button" onClick={() => setVisible(!visible)} aria-label={visible ? '隐藏密码' : '显示密码'} aria-pressed={visible}><Icon name="eye" size={18} /></button></div></label>
        {error && <div className="alert error" role="alert">{error}</div>}
        <button className="button primary login-submit" disabled={busy} type="submit">{busy ? '正在登录…' : '登录工作空间'}{!busy && <Icon name="arrow" size={18} />}</button>
      </form><p className="login-help"><Icon name="lock" size={13} /> 账号由公司管理员分配。如需帮助，请联系管理员。</p>
    </div><div className="login-bottom">HRAgent <span>·</span> 让每一次招聘更有方向</div></section>
  </div>;
}

function PositionEditor({ position, departments, call, onClose, onSaved }) {
  const dialog = useRef(null);
  const [values, setValues] = useState(() => position ? Object.fromEntries(Object.keys(INITIAL_FORM).map(key => [key, position[key] ?? ''])) : { ...INITIAL_FORM });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const available = departments.filter(dept => dept.is_active || dept.id === position?.department_id);
  useEffect(() => { dialog.current.showModal(); }, []);
  const change = event => setValues(current => ({ ...current, [event.target.name]: event.target.value }));
  const save = async event => {
    event.preventDefault(); if (busy) return;
    const payload = { ...values, title: values.title.trim(), location: values.location.trim() || null, description: values.description.trim() || null,
      target_headcount: Number(values.target_headcount), hired_headcount: Number(values.hired_headcount) };
    if (payload.hired_headcount > payload.target_headcount) { setError('已招聘人数不能大于计划招聘人数。'); return; }
    setError(''); setBusy(true);
    try {
      await call(position ? `/positions/${position.id}` : '/positions', { method: position ? 'PATCH' : 'POST', body: payload });
      onSaved(position ? '岗位信息已更新。' : '新岗位已创建。');
    } catch (err) { setError(err.message); setBusy(false); }
  };
  return <dialog ref={dialog} className="editor-dialog" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-heading"><div><p className="eyebrow">POSITION DETAILS</p><h2>{position ? '编辑岗位' : '新增招聘岗位'}</h2></div><button type="button" className="icon-button" disabled={busy} onClick={onClose} aria-label="关闭"><Icon name="close" /></button></div>
    <p className="muted editor-intro">填写岗位信息，所有内容仅在当前公司内可见。</p>
    <form onSubmit={save}><fieldset disabled={busy}><div className="form-grid">
      <label className="full">岗位名称 <input name="title" autoFocus value={values.title} onChange={change} required maxLength={200} placeholder="例如：Java 后端开发工程师" /></label>
      <label>所属部门<select name="department_id" value={values.department_id} onChange={change} required><option value="">选择部门</option>{available.map(dept => <option value={dept.id} key={dept.id}>{dept.name}{dept.is_active ? '' : '（已停用）'}</option>)}</select></label>
      <label>工作地点<input name="location" value={values.location} onChange={change} maxLength={100} placeholder="例如：上海" /></label>
      <label>计划招聘人数<input name="target_headcount" type="number" min="1" max="100000" step="1" required value={values.target_headcount} onChange={change} /></label>
      <label>已招聘人数<input name="hired_headcount" type="number" min="0" max={values.target_headcount || 100000} step="1" required value={values.hired_headcount} onChange={change} /></label>
      <label>招聘状态<select name="recruitment_status" value={values.recruitment_status} onChange={change}>{Object.entries(STATUS).map(([key, text]) => <option value={key} key={key}>{text}</option>)}</select></label>
      <div className="vacancy-preview"><span>剩余空缺</span><strong>{Math.max(0, Number(values.target_headcount) - Number(values.hired_headcount))}<small>人</small></strong></div>
      <label className="full">岗位备注 <span className="optional">选填</span><textarea name="description" value={values.description} onChange={change} rows={3} maxLength={10000} placeholder="填写岗位的补充信息" /></label>
    </div></fieldset>
    {!available.some(dept => dept.is_active) && <div className="alert">暂无启用的部门，请联系管理员在部门管理中新增部门，或通过部门接口启用已有部门。</div>}
    {error && <div className="alert error" role="alert">{error}</div>}
    <div className="dialog-footer"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" type="submit" disabled={busy || !available.length}>{busy ? '保存中…' : '保存岗位'}</button></div>
    </form>
  </dialog>;
}

function Workspace({ session, onLogout }) {
  const isAdmin = session.user.role === 'admin';
  const [view, setView] = useState('positions');
  const departmentView = isAdmin && view === 'departments';
  const pageTitle = departmentView ? '部门管理' : '岗位管理';
  const [company, setCompany] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [orgLoading, setOrgLoading] = useState(true);
  const [orgError, setOrgError] = useState('');
  const [result, setResult] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState({ search: '', department: '', status: '' });
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [editor, setEditor] = useState(null);
  const [opening, setOpening] = useState(null);
  const call = useCallback(async (path, options = {}) => {
    try { return await api(path, { ...options, token: session.token }); }
    catch (err) {
      if (err.status === 401 || (err.status === 403 && /停用|无权访问 HR|不存在/.test(err.message))) onLogout('登录状态已失效，请重新登录。');
      throw err;
    }
  }, [session.token, onLogout]);

  useEffect(() => {
    const controller = new AbortController();
    setOrgError(''); setOrgLoading(true);
    const loadDepartments = async () => {
      let collected = [], offset = 0;
      while (true) {
        const rows = await call(`/departments?limit=200&offset=${offset}`, { signal: controller.signal });
        collected = collected.concat(rows); offset += rows.length;
        if (rows.length < 200) break;
      }
      if (!controller.signal.aborted) setDepartments(collected);
    };
    Promise.all([
      call('/companies/current', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setCompany(value); }),
      loadDepartments(),
    ]).catch(err => { if (!controller.signal.aborted) setOrgError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setOrgLoading(false); });
    return () => controller.abort();
  }, [call, reload]);

  useEffect(() => {
    if (departmentView) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: PAGE_SIZE, offset: page * PAGE_SIZE });
    if (filters.search) params.set('search', filters.search);
    if (filters.department) params.set('department_id', filters.department);
    if (filters.status) params.set('recruitment_status', filters.status);
    setLoading(true); setError('');
    call(`/positions?${params}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setResult(value); })
      .catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [call, filters, page, reload, departmentView]);

  const applyFilter = (key, value) => { setFilters(current => ({ ...current, [key]: value })); setPage(0); };
  const edit = async position => {
    if (opening) return;
    setOpening(position.id); setNotice('');
    try { setEditor({ position: await call(`/positions/${position.id}`) }); }
    catch (err) { setError(err.message); }
    finally { setOpening(null); }
  };
  const name = company?.name || session.user.tenant_id;
  return <div className="workspace">
    <aside className="sidebar"><Brand /><span className="nav-label">工作空间</span><nav className="workspace-nav" aria-label="主导航"><button type="button" className={`nav-item ${!departmentView ? 'active' : ''}`} aria-current={!departmentView ? 'page' : undefined} onClick={() => { setView('positions'); setNotice(''); }}><Icon name="briefcase" />岗位管理{!departmentView && <span className="nav-line" />}</button>{isAdmin && <button type="button" className={`nav-item ${departmentView ? 'active' : ''}`} aria-current={departmentView ? 'page' : undefined} onClick={() => { setView('departments'); setEditor(null); setNotice(''); }}><Icon name="building" />部门管理{departmentView && <span className="nav-line" />}</button>}</nav><div className="sidebar-company"><div className="company-icon"><Icon name="building" /></div><div><small>当前所属公司</small><strong title={name}>{name}</strong></div><span className="tiny-dot" /></div><div className="sidebar-note">让每个岗位，都找到合适的人。</div></aside>
    <main className="workspace-main"><header className="topbar"><div>工作空间 <span>/</span><strong>{pageTitle}</strong></div><div className="user-menu"><span className="avatar">{session.user.role === 'admin' ? 'A' : 'H'}</span><span>{session.user.role === 'admin' ? '管理员' : 'HR'}<small>{company?.short_name || '招聘工作空间'}</small></span><button className="icon-button" onClick={() => onLogout()} aria-label="退出登录" title="退出登录"><Icon name="logout" size={18} /></button></div></header>
      <div className="page-content"><div className="page-heading"><div><p className="eyebrow">{departmentView ? 'ORGANIZATION MANAGEMENT' : 'RECRUITMENT MANAGEMENT'}</p><h1>{pageTitle}<span className="title-dot">.</span></h1><p className="muted">{departmentView ? '维护公司部门，为团队的招聘岗位建立清晰归属。' : '管理团队的招聘需求，让每一个机会清晰可见。'}</p></div>{!departmentView && <button className="button primary" onClick={() => { setNotice(''); setEditor({ position: null }); }}><Icon name="plus" size={18} />新增岗位</button>}</div>
        <section className="company-banner"><div className="company-icon"><Icon name="building" size={23} /></div><div><span>所属公司</span><h2>{name}</h2><p>{company?.address || '公司工作空间'}<i />{departmentView ? '仅管理员可查看和新增本公司部门' : 'HR 与管理员均可新增和编辑本公司岗位'}</p></div><span className="company-badge">公司工作空间</span></section>
        {orgError && <div className="alert error" role="alert">公司或部门资料加载失败：{orgError}<button className="text-button" onClick={() => setReload(value => value + 1)}>重试</button></div>}
        {notice && <div className="alert success" role="status">{notice}<button className="icon-button" aria-label="关闭提示" onClick={() => setNotice('')}><Icon name="close" size={16} /></button></div>}
        {departmentView ? <DepartmentManagement departments={departments} loading={orgLoading} error={orgError} call={call} Icon={Icon} onRefresh={() => setReload(value => value + 1)} onCreated={() => { setNotice('新部门已创建，可在岗位中选择。'); setReload(value => value + 1); }} /> : <section className="positions-card"><div className="card-heading"><div><h2>招聘岗位 <span className="count">{error ? '—' : result.total}</span></h2><p>按部门和招聘状态查看当前岗位。</p></div><button className="button refresh-button" onClick={() => setReload(value => value + 1)} disabled={loading}><Icon name="refresh" size={15} />刷新</button></div>
          <div className="toolbar"><form className="search-box" onSubmit={event => { event.preventDefault(); applyFilter('search', search.trim()); }}><Icon name="search" size={17} /><input aria-label="搜索岗位或部门" placeholder="搜索岗位名称或部门…" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} /><button type="submit">搜索</button></form><select aria-label="按部门筛选" value={filters.department} onChange={event => applyFilter('department', event.target.value)}><option value="">全部部门</option>{departments.map(dept => <option value={dept.id} key={dept.id}>{dept.name}{dept.is_active ? '' : '（停用）'}</option>)}</select><select aria-label="按招聘状态筛选" value={filters.status} onChange={event => applyFilter('status', event.target.value)}><option value="">全部招聘状态</option>{Object.entries(STATUS).map(([key, value]) => <option value={key} key={key}>{value}</option>)}</select></div>
          {error ? <div className="empty-state" role="alert"><span className="empty-icon"><Icon name="briefcase" size={30} /></span><h3>暂时无法加载岗位</h3><p>{error}</p><button className="button" onClick={() => setReload(value => value + 1)}>重新加载</button></div> : loading ? <div className="empty-state" role="status"><span className="spinner" /><p>正在加载岗位…</p></div> : result.items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="briefcase" size={32} /></span><h3>{filters.search || filters.department || filters.status ? '没有符合条件的岗位' : '从第一个招聘岗位开始'}</h3><p>{filters.search || filters.department || filters.status ? '试试调整搜索词或筛选条件。' : '添加部门的招聘需求，设置人数和状态。'}</p><button className="button primary" onClick={() => setEditor({ position: null })}><Icon name="plus" size={16} />新增岗位</button></div> : <div className="table-wrap"><table><thead><tr><th>岗位名称</th><th>所属部门</th><th>招聘进度</th><th>剩余空缺</th><th>招聘状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{result.items.map(position => <tr key={position.id}><td><strong className="position-title">{position.title}</strong><span className="position-location">{position.location || '地点未填写'}</span></td><td>{position.department_name}{!position.department_is_active && <small className="inactive-hint">部门已停用</small>}</td><td><div className="progress-text"><strong>{position.hired_headcount}</strong><span> / {position.target_headcount} 人</span></div><div className="progress-track"><div style={{ width: `${Math.min(100, position.hired_headcount / position.target_headcount * 100)}%` }} /></div></td><td><strong className="vacancy-number">{position.vacancy_count}</strong><small> 人</small>{position.vacancy_count === 0 && <small className="inactive-hint">已招满</small>}</td><td><span className={`status-badge ${position.recruitment_status}`}><span />{STATUS[position.recruitment_status]}</span></td><td className="date-cell">{time(position.updated_at)}</td><td><button className="text-button edit-button" onClick={() => edit(position)} disabled={!!opening}><Icon name="edit" size={15} />{opening === position.id ? '加载中' : '编辑'}</button></td></tr>)}</tbody></table></div>}
          <div className="table-footer"><span>{error ? '加载失败' : `共 ${result.total} 个符合条件的岗位`}</span><div className="pagination"><button className="icon-button previous" aria-label="上一页" disabled={page === 0 || loading} onClick={() => setPage(value => value - 1)}><Icon name="chevron" size={15} /></button><span>第 {page + 1} / {Math.max(1, Math.ceil(result.total / PAGE_SIZE))} 页</span><button className="icon-button" aria-label="下一页" disabled={loading || (page + 1) * PAGE_SIZE >= result.total} onClick={() => setPage(value => value + 1)}><Icon name="chevron" size={15} /></button></div></div>
        </section>}<footer className="workspace-footer"><Brand /><span>清晰的岗位，是高效招聘的开始。</span></footer>
      </div>
    </main>
    {editor && <PositionEditor position={editor.position} departments={departments} call={call} onClose={() => setEditor(null)} onSaved={message => { setEditor(null); setNotice(message); setPage(0); setReload(value => value + 1); }} />}
  </div>;
}

export default function App() {
  const [session, setSession] = useState(null);
  const [booting, setBooting] = useState(true);
  const [loginError, setLoginError] = useState('');
  const logout = useCallback((message = '') => {
    sessionStorage.removeItem(SESSION_KEY); setSession(null); setLoginError(message);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const token = sessionStorage.getItem(SESSION_KEY);
    if (!token) { setBooting(false); return () => controller.abort(); }
    api('/auth/me', { token, signal: controller.signal })
      .then(user => { if (!controller.signal.aborted) setSession({ token, user }); })
      .catch(err => { if (!controller.signal.aborted) logout(err.message); })
      .finally(() => { if (!controller.signal.aborted) setBooting(false); });
    return () => controller.abort();
  }, [logout]);
  if (booting) return <div className="boot-screen"><Brand /><span className="spinner" /><p>正在恢复工作空间…</p></div>;
  if (!session) return <Login initialError={loginError} onLogin={value => { sessionStorage.setItem(SESSION_KEY, value.token); setSession(value); setLoginError(''); }} />;
  return <Workspace session={session} onLogout={logout} />;
}
