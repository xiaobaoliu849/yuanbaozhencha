# 查得到，信得过

> 家族群里的传言，查一查再转。

WaytoAGI 1024 超能 Coding 周末 · 侦探赛道作品。粘贴一段话，或者丢一张聊天截图，它会：

1. **拆**：把一段传言拆成几条能独立查证的说法（截图先识别文字）。
2. **搜**：每条说法用 **元宝搜索** 查好几轮，第一轮没定论就换关键词再搜，最多三轮。
3. **比**：AI 只能依据搜到的网页下结论，每个判断都要引用来源编号和原文摘句。
4. **核**：后端逐句核对引用的原文是否真的出现在搜到的网页里；引用不存在的来源会被丢掉，核对不上就强制改判「查不到」。
5. **报**：生成可分享的证据链报告，附一段能直接发回家族群的话。
6. **盯**：会变化的说法（召回、停运、限行、上映日期……）可以设成每天自动复查，结论变了标红，填 PushPlus token 还能推送到微信。

去掉元宝搜索，这个作品就没有任何结论可给。

## 结构

```
backend/
  main.py                 FastAPI：调查（NDJSON 流式）、报告、盯梢、定时复查、托管前端
  services/yuanbao.py     元宝搜索（腾讯云 SearchPro）客户端
  services/investigate.py 拆解 → 多轮搜索 → 判断 → 引用核对 → 汇总
  services/store.py       SQLite（报告、盯梢）
  services/notify.py      结论变化提醒（PushPlus / Webhook）
  services/llm.py         大模型：OpenAI 兼容接口（Toklens 的 DeepSeek / GLM）或 Gemini
  services/gemini.py      Gemini（可选，用来看截图）
frontend/                 React + Vite，手机优先
.github/workflows/watch.yml  每天叫醒服务复查盯梢
```

## 本地运行

Windows 双击 `run_local.bat`，macOS / Linux 运行 `./run_local.sh`。第一次会生成 `.env`，填入：

- `YUANBAO_API_KEY`：腾讯云控制台 → 元宝搜索 → API KEY（先用邀请码核销领额度）
- `LLM_API_KEY`：Toklens（或任何 OpenAI 兼容接口）的 Key，接口地址填 `LLM_BASE_URL`
- `GEMINI_API_KEY`（可选）：填了才能识别截图，也可以改填能看图的 `LLM_VISION_MODEL`

然后打开 http://localhost:8000 。

## 部署

用 Toklens 香港节点时国内外服务器都行；用 Gemini 看截图则需要境外服务器。数据存在 SQLite，路径由 `DATA_DIR` 决定（Docker 里默认 `/data`）。

- **Railway（推荐）**：New Project → Deploy from GitHub repo，自动识别 Dockerfile；加一个 Volume 挂到 `/data`，填环境变量 `YUANBAO_API_KEY`、`LLM_API_KEY`、`LLM_BASE_URL`、`GEMINI_API_KEY`（可选）、`CRON_TOKEN`、`PUBLIC_URL`。报告链接和盯梢在重启后都还在。
- **Render**：用 `render.yaml` 一键部署。免费实例休眠重启后本地文件会清空，分享出去的报告链接会失效，适合演示。

持续盯梢：服务在运行时每小时检查一次到期的盯梢；免费主机会休眠，所以再在 GitHub 仓库 Secrets 里加 `APP_URL` 和 `CRON_TOKEN`，`daily-watch` 工作流每天北京时间 8 点叫醒服务并复查。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `YUANBAO_API_KEY` | 元宝搜索 API Key（也认 `TENCENTCLOUD_WSA_APIKEY`） |
| `LLM_API_KEY` | OpenAI 兼容接口的 Key（不填则全用 Gemini） |
| `LLM_BASE_URL` | 接口地址，默认 `https://hkg.toklens.ai/v1` |
| `LLM_MODEL` | 模型名；不填自动选第一个 DeepSeek 模型，可用模型见 `/api/models` |
| `LLM_VISION_MODEL` | 能看图的模型名，用于截图识别（没有 Gemini 时） |
| `GEMINI_API_KEY` | 可选，用来识别截图 |
| `PUBLIC_URL` | 对外地址，用于提醒里的报告链接 |
| `CRON_TOKEN` | `/api/cron` 的口令 |
| `WATCH_INTERVAL_HOURS` | 盯梢复查间隔，默认 24 |
| `DAILY_LIMIT` | 每个 IP 每天最多查几次，默认 40 |
| `ALERT_WEBHOOK_URL` | 可选，结论变化时 POST 一份 JSON |
| `YUANBAO_EXTRA` | 可选，追加到搜索请求体的 JSON，如 `{"Cnt": 10}` |

不查时政和涉及个人隐私的消息。
