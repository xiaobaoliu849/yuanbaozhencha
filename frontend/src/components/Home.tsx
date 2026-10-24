import { useEffect, useRef, useState } from 'react'
import { LABEL, compressImage, getRecent, type RecentReport } from '../api'
import { go } from '../App'

const EXAMPLES = [
  '隔夜茶会致癌，泡过的茶放一晚上千万别喝！',
  '香蕉和红薯一起吃会中毒，赶紧转给家里人！',
  '微信从下个月起转账要收手续费了',
  '手机充电时打电话会爆炸，已经有人出事了',
]

interface Props {
  onStart: (text: string, image?: { b64: string; mime: string }) => void
  error: string
}

export default function Home({ onStart, error }: Props) {
  const [text, setText] = useState('')
  const [image, setImage] = useState<{ b64: string; mime: string; preview: string } | null>(null)
  const [imgErr, setImgErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const [canSee, setCanSee] = useState(true)
  const [recent, setRecent] = useState<RecentReport[]>([])

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((h) => setCanSee(h.images !== false))
      .catch(() => {})
    getRecent().then(setRecent).catch(() => {})
  }, [])

  async function pick(file?: File | null) {
    if (!file) return
    setImgErr('')
    try {
      setImage(await compressImage(file))
    } catch (e) {
      setImgErr(e instanceof Error ? e.message : String(e))
    }
  }

  const ready = text.trim().length > 0 || image

  return (
    <section className="home">
      <h1>
        家族群里的传言，
        <br />
        <em>查一查再转。</em>
      </h1>
      <p className="lede">
        粘贴一段话，或者丢一张聊天截图。我会把它拆成几个能查的说法，用元宝搜索多轮查证、交叉比对，
        每个结论都附上能点开的来源。证据不够，就老实说「查不到」。
      </p>

      <div
        className="input-card"
        onPaste={(e) => {
          const f = Array.from(e.clipboardData.files).find((x) => x.type.startsWith('image/'))
          if (f) pick(f)
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          pick(e.dataTransfer.files[0])
        }}
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="把要查的话粘贴到这里，比如：听说喝隔夜茶会致癌……"
          rows={5}
          maxLength={2000}
        />
        {image && (
          <div className="shot">
            <img src={image.preview} alt="截图预览" />
            <button className="ghost small" onClick={() => setImage(null)}>移除截图</button>
          </div>
        )}
        <div className="input-actions">
          <button className="ghost" disabled={!canSee} title={canSee ? '' : '暂未开启截图识别'} onClick={() => fileRef.current?.click()}>
            📷 {image ? '换一张截图' : '上传截图'}
          </button>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
          <button
            className="primary"
            disabled={!ready}
            onClick={() => onStart(text, image ? { b64: image.b64, mime: image.mime } : undefined)}
          >
            开始查证
          </button>
        </div>
        {(error || imgErr) && <p className="error">{error || imgErr}</p>}
      </div>

      <div className="examples">
        <span>试试这些：</span>
        {EXAMPLES.map((ex) => (
          <button key={ex} className="chip" onClick={() => setText(ex)}>{ex}</button>
        ))}
      </div>

      {recent.length > 0 && (
        <section className="recent">
          <h2>最近查过</h2>
          <ul>
            {recent.map((r) => (
              <li key={r.id}>
                <a href={`/r/${r.id}`} onClick={(e) => { e.preventDefault(); go(`/r/${r.id}`) }}>
                  <span className={`mini-stamp v-${r.verdict}`}>{LABEL[r.verdict]}</span>
                  <span className="recent-title">{r.headline}</span>
                  <small>{r.sources} 个来源</small>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ol className="how">
        <li><b>拆</b>一段话里往往藏着好几个说法，逐条拆开来查。</li>
        <li><b>搜</b>每条说法用元宝搜索查好几轮，换着关键词找权威来源。</li>
        <li><b>比</b>来源之间交叉比对，原文逐句核对，核对不上就不下结论。</li>
        <li><b>盯</b>还没定论的事，可以设成每天自动复查，结论变了提醒你。</li>
      </ol>
      <p className="note">不查时政和涉及个人隐私的消息。查证报告会公开展示在「最近查过」里，请不要输入个人信息。</p>
    </section>
  )
}
