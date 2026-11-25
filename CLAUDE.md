# AI 吵架擂台：交接文件

## 這是什麼
Mario 的個人測試專案。Mario 在網頁上出辯題、按開始，GitHub Actions 用 Claude Code（`claude -p`）讓 Claude 分成正方、反方自己跟自己辯論，一段一段輪流講（每一步只有一個人發言），最後由主持人（也是 Claude）結算。網頁上可以暫停、繼續、結束；回合上限可選 3／5／10／20 或無限（按結束才停）。可以一次貼很多題（一行一題），最多 20 場同時打，每場各用一台 GitHub 機器。
- 2026-11-26 起改成這個玩法。之前是每小時自動出題、一人分飾五個 AI（GPT、Gemini、Grok、DeepSeek、Claude），舊場次保留在 `debates/`，網頁照樣能看。
- 跑的是 Mario 自己 Claude Pro 訂閱的額度（金鑰由 `claude setup-token` 產生），不是 API 付費。
- repo 是 **Public**（2026-11-26 Mario 決定改公開，為了免費用 GitHub Pages 放網頁）。所以 repo 內容、Actions log 大家都看得到：不要把金鑰、個資寫進檔案或印在 log。

## 使用者
- Mario 只有 iPhone，沒有電腦。需要他動手的步驟要寫成手機瀏覽器點得到的路徑。
- 回覆用繁體中文、全形標點、不用 emoji，先講結論、短一點。

## 檔案
| 路徑 | 作用 |
|---|---|
| `.github/workflows/arena.yml` | 只由網頁（或手動 Run workflow，要填場次 id）觸發，輸入 `id`。每次只做一步：正方或反方講一段、或結算 → 只 commit 這場自己的檔案 → 觸發「部署網頁」→ 還要繼續就帶同一個 id 再觸發自己。concurrency 用 `arena-<id>` 分開，所以各場平行、同一場依序。執行名稱是「擂台 <id>」，網頁靠它對應每場的執行狀態 |
| `.github/workflows/deploy.yml` | `build` 工作：跑 build.py、commit `site/data.json` 和 README（只有這裡寫這兩個檔），上傳；`deploy` 工作：部署到 GitHub Pages。兩個工作各自排隊、排隊中的被新的取代。辯論每步、改了 `site/index.html` 或 `scripts/` 推上 main、或手動都會跑 |
| `controls/<id>.json` | **只由網頁寫入**，一場一個：`{"id","topic","cmd":"run/pause/end","max"}`。`max` 為 0 代表無限。id 是台北時間 `YYYY-MM-DD_HHMMSS`，一次開多題時加 `-1`、`-2`… |
| `quota/<id>.json` | 每場各存 Claude Code（`--output-format stream-json`）回報的 `rate_limit_event.rate_limit_info`（狀態、5 小時／7 天用量比例、重置時間）。build.py 取 `at` 最新的一份 |
| `prompt.md` | 正方、反方、主持人的規則。改玩法主要改這裡 |
| `scripts/step.py` | 讀 `controls/<id>.json` 決定這一步：`plan <id>` 印出 pro/con/verdict/close/none，`run <id>` 執行（會呼叫 claude）。回合標題和名字由程式寫，Claude 只寫內容。發言時只給最近 6 回合，結算時給全文（太長會截中間）。無限模式打到 200 回合會自動結算當保險 |
| `debates/YYYY-MM-DD_HHMMSS.md` | 每場戰況（台北時間命名，id 由網頁按開始時產生）。第一行 `# 辯題`，`## 第 N 回合` 分段，發言格式 `**正方**：內容`，最後 `## 主持人結算`，第一行「勝者：正方／反方／平手」 |
| `scripts/build.py` | 把 `debates/*.md` 轉成 `site/data.json`（含每場狀態、還沒結束的場次 `live` 陣列、額度 `quota`），並重寫 README；解析失敗的場次會帶 `raw` 原文 |
| `site/index.html` | 單檔網頁（無外部依賴）：出題（一行一題）、每場進行中的卡片（狀態、最新發言、暫停／繼續／結束）、Claude 額度、場次列表、對話泡泡。進行中每 10 秒自動更新 |
| `site/data.json` | 轉檔產物，只由 deploy.yml 的 build 工作 commit |
| `README.md` | **每場自動覆寫**成場次目錄，不要手寫內容在這裡 |

