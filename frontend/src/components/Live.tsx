import { useEffect, useState } from 'react'
import type { LiveEvent, SourceCard, Verdict } from '../api'
import { LABEL } from '../api'

type Entry =
  | { kind: 'search'; round: number; query: string; status: 'running' | 'done' | 'error'; found?: number; fresh?: number }
  | { kind: 'why'; round: number; text: string }
  | { kind: 'judge'; round: number; sources: number; done: boolean }
  | { kind: 'verdict'; round: number; verdict: Verdict; confidence: number; note: string; evidence: number; verified: number; guard: boolean }

interface ClaimLive {
  claim: string
  queries: string[]
  entries: Entry[]
  cards: SourceCard[]
  verdict?: Verdict
  done: boolean
}

export interface LiveState {
  step: string
  stage: 'plan' | 'search' | 'summary'
  readable: string
  claims: ClaimLive[]
  searches: number
  sources: number
  startedAt: number
}

export const emptyLive = (): LiveState => ({
  step: '准备开始…', stage: 'plan', readable: '', claims: [], searches: 0, sources: 0, startedAt: Date.now(),
})

export function reduceLive(s: LiveState, e: LiveEvent): LiveState {
  const claims = s.claims.map((c) => ({ ...c, entries: [...c.entries], cards: [...c.cards] }))
  const at = (i: number) => claims[i] ?? (claims[i] = { claim: '', queries: [], entries: [], cards: [], done: false })
  switch (e.type) {
    case 'step':
      return { ...s, step: e.text, stage: e.stage ?? s.stage }
    case 'plan':
      return {
        ...s,
        readable: e.readable_text,
        claims: e.claims.map((c) => ({ claim: c.claim, queries: c.queries, entries: [], cards: [], done: false })),
      }
    case 'searching': {
      const c = at(e.claim)
      if (e.why) c.entries.push({ kind: 'why', round: e.round, text: e.why })
      for (const q of e.queries) c.entries.push({ kind: 'search', round: e.round, query: q, status: 'running' })
      return { ...s, claims }
    }
    case 'search': {
      const c = at(e.claim)
      const i = c.entries.findIndex((x) => x.kind === 'search' && x.query === e.query && x.status === 'running')
      const done: Entry = { kind: 'search', round: e.round, query: e.query, status: e.error ? 'error' : 'done', found: e.found, fresh: e.new }
      if (i >= 0) c.entries[i] = done
      else c.entries.push(done)
      c.cards.unshift(...(e.sources ?? []))
      return { ...s, claims, searches: s.searches + 1, sources: s.sources + (e.sources?.length ?? 0) }
    }
    case 'judging':
      at(e.claim).entries.push({ kind: 'judge', round: e.round, sources: e.sources, done: false })
      return { ...s, claims }
    case 'round': {
      const c = at(e.claim)
      c.entries = c.entries.map((x) => (x.kind === 'judge' && x.round === e.round ? { ...x, done: true } : x))
      c.entries.push({
        kind: 'verdict', round: e.round, verdict: e.verdict, confidence: e.confidence, note: e.note,
        evidence: e.evidence, verified: e.verified, guard: e.guard,
      })
      c.verdict = e.verdict
      return { ...s, claims }
    }
    case 'claim':
      at(e.claim).done = true
      return { ...s, claims }
    default:
      return s
  }
}

const STAGES = ['读题拆解', '元宝搜索', '比对判断', '原文核对', '写结论']

function stageIndex(s: LiveState): number {
  if (s.stage === 'summary') return 4
  if (!s.claims.length) return 0
  // Show what the investigation is busy with right now, across the claims still open.
  const open = s.claims.filter((c) => !c.done).flatMap((c) => c.entries)
  if (!open.length) return 3
  if (open.some((x) => x.kind === 'search' && x.status === 'running')) return 1
  if (open.some((x) => x.kind === 'judge' && !x.done)) return 2
  return 3
}

