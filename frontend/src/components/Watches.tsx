import { useEffect, useState } from 'react'
import { LABEL, ackWatch, listWatches, ownerId, recheckWatch, stopWatch, type Watch } from '../api'
import { go } from '../App'

const when = (iso: string) => new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })

export default function Watches({ onCount }: { onCount: (n: number) => void }) {
  const [watches, setWatches] = useState<Watch[] | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const owner = ownerId()

  useEffect(() => {
    listWatches(owner).then(setWatches).catch((e) => setErr(e.message))
  }, [owner])

  useEffect(() => {
    if (watches) onCount(watches.filter((w) => w.changed).length)
  }, [watches, onCount])

  const replace = (w: Watch) => setWatches((ws) => ws?.map((x) => (x.id === w.id ? w : x)) ?? null)

  async function recheck(w: Watch) {
    setBusy(w.id)
    setErr('')
    try {
      replace(await recheckWatch(owner, w.id))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  if (!watches) return <p className="loading">{err || '正在加载…'}</p>

  return (
    <section className="watches">
      <h1>我的盯梢</h1>
      <p className="lede">这些说法每天自动重新查一次。结论有变化会标红{watches.some((w) => w.has_push) ? '，并推送到微信' : ''}。</p>
      {err && <p className="error">{err}</p>}
      {watches.length === 0 && (
        <p className="note box">
          还没有盯梢。查完一条说法后，在结论下面点「每天盯着这条」。
          <br />
          适合还没定论、会变化的事：召回、停运、限行、价格、上映日期……
        </p>
      )}
      {watches.map((w) => {
        const last = w.history[w.history.length - 1]
        // A change is confirmed over one or two checks, so look back for the verdict it changed from.
        const prev = [...w.history].reverse().find((h) => h.verdict !== w.verdict) ?? null
        return (
          <div key={w.id} className={`watch ${w.changed ? 'changed' : ''}`}>
            <div className="claim-head">
              <h3>{w.claim}</h3>
              <span className={`mini-stamp v-${w.verdict}`}>{LABEL[w.verdict]}</span>
            </div>
            {w.changed && prev && (
              <p className="change">
                ⚠ 结论变了：{LABEL[prev.verdict]} → {LABEL[w.verdict]}
              </p>
            )}
            {!w.changed && last && last.verdict !== w.verdict && (
              <p className="hint">最近一次复查得到「{LABEL[last.verdict]}」，把握不高，再查一次确认后才算结论变化。</p>
            )}
            {last && <p className="explain">{last.explanation}</p>}
            {last?.sources.length > 0 && (
              <ul className="watch-src">
                {last.sources.map((s) => (
                  <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> <small>{s.site}</small></li>
                ))}
              </ul>
            )}
            <ol className="timeline">
              {w.history.map((h, i) => (
                <li key={i}>
                  <span>{when(h.at)}</span>
                  <span className={`mini-stamp v-${h.verdict}`}>{LABEL[h.verdict]}</span>
                  <small>把握 {h.confidence}%</small>
                </li>
              ))}
            </ol>
            <div className="claim-actions">
              <button className="ghost small" disabled={busy === w.id} onClick={() => recheck(w)}>
                {busy === w.id ? '正在复查…' : '立即复查'}
              </button>
              {w.changed && (
                <button className="ghost small" onClick={async () => { await ackWatch(owner, w.id); replace({ ...w, changed: false }) }}>
                  知道了
                </button>
              )}
              <button className="ghost small" onClick={() => go(`/r/${w.report_id}`)}>原报告</button>
              <button
                className="ghost small danger"
                onClick={async () => { await stopWatch(owner, w.id); setWatches((ws) => ws?.filter((x) => x.id !== w.id) ?? null) }}
              >
                不盯了
              </button>
            </div>
            <p className="hint">上次检查 {when(w.last_checked)}</p>
          </div>
        )
      })}
    </section>
  )
}