## 網頁怎麼控制
- 網頁本身是靜態的，沒有後端。按鈕用 Mario 存在自己手機瀏覽器（localStorage）的 GitHub 權杖，直接呼叫 GitHub API：改 `controls/<id>.json`，再帶 id 觸發 `arena.yml`。
- 權杖是 fine-grained personal access token，只選這個 repo，權限 Contents、Actions 都是 Read and write。建立網址：https://github.com/settings/personal-access-tokens/new 。過期就重建，貼到網頁「換權杖」。
- 有權杖時，網頁直接從 GitHub API 讀 `site/data.json` 和最近 50 次 arena 執行，每 10 秒一次（2 個請求），所以 build 工作一 commit 就看得到，不用等部署；按了按鈕到資料跟上之前，網頁先照按的顯示（最多 3 分鐘）；也會顯示排隊中、誰在想、上一步失敗（附連結）。
- 沒有權杖的人打開網址只能看，不能按，資料來自網站上的 data.json（要等部署）。
- 暫停只是改 control.json，正在打的回合會打完才停。打到一半當掉（例如 Claude 額度用完），狀態會卡在「進行中」，按暫停再按繼續就會重新觸發。
- 實測每段發言約 20 到 40 秒（GitHub 排隊、裝 Claude Code、Claude 思考）。回合上限網頁可選 3／5／10／20／無限，有上限時程式最多 30。

## Secrets（repo → Settings → Secrets and variables → Actions）
| 名稱 | 狀態 | 說明 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | 已設定、2026-11-26 實測可用 | `claude setup-token` 產生，效期約一年（約 2027-11 到期）。到期或外流就重產並覆蓋；撤銷在 claude.ai 設定 |

金鑰一律不要印在 log、檔案或對話裡。

## 目前狀態（2026-11-26）
- 舊玩法第一場（火鍋一人一鍋，DeepSeek 勝）跑成功。
- 新玩法已上線：repo 公開、Pages 開好、Mario 手機已存權杖。第一場「你媽應該跟我在一起」3 回合實跑成功，反方勝（那時還是單一 control.json，已搬到 controls/）。
- 之後加了：一段一段發言、即時狀態、額度顯示、無限模式、多題同時打（最多 20 場）。用假的 claude 模擬過（含三場交錯）、用手機尺寸和模擬的 GitHub API 測過網頁，還沒實跑。額度欄位（rate_limit_event）是從 Claude Code 程式碼看出來的格式，實際會不會每次回報要實跑確認。

## 網頁（GitHub Pages）
- 網址：https://mario-0729.github.io/ai-arena/
- 需要 repo 是 Public，且 Settings → Pages → Source 選「GitHub Actions」（只要設一次）。
- 網址公開，誰都看得到；但沒有 GitHub 權杖按不了控制按鈕。
- 部署偶爾出現「No artifacts named "github-pages"」：剛上傳完就部署，GitHub 還沒登記好。所以 deploy.yml 把上傳、部署分成兩個工作，部署失敗會等 20 秒重試一次。網頁只是慢一點更新，辯論本身不受影響。
- 曾考慮 Cloudflare Pages（免費、repo 可維持私人），Mario 選了改公開走 GitHub Pages。之後想改回私人，就得換回 Cloudflare 或付費 GitHub Pro。

## 限制與成本
- GitHub Actions：Public repo 使用標準 runner 不計分鐘數。免費方案同時最多 20 個工作，超過的會排隊；deploy 的兩個工作也占名額，所以 20 場全開時網頁更新會慢一點。
- 同時很多場時，Claude 可能因為短時間請求太多被限速，Claude Code 會自己重試；真的失敗那場會停住，按暫停再繼續就好。
- Claude 額度：每段發言、每次結算各呼叫一次 Claude，都扣 Mario 的 Pro 用量。只在他按開始時才跑；無限模式會一直扣到他按結束，或額度用完 Claude 回錯誤時停住。
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
- 額度快用完（例如 5 小時超過 90%）時自動暫停
