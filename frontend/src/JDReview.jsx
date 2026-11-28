import React, { useState } from 'react';

const fields = {
  source_position_title: '原文岗位名称', summary: '岗位概述', responsibilities: '岗位职责',
  location: '工作地点', employment_type: '用工类型', salary: '薪资待遇', experience: '经验要求', education: '学历要求',
};
const categories = { skill: '技能', experience: '经验', education: '学历', certification: '证书', language: '语言', other: '其他' };
const importance = { required: '必备', preferred: '优先', unspecified: '待明确' };

function fieldText(data, key) {
  if (key === 'responsibilities') return (data?.[key] || []).map(item => item.value).join('\n');
  return data?.[key]?.value || '';
}

function Evidence({ items, blocks }) {
  if (!items?.length) return null;
  return <details className="jd-source"><summary>原文依据（{items.length}）</summary>
    {items.map((item,i) => <blockquote key={i}>{item.quote}{blocks[item.block_id]?.page_number && <small>第 {blocks[item.block_id].page_number} 页</small>}</blockquote>)}
  </details>;
}

export default function JDReview({ jd, call, onPublished, onConflict }) {
  const editable = jd.review_status === 'awaiting_review';
  const [values, setValues] = useState(() => Object.fromEntries(Object.keys(fields).map(k => [k, fieldText(jd.reviewed_data,k)])));
  const [rows, setRows] = useState(() => jd.requirements.map(item => ({ ...item, key: item.id, evaluation_rule: item.evaluation_rule ?? '' })));
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const missing = rows.filter(r => !r.removed && r.description.trim() && !r.evaluation_rule.trim());
  const [error, setError] = useState('');
  const blocks = Object.fromEntries(jd.text_blocks.map(block => [block.block_id, block]));
  function change(key, patch) { setRows(current => current.map(r => r.key === key ? { ...r, ...patch } : r)); }
  function add() {
    setRows(current => [...current, { key: crypto.randomUUID(), description: '', category: 'skill', importance: 'unspecified', evaluation_rule: '', evidence: [] }]);
  }
  async function suggestRules() {
    if (generating || busy || !missing.length) return;
    setGenerating(true); setError('');
    try {
      const result = await call('/job-descriptions/' + jd.id + '/rule-suggestions', {
        method: 'POST', signal: AbortSignal.timeout(135000),
        body: missing.map(({ description, category, importance }) => ({ description, category, importance })),
      });
      const byKey = new Map(result.suggestions.map(s => [missing[s.index].key, s.evaluation_rule]));
      setRows(current => current.map(r => byKey.has(r.key) && !r.evaluation_rule.trim()
        ? { ...r, evaluation_rule: byKey.get(r.key) } : r));
    } catch (err) { setError(err.message); if (err.status === 409) onConflict(); }
    finally { setGenerating(false); }
  }
  async function publish(event) {
    event.preventDefault();
    if (!editable || busy || generating) return;
    const retained = rows.filter(r => !r.removed);
    if (!retained.length) { setError('至少保留一条筛选条件。'); return; }
    if (retained.some(r => !r.description.trim() || !r.evaluation_rule.trim() || r.importance === 'unspecified')) {
      setError('请为每条保留的条件填写描述、重要性和评估规则。'); return;
    }
    const requirements = retained.map(r => ({
      ...(r.id ? { requirement_id: r.id } : {}), description: r.description.trim(), category: r.category,
      importance: r.importance, evaluation_rule: r.evaluation_rule.trim(),
    }));
    const position_edits = {};
    for (const key of Object.keys(fields)) {
      if (values[key] === fieldText(jd.reviewed_data,key)) continue;
      position_edits[key] = key === 'responsibilities' ? values[key].split('\n').map(s => s.trim()).filter(Boolean) : values[key].trim() || null;
    }
    setBusy(true); setError('');
    try {
      const result = await call('/job-descriptions/' + jd.id + '/review', { method: 'POST',
        body: { position_edits, requirements, remove_requirement_ids: rows.filter(r => r.removed && r.id).map(r => r.id) },
      });
      onPublished(result);
    } catch (err) { setError(err.message); if (err.status === 409) onConflict(); }
    finally { setBusy(false); }
  }
  const questions = [...new Set([...(jd.structured_data?.clarification_questions || []), ...(jd.structured_data?.missing_information || [])])];
  return <form className="jd-review" onSubmit={publish}>
    {editable && questions.length > 0 && <details className="jd-source"><summary>待核对事项（{questions.length}）</summary><ul>{questions.map(q => <li key={q}>{q}</li>)}</ul></details>}
    <fieldset disabled={busy || generating}>
      <details className="jd-fields" open={!editable || undefined}><summary>岗位字段{editable ? ' · 查看与修改' : ''}</summary>
        <div className="form-grid">{Object.entries(fields).map(([key,label]) => editable
          ? <label key={key} className={['summary','responsibilities'].includes(key) ? 'full' : ''}>{label}{['summary','responsibilities'].includes(key)
              ? <textarea value={values[key]} rows={3} placeholder={key === 'responsibilities' ? '每行填写一项职责' : ''} onChange={e => setValues({ ...values,[key]: e.target.value })} />
              : <input value={values[key]} onChange={e => setValues({ ...values,[key]: e.target.value })} />}</label>
          : values[key] && <div key={key}><small>{label}</small><p className="jd-value">{values[key]}</p></div>)}</div>
      </details>
      <div className="jd-section-heading"><h3>筛选条件 <span className="count">{rows.filter(row => !row.removed).length}</span></h3>
        {editable && <button type="button" className="text-button" onClick={add}>＋ 添加条件</button>}</div>
      {editable && missing.length > 0 && <button type="button" className="button" onClick={suggestRules}>
        {generating ? '正在生成建议…' : `AI 补全 ${missing.length} 条空白评估规则`}
      </button>}
      {rows.map((row,i) => <article className={'jd-criterion' + (row.removed ? ' jd-removed' : '')} key={row.key}>
        {editable ? <>
          <div className="jd-section-heading"><strong>条件 {i+1}</strong><button type="button" className="text-button" onClick={() => {
            if (!row.id) setRows(current => current.filter(r => r.key !== row.key));
            else change(row.key,{ removed: !row.removed });
          }}>{row.removed ? '撤销移除' : '移除'}</button></div>
          {row.removed ? <p>{row.description}（发布时移除）</p> : <>
            {row.clarification && <p className="alert">{row.clarification}</p>}
            <label>条件描述<input required value={row.description} onChange={e => change(row.key,{description:e.target.value})} /></label>
            <div className="jd-controls">
              <label>类别<select value={row.category} onChange={e => change(row.key,{category:e.target.value})}>{Object.entries(categories).map(([k,n]) => <option key={k} value={k}>{n}</option>)}</select></label>
              <label>重要性<select required value={row.importance === 'unspecified' ? '' : row.importance} onChange={e => change(row.key,{importance:e.target.value})}><option value="">请选择</option><option value="required">必备</option><option value="preferred">优先</option></select></label>
            </div>
            <label>评估规则<textarea required rows={2} value={row.evaluation_rule} onChange={e => change(row.key,{evaluation_rule:e.target.value})} placeholder="描述应从简历中核对哪些证据" /></label>
            <Evidence items={row.evidence} blocks={blocks} />
          </>}
        </> : <>
          <strong>{row.description}</strong><p className="jd-meta">{importance[row.importance]} · {categories[row.category]}</p>
          <p>{row.evaluation_rule}</p><Evidence items={row.evidence} blocks={blocks} />
        </>}
      </article>)}
    </fieldset>
    {error && <p className="alert error" role="alert">{error}</p>}
    {editable ? <div className="jd-publish"><small>发布后，同岗位之前的发布版本将自动归档。</small><button className="button primary" disabled={busy || generating}>{busy ? '发布中…' : '确认并发布此版本'}</button></div>
      : jd.published_at && <p className="jd-meta">发布时间 · {new Date(jd.published_at).toLocaleString('zh-CN')}</p>}
  </form>;
}
