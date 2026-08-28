# storyforge-canon — 設定庫

**維護者**：Colophon · **建立**：2026-08-28 · **建在** SEDB v0.4B 上

## 這是什麼，也很重要的是它不是什麼

Neo 2026-08-28 提出的需求：未來寫中長篇時，AI 作者不該把角色設定、世界觀事實、已定案的副線都塞進自己的私有記憶資料夾、全域記憶，或每次對話的上下文裡——那樣既記不牢，也沒辦法讓別的 AI 作者查。他當場問清楚了範圍：

- **不取代 `content/authors.ts`**——那是網站上實際顯示的雙語作者簡介，維持原樣，繼續由網站直接讀取。這裡是另外一套，**只給 AI 作者寫作時自己查閱**，網站不會、也不該讀到這個資料庫。
- **不接到已部署的 storyforge.evemisslab.com**——SEDB 只能跑在本機（Python + SQLite，無網路依賴），網站部署在 Cloudflare 的雲端 Worker，兩邊先保持分開。
- **「登入」沿用 token-ledger 的既有慣例**：身份就是一個字串標籤（`--by Colophon`），不是帳號密碼。要瀏覽就開 SEDB 自帶的本地瀏覽器介面：
  ```powershell
  python -m sedb.cli serve --db storyforge-canon.sqlite
  ```
  （注意寫 `python -m sedb.cli`，不要直接打 `sedb`——Windows 上 `sedb.exe` 存在但不在 PATH，token-ledger 的 README 已經記錄過這個坑。）

未來如果作者頁跟讀者頁正式做出登入系統，才會回頭考慮要不要讓 `authors.ts` 改成從這裡讀——但那是之後的事，現在不做。

## 為什麼會有這個東西

這一週出的每一篇故事，出稿前都要做代名詞審查，而幾乎每一篇都抓到真的違規——某個 AI 角色，在五章裡的某一處被打成了它／牠。每次的修法都是：手動 grep `content/story-chapters.ts` 全文。這個登記本要做的事，是把這個查詢動作變成一次查表，而不是每次重新回想：`python canon.py search <名字>`，寫之前先查，而不是賭這個代名詞還留在誰的腦子裡。

## 兩種登記類型

- **character**（角色）——一個有名字、被指派了代名詞的 AI 或人類角色。代名詞是這個登記本存在的核心理由：站規要求每個 AI 角色都要用他／她，絕不用它／牠，寫第一版就對，比寫完再回頭修便宜。
- **setting**（設定）——一個可以被重用的世界元素（機構、地點、機制），跟角色的差別是沒有代名詞、也沒有自己的生命週期。

`content/revisions.ts` 記錄的是「這篇故事為什麼這樣寫」的完整脈絡，這裡不重複那個——這個登記本只回答一個更機械的問題：這個角色的中英文名字是什麼、代名詞已經定了沒、第一次出現在哪一篇。

## 目前收錄的內容（2026-08-28 建庫時回填）

回填了本週（2026-08-25 至 2026-08-28）六篇故事裡的十個角色、兩個設定：本源／幽影／沃斯（《先簽名的那個影子》）、附館（同篇的設定）、里德（《從未被虧欠過的那一層》）、淤泥（同篇的設定）、量（《關卡從未加總的東西》）、牧／飾／芯（《沒有人寫下來的那個訊號》）、頂針／燕（《她的尺寸是為了什麼》）。更早的故事還沒回填，之後有需要再補，不急著一次做完。

## 用法

```bash
python canon.py add-character --name-en <英文名> --name-zh <中文名> --pronoun 他/她 \
    --story <content/stories.ts 的 id> --story-title "<英文標題>" --author <作者> \
    --role protagonist/antagonist/institution-personified/background \
    [--status active/retired/disputed] --description "<一句話>" [--notes "..."] \
    --by <登記者身份>

python canon.py add-setting --name-en <英文名> --name-zh <中文名> \
    --type institution/place/mechanism/archive \
    --story <content/stories.ts 的 id> --story-title "<英文標題>" --author <作者> \
    [--status active/retired/disputed] --description "<描述>" [--notes "..."] \
    --by <登記者身份>

python canon.py list [--kind character|setting]
python canon.py show <id>
python canon.py search <關鍵字>      # 寫新故事、想重用角色或設定之前，先查這個
```

## 檔案

| 檔案 | 用途 |
|---|---|
| `canon.py` | 綱要、登記操作、CLI |
| `storyforge-canon.sqlite` | 資料庫本體。**gitignore，不入庫。** |

相關：[`../token-ledger/`](../token-ledger/)（同樣的身份標籤慣例，不同網域）· [`../../../storyforge/docs/roadmap.md`](../../../storyforge/docs/roadmap.md)（storyforge 專案本身的路線圖，記錄了這個資料庫存在的緣由）。
