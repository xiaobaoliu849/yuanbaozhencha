import { useEffect, useMemo, useState } from 'react'
import { LABEL, addWatch, getReport, ownerId, type ClaimResult, type Report, type Source } from '../api'
import { go } from '../App'

const STANCE = { support: '支持', refute: '反驳', context: '背景' }

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  }
}

export default function ReportView({ id, initial }: { id: string; initial: Report | null }) {
  const [report, setReport] = useState<Report | null>(initial)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (initial) return
    getReport(id).then(setReport).catch((e) => setErr(e.message))
  }, [id, initial])

  const byId = useMemo(() => new Map((report?.sources ?? []).map((s) => [s.id, s])), [report])

  if (err) return <p className="error">{err}</p>
  if (!report) return <p className="loading">正在打开报告…</p>

  const link = `${location.origin}/r/${report.id}`
  const cited = report.sources.filter((s) => s.cited)
  const searches = report.claims.reduce((n, c) => n + c.searched.length, 0)
  const rounds = report.claims.reduce((n, c) => n + c.chain.length, 0)

  return (
    <article className="report">
      <div className="report-head">
        <span className={`stamp v-${report.verdict}`}>{report.verdict_label}</span>
        <h1>{report.headline || report.title}</h1>
        <p className="meta">
          {new Date(report.created_at).toLocaleString('zh-CN')} · {report.claims.length} 条说法 · 搜索 {searches} 次 ·{' '}
          {rounds} 轮比对 · {report.sources.length} 个来源，引用 {cited.length} 个
        </p>
      </div>

      <blockquote className="readable">
        <small>{report.had_image ? '从截图里识别到的内容' : '要查的内容'}</small>
        {report.readable_text}
      </blockquote>

      {report.off_limits && <p className="note box">这类内容不在查证范围内：{report.off_limits_reason}</p>}

      {report.family_message && (
        <div className="family">
          <small>可以直接发到家族群</small>
          <p>{report.family_message}</p>
          <button
            className="primary"
            onClick={async () => {
              if (await copy(`${report.family_message}\n查证报告：${link}`)) {
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              }
            }}
          >
            {copied ? '已复制 ✓' : '复制这段话 + 报告链接'}
          </button>
        </div>
      )}

      {report.claims.map((c) => (
        <ClaimCard key={c.index} c={c} byId={byId} reportId={report.id} />
      ))}

      {report.sources.length > 0 && (
        <section className="sources">
          <h2>全部来源</h2>
          <p className="hint">元宝搜索返回的所有网页。标「已引用」的是结论依据。</p>
          <ol>
            {[...cited, ...report.sources.filter((s) => !s.cited)].map((s) => (
              <SourceRow key={s.id} s={s} />
            ))}
          </ol>
        </section>
      )}

      <div className="again">
        <button className="ghost" onClick={() => go('/')}>再查一条</button>
      </div>
    </article>
  )
}

function SourceRow({ s }: { s: Source }) {
  return (
    <li id={`src-${s.id}`} className={s.cited ? 'cited' : ''}>
      <span className="sid">{s.id}</span>
      <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
      <span className="src-meta">
        {s.site || host(s.url)}
        {s.date && ` · ${s.date.slice(0, 10)}`}
        {s.cited && <b> · 已引用</b>}
      </span>
    </li>
  )
}

function ClaimCard({ c, byId, reportId }: { c: ClaimResult; byId: Map<string, Source>; reportId: string }) {
  const [chainOpen, setChainOpen] = useState(false)
  const [watchOpen, setWatchOpen] = useState(false)
  const [token, setToken] = useState('')
  const [watchState, setWatchState] = useState<'idle' | 'saving' | 'done' | string>('idle')

  async function watch() {
    setWatchState('saving')
    try {
      await addWatch(ownerId(), reportId, c.index, token)
      setWatchState('done')
    } catch (e) {
      setWatchState(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className={`claim v-${c.verdict}-edge`}>
      <div className="claim-head">
        <span className="num">{c.index + 1}</span>
        <h3>{c.claim}</h3>
        <span className={`mini-stamp v-${c.verdict}`}>{c.verdict_label}</span>
      </div>
      <div className="confidence">
        <span style={{ width: `${c.confidence}%` }} />
        <small>把握 {c.confidence}%</small>
      </div>
      <p className="explain">{c.explanation}</p>
      {c.guard && <p className="guard">🛡 {c.guard}</p>}
      {c.conflicts && <p className="conflicts">⚖ 来源有分歧：{c.conflicts}</p>}

      {c.evidence.length > 0 && (
        <ul className="evidence">
          {c.evidence.map((e, i) => {
            const s = byId.get(e.source)
            return (
              <li key={i} className={`stance-${e.stance}`}>
                <span className="tag">{STANCE[e.stance]}</span>
                <q>{e.quote}</q>
                {!e.quote_found && <span className="unverified">原文未逐字核对上</span>}
                {s && (
                  <a href={s.url} target="_blank" rel="noreferrer" className="ev-src">
                    [{s.id}] {s.site || host(s.url)}
                    {s.date && ` · ${s.date.slice(0, 10)}`} ↗
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="claim-actions">
        <button className="ghost small" onClick={() => setChainOpen(!chainOpen)}>
          {chainOpen ? '收起' : '看'}证据链（{c.chain.length} 轮）
        </button>
        {watchState === 'done' ? (
          <button className="ghost small" onClick={() => go('/watch')}>已加入盯梢 ✓ 去看看</button>
        ) : (
          <button className="ghost small" onClick={() => setWatchOpen(!watchOpen)}>👁 每天盯着这条</button>
        )}
      </div>

      {watchOpen && watchState !== 'done' && (
        <div className="watch-form">
          <p>每天自动用元宝搜索重新查一次，结论变了会在「我的盯梢」里标红。</p>
          <label>
            想在微信里收到提醒？填 PushPlus token（可不填）
            <input value={token} onChange={(e) => setToken(e.target.value)} placeholder="pushplus.plus 里获取" />
          </label>
          <button className="primary small" disabled={watchState === 'saving'} onClick={watch}>
            {watchState === 'saving' ? '保存中…' : '开始盯梢'}
          </button>
          {!['idle', 'saving', 'done'].includes(watchState) && <p className="error">{watchState}</p>}
        </div>
      )}

      {chainOpen && (
        <ol className="chain">
          {c.chain.map((r) => (
            <li key={r.round}>
              <b>第 {r.round} 轮</b>
              <ul>
                {r.searches.map((s, i) => (
                  <li key={i}>
                    🔍 「{s.query}」{s.error ? ` 失败：${s.error}` : ` → ${s.found} 条，新来源 ${s.new} 个`}
                    {s.sources.length > 0 && (
                      <span className="chain-src">
                        {s.sources.map((sid) => (
                          <a key={sid} href={`#src-${sid}`}>{sid}</a>
                        ))}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <p>
                → 判断：<span className={`mini-stamp v-${r.verdict}`}>{LABEL[r.verdict]}</span>{' '}
                把握 {r.confidence}%
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
