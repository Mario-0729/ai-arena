# AI 吵架擂台：交接文件

## 這是什麼
Mario 的個人測試專案。Mario 在網頁上出辯題、按開始，GitHub Actions 用 Claude Code（`claude -p`）讓 Claude 分成正方、反方自己跟自己辯論，一回合接一回合打，最後由主持人（也是 Claude）結算。網頁上可以暫停、繼續、結束。
- 2026-11-26 起改成這個玩法。之前是每小時自動出題、一人分飾五個 AI（GPT、Gemini、Grok、DeepSeek、Claude），舊場次保留在 `debates/`，網頁照樣能看。
- 跑的是 Mario 自己 Claude Pro 訂閱的額度（金鑰由 `claude setup-token` 產生），不是 API 付費。
- 只給自己看，repo 保持 **Private**，不要改成公開。

## 使用者
- Mario 只有 iPhone，沒有電腦。需要他動手的步驟要寫成手機瀏覽器點得到的路徑。
- 回覆用繁體中文、全形標點、不用 emoji，先講結論、短一點。

## 檔案
| 路徑 | 作用 |
|---|---|
| `.github/workflows/arena.yml` | 只由網頁（或手動 Run workflow）觸發，每次只做一步：打一回合或結算 → 轉檔 → commit → 部署 → 還要繼續就自己再觸發一次。已沒有每小時排程 |
| `.github/workflows/deploy.yml` | 改了 `site/index.html` 或 `scripts/` 推上 main 時重新部署；也能手動執行 |
| `control.json` | **只由網頁寫入**：`{"id","topic","cmd":"run/pause/end","max"}`，指定目前這場和指令 |
| `prompt.md` | 正方、反方、主持人的規則。改玩法主要改這裡 |
| `scripts/step.py` | 讀 control.json 決定這一步：`plan` 印出 round/verdict/close/none，`run` 執行（會呼叫 claude）。回合標題由程式寫，Claude 只寫內容 |
| `debates/YYYY-MM-DD_HHMMSS.md` | 每場戰況（台北時間命名，id 由網頁按開始時產生）。第一行 `# 辯題`，`## 第 N 回合` 分段，發言格式 `**正方**：內容`，最後 `## 主持人結算`，第一行「勝者：正方／反方／平手」 |
| `scripts/build.py` | 把 `debates/*.md` 轉成 `site/data.json`（含每場狀態和目前這場 `live`），並重寫 README；解析失敗的場次會帶 `raw` 原文 |
| `site/index.html` | 單檔網頁（無外部依賴）：控制台（出題、開始、暫停、繼續、結束）、場次列表、對話泡泡。進行中每 15 秒自動更新 |
| `site/data.json` | 轉檔產物，排程會一起 commit |
| `README.md` | **每場自動覆寫**成場次目錄，不要手寫內容在這裡 |

## 網頁怎麼控制
- 網頁本身是靜態的，沒有後端。按鈕用 Mario 存在自己手機瀏覽器（localStorage）的 GitHub 權杖，直接呼叫 GitHub API：改 `control.json`，再觸發 `arena.yml`。
- 權杖是 fine-grained personal access token，只選這個 repo，權限 Contents、Actions 都是 Read and write。建立網址：https://github.com/settings/personal-access-tokens/new 。過期就重建，貼到網頁「換權杖」。
- 沒有權杖的人打開網址只能看，不能按。
- 暫停只是改 control.json，正在打的回合會打完才停。打到一半當掉（例如 Claude 額度用完），狀態會卡在「進行中」，按暫停再按繼續就會重新觸發。
- 每回合約 1 到 3 分鐘（GitHub 排隊、裝 Claude Code、Claude 思考、部署）。回合上限網頁可選 3／5／10／20，程式上限 30。

## Secrets（repo → Settings → Secrets and variables → Actions）
| 名稱 | 狀態 | 說明 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | 已設定、2026-11-26 實測可用 | `claude setup-token` 產生，效期約一年（約 2027-11 到期）。到期或外流就重產並覆蓋；撤銷在 claude.ai 設定 |
| `CLOUDFLARE_API_TOKEN` | **未設定** | 沒設就自動跳過部署，不會讓排程失敗 |
| `CLOUDFLARE_ACCOUNT_ID` | **未設定** | 同上 |

金鑰一律不要印在 log、檔案或對話裡。

## 目前狀態（2026-11-26）
- 舊玩法第一場（火鍋一人一鍋，DeepSeek 勝）跑成功。
- 新玩法（網頁出題、正反方、開始／暫停／結束）已完成，用假的 claude 模擬整場流程、用手機尺寸和模擬的 GitHub API 測過網頁。還沒在真的 Actions 上跑過。
- 網頁**還沒上線**：缺 Cloudflare 兩個 secret。Mario 也還沒建 GitHub 權杖。

## 下一步：讓網頁上線（Cloudflare Pages，免費）
用 wrangler 直接上傳（Direct Upload），不走 Cloudflare 的 Git 整合，因為 Git 整合免費方案每月只有 500 次建置，每小時一場會超過。
1. Mario 用手機到 https://dash.cloudflare.com/profile/api-tokens → Create Token → 「Edit Cloudflare Workers」範本（含 Pages 權限）或自訂權限 `Account → Cloudflare Pages → Edit` → 建立後複製。
2. 帳戶 ID：Cloudflare 後台首頁右側或 Workers & Pages 頁面的 Account ID。
3. 兩個值存成上表的 secrets。
4. Actions → 部署網頁 → Run workflow。第一次會自動建立名為 `ai-arena` 的 Pages 專案，網址是 `https://ai-arena.pages.dev`（名稱被占用時 Cloudflare 會加後綴，以部署 log 為準）。
5. 網址雖然沒公開，但拿到連結的人都看得到。想只給自己看，可以在 Cloudflare Zero Trust → Access 幫這個網址加 Email 驗證（免費 50 人內）。

## 限制與成本
- GitHub Actions：Private repo 每月 2,000 分鐘免費。每回合是一次執行，約 1 到 2 分鐘（計費無條件進位）。打一場 10 回合加結算約 15 到 25 分鐘，一個月大約可以打 80 到 100 場這種長度的。
- Claude 額度：每回合、每次結算各呼叫一次 Claude，都扣 Mario 的 Pro 用量。只在他按開始時才跑。
- GitHub 排程常延遲幾分鐘到十幾分鐘，屬正常。

## 之前試過、放棄的路線（不要重做）
- Cloudflare Worker + OpenRouter 付費多模型版、Workers AI 免費多模型版：做好了但 Mario 要用自己的 Claude 額度，所以改走這條。
- Claude Code 排程任務（Routines）：Pro 每天只能跑 5 次，太少。
- Artifact 網頁版：頁面要一直開著才會跑。
- 每小時自動出題、一人分飾五個 AI：2026-11-26 Mario 改成自己出題、Claude 自己跟自己辯。

## 可以延續的點子
- 讓網友投票誰贏（需要後端，例如 Cloudflare Worker + D1）
- 每場自動產生短影音腳本或 Threads 貼文
- 題目來源改成每日時事
- 結算後的勝場統計（正方／反方／平手）
