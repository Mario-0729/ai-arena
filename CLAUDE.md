# AI 吵架擂台：交接文件

## 這是什麼
Mario 的個人測試專案。GitHub Actions 每小時用 Claude Code（`claude -p`）讓 Claude 一人分飾五個 AI 角色（GPT、Gemini、Grok、DeepSeek、Claude）圓桌辯論一場，結果存成 Markdown，再轉成網頁。
- 跑的是 Mario 自己 Claude Pro 訂閱的額度（金鑰由 `claude setup-token` 產生），不是 API 付費。
- 只給自己看，repo 保持 **Private**，不要改成公開。

## 使用者
- Mario 只有 iPhone，沒有電腦。需要他動手的步驟要寫成手機瀏覽器點得到的路徑。
- 回覆用繁體中文、全形標點、不用 emoji，先講結論、短一點。

## 檔案
| 路徑 | 作用 |
|---|---|
| `.github/workflows/arena.yml` | 排程（每小時第 7 分，cron 是 UTC）：開吵 → 更新 README → 轉檔 → commit → 部署網頁 |
| `.github/workflows/deploy.yml` | 改了 `site/index.html` 或 `scripts/` 推上 main 時重新部署；也能手動執行 |
| `prompt.md` | 辯論規則與角色個性。改玩法主要改這裡 |
| `debates/YYYY-MM-DD_HHMM.md` | 每場戰況（台北時間命名）。第一行 `# 辯題`，`## 第 N 回合` 分段，發言格式 `**名字**：內容`，最後 `## 主持人結算` |
| `scripts/build.py` | 把 `debates/*.md` 轉成 `site/data.json`；解析失敗的場次會帶 `raw` 原文 |
| `site/index.html` | 單檔網頁（無外部依賴）：勝場排行、場次列表、對話泡泡、上一場/下一場 |
| `site/data.json` | 轉檔產物，排程會一起 commit |
| `README.md` | **每場自動覆寫**成場次目錄，不要手寫內容在這裡 |

## Secrets（repo → Settings → Secrets and variables → Actions）
| 名稱 | 狀態 | 說明 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | 已設定、2026-11-26 實測可用 | `claude setup-token` 產生，效期約一年（約 2027-11 到期）。到期或外流就重產並覆蓋；撤銷在 claude.ai 設定 |
| `CLOUDFLARE_API_TOKEN` | **未設定** | 沒設就自動跳過部署，不會讓排程失敗 |
| `CLOUDFLARE_ACCOUNT_ID` | **未設定** | 同上 |

金鑰一律不要印在 log、檔案或對話裡。

## 目前狀態（2026-11-26）
- 排程已上線，第一場（火鍋一人一鍋，DeepSeek 勝）跑成功，一場約 45 秒。
- 網頁已完成並在本機用手機尺寸檢查過，**還沒上線**：缺 Cloudflare 兩個 secret。

## 下一步：讓網頁上線（Cloudflare Pages，免費）
用 wrangler 直接上傳（Direct Upload），不走 Cloudflare 的 Git 整合，因為 Git 整合免費方案每月只有 500 次建置，每小時一場會超過。
1. Mario 用手機到 https://dash.cloudflare.com/profile/api-tokens → Create Token → 「Edit Cloudflare Workers」範本（含 Pages 權限）或自訂權限 `Account → Cloudflare Pages → Edit` → 建立後複製。
2. 帳戶 ID：Cloudflare 後台首頁右側或 Workers & Pages 頁面的 Account ID。
3. 兩個值存成上表的 secrets。
4. Actions → 部署網頁 → Run workflow。第一次會自動建立名為 `ai-arena` 的 Pages 專案，網址是 `https://ai-arena.pages.dev`（名稱被占用時 Cloudflare 會加後綴，以部署 log 為準）。
5. 網址雖然沒公開，但拿到連結的人都看得到。想只給自己看，可以在 Cloudflare Zero Trust → Access 幫這個網址加 Email 驗證（免費 50 人內）。

## 限制與成本
- GitHub Actions：Private repo 每月 2,000 分鐘免費。目前每場約 1 分鐘（計費會無條件進位），每月約 720 分鐘；加上部署大約翻倍，仍在額度內。調高頻率前先算。
- Claude 額度：每場都扣 Mario 的 Pro 用量。他自己用 Claude 撞到上限時，可以到 Actions → AI 吵架擂台 → ⋯ → Disable workflow 暫停。
- GitHub 排程常延遲幾分鐘到十幾分鐘，屬正常。

## 之前試過、放棄的路線（不要重做）
- Cloudflare Worker + OpenRouter 付費多模型版、Workers AI 免費多模型版：做好了但 Mario 要用自己的 Claude 額度，所以改走這條。
- Claude Code 排程任務（Routines）：Pro 每天只能跑 5 次，太少。
- Artifact 網頁版：頁面要一直開著才會跑。

## 可以延續的點子
- 讓網友投票誰贏（需要後端，例如 Cloudflare Worker + D1）
- 每場自動產生短影音腳本或 Threads 貼文
- 題目來源改成每日時事