export default function Live({ state }: { state: LiveState }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [])
  const secs = Math.floor((now - state.startedAt) / 1000)
  const cur = stageIndex(state)

  return (
    <section className="live">
      <div className="live-head">
        <span className="spinner" />
        <div>
          <h2>正在调查</h2>
          <p>{state.step}</p>
        </div>
        <span className="timer">{secs}s</span>
      </div>

      <ol className="stepper">
        {STAGES.map((name, i) => (
          <li key={name} className={i < cur ? 'done' : i === cur ? 'now' : ''}>
            <span className="dot">{i < cur ? '✓' : i + 1}</span>
            <small>{name}</small>
          </li>
        ))}
      </ol>

      <div className="live-stats">
        <span>已搜索 <b>{state.searches}</b> 次</span>
        <span>找到 <b>{state.sources}</b> 个网页</span>
        <span>{state.claims.filter((c) => c.done).length}/{state.claims.length || '?'} 条查完</span>
      </div>

      {state.readable ? (
        <blockquote className="readable">
          <small>要查的内容</small>
          {state.readable}
        </blockquote>
      ) : (
        <div className="thinking">
          <span className="skeleton" />
          <span className="skeleton short" />
          <p>AI 在读你给的内容，找出里面哪些话能查证…</p>
        </div>
      )}

      {state.claims.map((c, i) => (
        <div key={i} className={`live-claim ${c.done ? 'done' : ''}`}>
          <div className="live-claim-head">
            <span className="num">{i + 1}</span>
            <span className="claim-text">{c.claim}</span>
            {c.done && c.verdict ? (
              <span className={`mini-stamp v-${c.verdict}`}>{LABEL[c.verdict]}</span>
            ) : (
              <span className="mini-spin" />
            )}
          </div>
          {c.entries.length === 0 && c.queries.length > 0 && (
            <p className="plan-q">准备搜索：{c.queries.map((q) => `「${q}」`).join('、')}</p>
          )}
          <ul className="log">
            {c.entries.map((x, j) => (
              <LogLine key={j} x={x} />
            ))}
          </ul>
          {c.cards.length > 0 && (
            <div className="cards">
              {c.cards.map((s) => (
                <a key={s.id} className={`card tier-${s.tier}`} href={s.url} target="_blank" rel="noreferrer">
                  <span className="tier">{s.tier_label}</span>
                  <span className="card-title">{s.title}</span>
                  <small>{s.site}{s.date && ` · ${s.date.slice(0, 10)}`}</small>
                </a>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}

function LogLine({ x }: { x: Entry }) {
  const r = <span className="r">第{x.round}轮</span>
  switch (x.kind) {
    case 'why':
      return <li className="log-why">{r}↻ {x.text}</li>
    case 'search':
      return (
        <li className={`log-search ${x.status}`}>
          {r}
          {x.status === 'running' ? <span className="mini-spin" /> : x.status === 'error' ? '✕' : '🔍'} 元宝搜索「{x.query}」
          {x.status === 'done' && <em> → {x.found} 条结果{x.fresh !== undefined && x.fresh < (x.found ?? 0) ? `，新 ${x.fresh} 条` : ''}</em>}
          {x.status === 'error' && <em> 搜索失败</em>}
        </li>
      )
    case 'judge':
      return (
        <li className="log-judge">
          {r}
          {x.done ? '⚖️' : <span className="mini-spin" />} AI 阅读 {x.sources} 个网页，交叉比对{x.done ? '' : '中…'}
        </li>
      )
    case 'verdict':
      return (
        <li className="log-verdict">
          {r}
          <span>
            {x.evidence ? `✅ 原文核对：${x.verified}/${x.evidence} 句在网页里找到` : '✅ 原文核对：没有能引用的原文'}
            {x.guard && <b className="guard-tag"> 核对不上，改判查不到</b>}
            <br />
            → <span className={`mini-stamp v-${x.verdict}`}>{LABEL[x.verdict]}</span> 把握 {x.confidence}%
            {x.note && <span className="note-line">{x.note}</span>}
          </span>
        </li>
      )
  }
}
