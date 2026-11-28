import React, { useEffect, useRef, useState } from 'react';
import './resume-review.css';

const MATCH_LABEL = { met: '满足', unknown: '待核实', unmet: '不满足' };
const MATCH_STATUS = { pending: '待评审', processing: '评审中', completed: '已评审', failed: '评审失败' };

function useReviewStage(call, path, statusKey) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [revision, setRevision] = useState(0);
  const inFlight = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]);
        const result = await call(path, { signal });
        if (controller.signal.aborted) return;
        setData(result);
        setError('');
        if (result[statusKey] === 'processing') timer = setTimeout(load, 2000);
      } catch (err) {
        if (!controller.signal.aborted) setError(err.message);
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [call, path, statusKey, revision]);

  async function start() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    try {
      const result = await call(path, { method: 'POST' });
      setData(result);
      setError('');
      setRevision(value => value + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  function reload() {
    setError('');
    setData(null);
    setRevision(value => value + 1);
  }
  return { data, status: data?.[statusKey], error, submitting, start, reload };
}

function Evidence({ items }) {
  if (!items?.length) return null;
  return <details className="jd-source review-evidence">
    <summary>查看原文证据（{items.length}）</summary>
    {items.map(item => <blockquote key={item.block_id}>
      <small>第 {item.page_number} 页 · {item.block_id}</small>{item.quote}
    </blockquote>)}
  </details>;
}

function MatchBadge({ value }) {
  return <span className={'jd-badge review-' + value}>{MATCH_LABEL[value]}</span>;
}

function Findings({ item }) {
  return <>
    <p className="review-text">{item.reason}</p>
    {item.follow_up_question && <p className="review-question"><strong>建议追问</strong> {item.follow_up_question}</p>}
    <Evidence items={item.evidence} />
  </>;
}

function MatchReport({ results }) {
  return <section className="jd-card review-report"><div className="jd-detail-heading">
    <h2>历史岗位条件匹配明细</h2>
    <div className="review-totals">{Object.entries(MATCH_LABEL).map(([value, label]) =>
      <span key={value} className={'jd-badge review-' + value}>{label} {results.filter(row => row.match_status === value).length}</span>
    )}</div>
  </div>
    {results.every(item => !item.checks?.length) && <p className="muted">这份历史报告只保存了岗位条件的判断和证据。</p>}
    {results.map(item => <details key={item.requirement_id} className="review-requirement">
      <summary><span>{item.description}</span><MatchBadge value={item.match_status} /></summary>
      <div className="review-body">
        <small>{item.importance === 'required' ? '必备条件' : '优先条件'}</small>
        <p><strong>评估规则</strong> {item.evaluation_rule}</p>
        {item.checks?.length ? <ul className="review-checks">{item.checks.map((check, index) =>
          <li key={index}><div className="review-check-title"><strong>{check.criterion}</strong><MatchBadge value={check.match_status} /></div>
            <Findings item={check} />
          </li>
        )}</ul> : <Findings item={item} />}
      </div>
    </details>)}
  </section>;
}

function SixDimensionReport({ report }) {
  const { summary, issues, structured } = report;
  return <section className="jd-card review-report">
    <div className="jd-detail-heading"><h2>六维度评审报告</h2><strong>综合分 {report.weighted_score} / 100</strong></div>
    <p>{summary.overall_comment}</p><p>{summary.fit_assessment}</p>
    {report.dimension_scores.map(dim => <details key={dim.key} className="review-requirement">
      <summary><span>{dim.dimension} · {dim.score} 分</span><small>固定权重 {Math.round(dim.weight * 100)}%</small></summary>
      <div className="review-body">
        <h3>问题</h3>{dim.issues.length ? <ul>{dim.issues.map((x,i) => <li key={i}>{x}</li>)}</ul> : <p>未发现具体问题。</p>}
        <h3>建议</h3>{dim.suggestions.length ? <ul>{dim.suggestions.map((x,i) => <li key={i}>{x}</li>)}</ul> : <p>暂无补充建议。</p>}
      </div>
    </details>)}
    <details className="review-requirement"><summary>亮点与改进方向</summary>
      <h3>亮点</h3><ul>{summary.highlights.map((x,i) => <li key={i}>{x}</li>)}</ul>
      <h3>改进方向</h3><ul>{summary.core_improvements.map((x,i) => <li key={i}>{x}</li>)}</ul>
    </details>
    <details className="review-requirement"><summary>问题诊断（{issues.length}）</summary>
      {issues.map((issue,i) => <article key={i}><strong>{issue.dimension} · {issue.location}</strong>
        <p>{issue.description}</p><p>{issue.suggestion}</p></article>)}
    </details>
    <details className="review-requirement"><summary>查看简历信息</summary>
      <p>{structured.name} · {structured.target_position}</p>
      {structured.work_experience.map((job,i) => <p key={i}>{job.company} · {job.position} · {job.duration}<br />{job.description}</p>)}
      {structured.projects.map((project,i) => <p key={i}>{project.name} · {project.duration}<br />{project.description}</p>)}
    </details>
  </section>;
}

export default function ResumeReviewDetail({ task, position, call, onBack }) {
  const stage = useReviewStage(call, '/resume-reviews/' + task.id + '/match', 'status');
  const report = stage.data?.six_dimension_report;
  const history = stage.data?.requirement_results;
  return <div className="jd-page resume-review-detail">
    <button type="button" className="text-button" onClick={onBack}>← 返回审查任务</button>
    <header className="page-heading"><div><h1>{task.original_filename}</h1>
      <p className="muted">{position.title} · JD v{task.jd_version} · {task.page_count} 页</p>
      <small className="jd-meta">任务编号 {task.id}</small></div></header>
    <section className="jd-card">
      <div className="jd-detail-heading"><h2>简历六维度评审</h2>
        <span className={'jd-badge review-' + stage.status} role="status">
          {stage.status === 'completed' && !report ? '待评审（已有历史报告）' : MATCH_STATUS[stage.status] || '读取中…'}
        </span></div>
      {stage.error ? <div className="alert error" role="alert">{stage.error}
        <button className="text-button" onClick={stage.reload}>重新查询状态</button></div>
        : <>
          {stage.data?.match_error && <p className="alert error">{stage.data.match_error}</p>}
          {stage.status === 'processing' && <p role="status">正在后台读取简历并生成评审报告，完成后会自动显示。</p>}
          {stage.data && !report && stage.status !== 'processing' &&
            <button className="button primary" disabled={stage.submitting} onClick={stage.start}>
              {stage.submitting ? '提交中…' : stage.status === 'failed' ? '重新评审' : '开始六维度评审'}
            </button>}
        </>}
    </section>
    {report && <SixDimensionReport report={report} />}
    {history?.length > 0 && <MatchReport results={history} />}
  </div>;
}
