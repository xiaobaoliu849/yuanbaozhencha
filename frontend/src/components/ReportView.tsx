import { useEffect, useMemo, useState } from 'react'
import { LABEL, addWatch, cleanHeadline, getReport, ownerId, type ClaimResult, type Report, type Source } from '../api'
import { go } from '../App'

const STANCE = { support: '支持', refute: '反驳', context: '背景' }
const MOOD = { true: '✅ 是真的，可以放心转', false: '🙅 是谣言，别再转了', mixed: '🤔 有真有假，要看情况', unknown: '🔍 暂时查不清，先别急着信' }

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
      <nav className="crumbs">
        <button className="back" onClick={() => go('/')}>← 返回首页</button>
        <span>结案报告 · No.{report.id}</span>
      </nav>

      <div className="report-head">
        <span className={`stamp slam v-${report.verdict}`}>{report.verdict_label}</span>
        <p className={`mood v-${report.verdict}`}>{MOOD[report.verdict]}</p>
        <h1>{cleanHeadline(report.headline || report.title)}</h1>
        <p className="meta">{new Date(report.created_at).toLocaleString('zh-CN')} · 搜索由元宝搜索提供</p>
        <div className="stats">
          <div><b>{report.claims.length}</b><small>条说法</small></div>
          <div><b>{searches}</b><small>次搜索</small></div>
          <div><b>{rounds}</b><small>轮比对</small></div>
          <div><b>{cited.length}<em>/{report.sources.length}</em></b><small>引用来源</small></div>
        </div>
      </div>

      {report.claims.length > 0 && (
        <section className="verdicts">
          <h2>结论速览</h2>
          <ol>
            {report.claims.map((c) => (
              <li key={c.index}>
                <a
                  href={`#claim-${c.index}`}
                  onClick={(e) => {
                    e.preventDefault()
                    document.getElementById(`claim-${c.index}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                  }}
                >
                  <span className={`mini-stamp v-${c.verdict}`}>{c.verdict_label}</span>
                  <span className="v-claim">{c.claim}</span>
                  <small>把握 {c.confidence}% ›</small>
                </a>
              </li>
            ))}
          </ol>
        </section>
      )}

      {report.off_limits && <p className="note box">这类内容不在查证范围内：{report.off_limits_reason}</p>}

      {report.family_message && (
        <div className="family">
          <small>一句话结论，可以直接转发</small>
          <p>{report.family_message}</p>
        </div>
      )}

      <Readable text={report.readable_text} fromImage={report.had_image} />

      {report.claims.map((c, i) => (
        <div key={c.index} id={`claim-${c.index}`} className="rise" style={{ animationDelay: `${0.15 + i * 0.12}s` }}>
          <ClaimCard c={c} byId={byId} reportId={report.id} />
        </div>
      ))}

      {report.claims.length > 0 && (
        <div className="watch-hint">
          <span className="eye">👁</span>
          <div>
            <b>这件事以后会变吗？</b>
            <p>在上面任意一条说法下点「每天盯着这条」，我每天自动用元宝搜索重查一次，结论变了会在「我的盯梢」里标红提醒你。</p>
          </div>
          <button className="ghost small" onClick={() => go('/watch')}>我的盯梢</button>
        </div>
      )}

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

      <div className="dock">
        <button className="ghost" onClick={() => go('/')}>🔍 再查一条</button>
        {report.family_message && (
          <button
            className="primary"
            onClick={async () => {
              const text = `${report.family_message}\n查证报告：${link}`
              // The system share sheet only exists on HTTPS; otherwise copy the text for pasting.
              if (navigator.share) {
                try {
                  await navigator.share({ title: '查得到，信得过', text })
                  return
                } catch (e) {
                  if (e instanceof DOMException && e.name === 'AbortError') return
                }
              }
              if (await copy(text)) {
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              }
            }}
          >
            {copied ? '已复制，去粘贴吧 ✓' : '📤 分享'}
          </button>
        )}
      </div>
    </article>
  )
}

/** The checked text; long screenshot transcripts start folded so the verdicts stay on the first screen. */
function Readable({ text, fromImage }: { text: string; fromImage: boolean }) {
  const long = text.length > 120 || text.split('\n').length > 4
  const [open, setOpen] = useState(!long)
  return (
    <blockquote className={`readable ${open ? '' : 'folded'}`}>
      <small>{fromImage ? '从截图里识别到的内容' : '要查的内容'}</small>
      <span className="readable-text">{text}</span>
      {long && (
        <button className="link" onClick={() => setOpen(!open)}>
          {open ? '收起' : '展开全文'}
        </button>
      )}
    </blockquote>
  )
}

function SourceRow({ s }: { s: Source }) {
  return (
    <li id={`src-${s.id}`} className={s.cited ? 'cited' : ''}>
      <span className="sid">{s.id}</span>
      <span>
        {s.tier && <span className={`tier tier-${s.tier}`}>{s.tier_label}</span>}
        <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
      </span>
      <span className="src-meta">
        {s.site || host(s.url)}
        {s.date && ` · ${s.date.slice(0, 10)}`}
        {s.cited && <b> · 已引用</b>}
      </span>
    </li>
  )
}

function ClaimCard({ c, byId, reportId }: { c: ClaimResult; byId: Map<string, Source>; reportId: string }) {
  const [chainOpen, setChainOpen] = useState(true)
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
                    {s.tier && <span className={`tier tier-${s.tier}`}>{s.tier_label}</span>}
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
          {chainOpen ? '收起' : '展开'}调查过程（{c.chain.length} 轮）
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

      {chainOpen && <p className="chain-title">调查过程</p>}
      {chainOpen && (
        <ol className="chain">
          {c.chain.map((r, k) => (
            <li key={r.round}>
              <b>第 {r.round} 轮</b>
              {k > 0 && c.chain[k - 1].next_reason && <p className="why">↻ {c.chain[k - 1].next_reason}</p>}
              <ul>
                {r.searches.map((s, i) => (
                  <li key={i}>
                    🔍 元宝搜索「{s.query}」{s.error ? ` 失败：${s.error}` : ` → ${s.found} 条，新来源 ${s.new} 个`}
                    {s.sources.length > 0 && (
                      <span className="chain-src">
                        {s.sources.map((sid) => (
                          <a key={sid} href={`#src-${sid}`}>{sid}</a>
                        ))}
                      </span>
                    )}
                  </li>
                ))}
                <li>⚖️ AI 阅读{r.sources ? ` ${r.sources} 个` : ''}网页，交叉比对</li>
                {r.evidence !== undefined && (
                  <li>
                    {r.evidence ? `✅ 原文核对：${r.verified}/${r.evidence} 句在网页里找到` : '✅ 原文核对：没有能引用的原文'}
                    {r.guard && <b className="guard-tag"> 核对不上，改判查不到</b>}
                  </li>
                )}
              </ul>
              <p>
                → <span className={`mini-stamp v-${r.verdict}`}>{LABEL[r.verdict]}</span> 把握 {r.confidence}%
                {r.note && k < c.chain.length - 1 && <span className="note-line">{r.note}</span>}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
