import type { LiveEvent, Verdict } from '../api'
import { LABEL } from '../api'

interface ClaimLive {
  claim: string
  log: { round: number; text: string; kind: 'search' | 'judge' | 'round' | 'error' }[]
  verdict?: Verdict
  confidence?: number
  done: boolean
}

export interface LiveState {
  step: string
  readable: string
  claims: ClaimLive[]
  searches: number
}

export const emptyLive = (): LiveState => ({ step: '准备开始…', readable: '', claims: [], searches: 0 })

export function reduceLive(s: LiveState, e: LiveEvent): LiveState {
  const claims = s.claims.map((c) => ({ ...c, log: [...c.log] }))
  const at = (i: number) => claims[i] ?? (claims[i] = { claim: '', log: [], done: false })
  switch (e.type) {
    case 'step':
      return { ...s, step: e.text }
    case 'plan':
      return { ...s, readable: e.readable_text, claims: e.claims.map((c) => ({ claim: c.claim, log: [], done: false })) }
    case 'search':
      at(e.claim).log.push({
        round: e.round,
        kind: e.error ? 'error' : 'search',
        text: e.error ? `搜「${e.query}」失败` : `搜「${e.query}」→ ${e.found} 条结果${e.new < e.found ? `（新 ${e.new}）` : ''}`,
      })
      return { ...s, claims, searches: s.searches + 1 }
    case 'judging':
      at(e.claim).log.push({ round: e.round, kind: 'judge', text: `比对 ${e.sources} 个来源…` })
      return { ...s, claims }
    case 'round': {
      const c = at(e.claim)
      c.log.push({ round: e.round, kind: 'round', text: `第 ${e.round} 轮结论：${LABEL[e.verdict]}（把握 ${e.confidence}%）` })
      c.verdict = e.verdict
      c.confidence = e.confidence
      return { ...s, claims }
    }
    case 'claim':
      at(e.claim).done = true
      return { ...s, claims }
    default:
      return s
  }
}

export default function Live({ state }: { state: LiveState }) {
  return (
    <section className="live">
      <div className="live-head">
        <span className="spinner" />
        <div>
          <h2>正在调查</h2>
          <p>{state.step}</p>
        </div>
        <span className="counter">已搜索 {state.searches} 次</span>
      </div>
      {state.readable && (
        <blockquote className="readable">
          <small>要查的内容</small>
          {state.readable}
        </blockquote>
      )}
      {state.claims.map((c, i) => (
        <div key={i} className={`live-claim ${c.done ? 'done' : ''}`}>
          <div className="live-claim-head">
            <span className="num">{i + 1}</span>
            <span className="claim-text">{c.claim}</span>
            {c.done && c.verdict && <span className={`mini-stamp v-${c.verdict}`}>{LABEL[c.verdict]}</span>}
          </div>
          <ul>
            {c.log.map((l, j) => (
              <li key={j} className={`log-${l.kind}`}>
                <span className="r">R{l.round}</span>
                {l.text}
              </li>
            ))}
            {!c.done && <li className="log-wait">…</li>}
          </ul>
        </div>
      ))}
    </section>
  )
}
