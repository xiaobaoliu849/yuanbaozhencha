export type Verdict = 'true' | 'false' | 'mixed' | 'unknown'

export const LABEL: Record<Verdict, string> = { true: '属实', false: '不实', mixed: '部分属实', unknown: '查不到' }

export interface Source {
  id: string
  title: string
  url: string
  site: string
  date: string
  passage: string
  favicon: string
  queries: string[]
  cited: boolean
}

export interface Evidence {
  source: string
  quote: string
  stance: 'support' | 'refute' | 'context'
  quote_found: boolean
}

export interface Round {
  round: number
  searches: { query: string; found: number; new: number; sources: string[]; error: string | null }[]
  verdict: Verdict
  confidence: number
  note: string
}

export interface ClaimResult {
  index: number
  claim: string
  verdict: Verdict
  verdict_label: string
  confidence: number
  explanation: string
  conflicts: string
  evidence: Evidence[]
  guard: string
  chain: Round[]
  searched: string[]
  checked_at: string
}

export interface Report {
  id: string
  title: string
  input_text: string
  readable_text: string
  had_image: boolean
  created_at: string
  claims: ClaimResult[]
  sources: Source[]
  headline: string
  family_message: string
  verdict: Verdict
  verdict_label: string
  off_limits: boolean
  off_limits_reason: string
}

export type LiveEvent =
  | { type: 'step'; text: string }
  | { type: 'plan'; title: string; readable_text: string; off_limits: boolean; claims: { claim: string; queries: string[] }[] }
  | { type: 'search'; claim: number; round: number; query: string; found: number; new: number; error: string | null }
  | { type: 'judging'; claim: number; round: number; sources: number }
  | { type: 'round'; claim: number; round: number; verdict: Verdict; confidence: number }
  | { type: 'claim'; claim: number; result: ClaimResult }
  | { type: 'done'; report: Report }
  | { type: 'error'; message: string }

export interface WatchCheck {
  at: string
  verdict: Verdict
  confidence: number
  explanation: string
  sources: { title: string; url: string; site: string; date: string }[]
}

export interface Watch {
  id: string
  report_id: string
  claim: string
  created_at: string
  last_checked: string
  verdict: Verdict
  changed: boolean
  has_push: boolean
  history: WatchCheck[]
  just_changed?: boolean
  previous_verdict?: Verdict
}

async function errorText(r: Response): Promise<string> {
  try {
    const j = await r.json()
    return typeof j.detail === 'string' ? j.detail : `出错了（${r.status}）`
  } catch {
    return `出错了（${r.status}）`
  }
}

export async function investigate(
  body: { text: string; image_b64?: string; image_mime?: string },
  onEvent: (e: LiveEvent) => void,
): Promise<void> {
  const r = await fetch('/api/investigate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok || !r.body) throw new Error(await errorText(r))
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf))
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getReport = (id: string) => json<Report>(`/api/reports/${encodeURIComponent(id)}`)
export const listWatches = (owner: string) => json<Watch[]>(`/api/watches?owner=${encodeURIComponent(owner)}`)
export const addWatch = (owner: string, report_id: string, claim_index: number, push_token: string) =>
  json<Watch>('/api/watches', post({ owner, report_id, claim_index, push_token }))
export const recheckWatch = (owner: string, id: string) => json<Watch>(`/api/watches/${id}/recheck`, post({ owner }))
export const ackWatch = (owner: string, id: string) => json<{ ok: boolean }>(`/api/watches/${id}/ack`, post({ owner }))
export const stopWatch = (owner: string, id: string) => json<{ ok: boolean }>(`/api/watches/${id}/stop`, post({ owner }))

export function ownerId(): string {
  try {
    let id = localStorage.getItem('chade-owner')
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem('chade-owner', id)
    }
    return id
  } catch {
    return 'anon-' + Math.random().toString(36).slice(2, 12)
  }
}

/** Shrink a screenshot to at most 1600px on its long side and return base64 JPEG (no data: prefix). */
export function compressImage(file: File): Promise<{ b64: string; mime: string; preview: string }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height))
      const c = document.createElement('canvas')
      c.width = Math.round(img.width * scale)
      c.height = Math.round(img.height * scale)
      c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
      const preview = c.toDataURL('image/jpeg', 0.85)
      URL.revokeObjectURL(url)
      resolve({ b64: preview.split(',')[1], mime: 'image/jpeg', preview })
    }
    img.onerror = () => reject(new Error('图片读不出来，换一张试试'))
    img.src = url
  })
}
