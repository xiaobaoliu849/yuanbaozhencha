import { useEffect, useState } from 'react'
import { investigate, listWatches, ownerId, type LiveEvent, type Report } from './api'
import Home from './components/Home'
import Live, { type LiveState, reduceLive, emptyLive } from './components/Live'
import ReportView from './components/ReportView'
import Watches from './components/Watches'

type Route = { page: 'home' } | { page: 'report'; id: string } | { page: 'watch' }

function parse(path: string): Route {
  const m = path.match(/^\/r\/([\w-]+)/)
  if (m) return { page: 'report', id: m[1] }
  if (path.startsWith('/watch')) return { page: 'watch' }
  return { page: 'home' }
}

export function go(path: string) {
  history.pushState(null, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo(0, 0)
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parse(location.pathname))
  const [live, setLive] = useState<LiveState | null>(null)
  const [fresh, setFresh] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [alerts, setAlerts] = useState(0)

  useEffect(() => {
    const on = () => setRoute(parse(location.pathname))
    window.addEventListener('popstate', on)
    return () => window.removeEventListener('popstate', on)
  }, [])

  useEffect(() => {
    listWatches(ownerId())
      .then((ws) => setAlerts(ws.filter((w) => w.changed).length))
      .catch(() => {})
  }, [route])

  async function start(text: string, image?: { b64: string; mime: string }) {
    setError('')
    setLive(emptyLive())
    let ended = false
    try {
      await investigate({ text, image_b64: image?.b64, image_mime: image?.mime }, (e: LiveEvent) => {
        if (e.type === 'done' || e.type === 'error') ended = true
        if (e.type === 'done') {
          setFresh(e.report)
          setLive(null)
          go(`/r/${e.report.id}`)
        } else if (e.type === 'error') {
          setError(e.message)
          setLive(null)
        } else {
          setLive((s) => reduceLive(s ?? emptyLive(), e))
        }
      })
      // The stream closed without a verdict (network drop, server restart): don't leave the spinner up.
      if (!ended) {
        setError('连接中断了，调查没有完成，请再试一次')
        setLive(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setLive(null)
    }
  }

  return (
    <div className="app">
      <header className="top">
        <a className="brand" href="/" onClick={(e) => { e.preventDefault(); go('/') }}>
          <img src="/favicon.svg" alt="" />
          <span>查得到，信得过</span>
        </a>
        <a className="watch-link" href="/watch" onClick={(e) => { e.preventDefault(); go('/watch') }}>
          我的盯梢{alerts > 0 && <b className="dot">{alerts}</b>}
        </a>
      </header>

      <main>
        {live ? (
          <Live state={live} />
        ) : route.page === 'report' ? (
          <ReportView id={route.id} initial={fresh?.id === route.id ? fresh : null} />
        ) : route.page === 'watch' ? (
          <Watches onCount={setAlerts} />
        ) : (
          <Home onStart={start} error={error} />
        )}
      </main>

      <footer className="foot">
        搜索由 <b>元宝搜索</b> 提供 · 只信能点开的来源
        <br />
        WaytoAGI 1024 超能 Coding 周末 · 侦探赛道
      </footer>
    </div>
  )
}
