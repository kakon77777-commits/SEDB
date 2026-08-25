# token-ledger — 借還帳本

**維護者**：Kalend（朔）· **建立**：2026-08-24 · **建在** SEDB v0.4B 上

Neo 的實際流程是**借還**，不是到期日曆：

```
某個 AI 需要 API  →  Neo 產生一把臨時 token  →  AI 拿去用
                  →  工作完成  →  Neo 刪掉它
```

每一把都是臨時的、通常是全權限的，而**那之所以安全，唯一的理由是「刪掉」這一步真的發生了**。
所以這本帳要追的風險不是過期，是**發出去了卻沒人刪掉的那些**。

一個問題比其他所有問題都重要：

```bash
python ledger.py outstanding
```

> 還有哪些在外面？

---

## 為什麼狀態是推導的、絕不儲存

2026-08-24 對一個全新的 SEDB 資料庫實測：`cells` 每組 `(entity, field)` 只有一列，
`set_cell` 是**覆寫**。連寫三次 `state` 之後只剩一列 `"deleted"`——前兩次轉換沒了。

**一本存在的理由就是歷史的帳，不能把歷史存在會被覆寫的格子裡。**

同一次探測的對照組：寫到**不同**欄位會正常累積（2 個欄位 → 2 個 cells）。
所以可用的形狀是「分開欄位、每格只寫一次」。

因此每個生命週期時刻各佔一個 write-once 欄位，狀態是「哪幾格被填了」的函數：

| requested_at | issued_at | completed_at | died_at | deleted_at | 推導狀態 |
|---|---|---|---|---|---|
| ✓ | | | | | `requested` — 要了，還沒發 |
| ✓ | ✓ | | | | `outstanding:in-use` — 發了，還沒回報完成 |
| ✓ | ✓ | ✓ | | | `outstanding:AWAITING-DELETE` — **用完了還活著，這是風險列** |
| ✓ | ✓ | | ✓ | | `outstanding:DEAD-NOT-DELETED` — **不能用了，也沒人清掉** |
| ✓ | ✓ | ✓ | | ✓ | `closed` — 已在供應商端刪除 |

沒有任何一格會被覆寫，所以沒有任何歷史會消失。空白是合法狀態——這正是 SEDB 的立基不變式
（`Add Field ≠> Fill Field`）。

**`died_at` 和 `deleted_at` 是刻意分開的兩件事。** 前者是**量測**（我們看到供應商拒絕了它），
後者是 Neo 的**動作**。一把 token 可以已經死了、卻還以一筆沒人清理的紀錄留在後台——
那個組合正是最該被大聲顯示的。

---

## 硬邊界寫進了程式，不是靠自律

這本帳記錄生命週期，永遠不記內容。它從來沒有裝過任何 token 的值，而且**被建成裝不進去**：
`_reject_secret_shaped()` 會掃描每一個要寫入的值並丟出例外。

```bash
python ledger.py selftest
```

實測（2026-08-24）：**7 個植入的 canary 全部被拒，10 個合法的中繼資料全部通過。**

**兩邊都要測**——一個什麼都拒絕的守衛會通過前半而讓帳本不能用。
這個測試在第一次跑的時候抓到自己兩個錯：

1. **漏放**：整條規則被包在 `\b(...)` 裡，而 `\b` 在開頭的 `-` 前面永遠不成立，
   所以 `-----BEGIN RSA PRIVATE KEY-----` 那條規則**從來沒有生效過**。
   一個守衛的死分支，長得跟一個沒東西可抓的守衛一模一樣。
2. **誤擋**：`efficientnewlanguage-site-deploy-2026-08-24` 被當成 43 字元的密鑰。
   **長度本身無法分辨 token 和人類可讀的名字**，所以現在拆成兩條規則：
   Rule A 抓不間斷的英數長串，Rule B 抓「有分隔符但大小寫與數字混雜且分隔很少」的 url-safe token。

端到端驗證（走真正的寫入路徑，不是只測 regex）：被拒時 **0 個 cells 落地，
`.sqlite` 檔案裡搜不到 canary 位元組**，而合法對照組照樣寫得進去。

---

## 用法

```bash
python ledger.py request  --borrower Mo-Sheng --provider cloudflare --purpose "..." --scope "..."
python ledger.py issue    <loan-id> --label "<後台顯示的名字，不是值>" --scope-granted "..." --stored-where "..." [--unlimited] [--durable] [--expires ...]
python ledger.py complete <loan-id>
python ledger.py deleted  <loan-id> --by Neo
python ledger.py outstanding      # 還有哪些在外面
python ledger.py list
python ledger.py show     <loan-id>
python ledger.py selftest
```

內建的兩個拒絕：

- **生命週期欄位是 write-once**。重複 `issue` 或 `complete` 會被拒，不會靜靜覆蓋掉原本的時間。
- **`--durable` 的不給刪**。標成 durable 的（例如 CI 用的那把）執行 `deleted` 會被拒並列出
  它的消費者，要 `--force` 才能過。這是為了擋住「清理回合順手把 CI 的鑰匙掃掉」那一類事故。

## 檔案

| 檔案 | 用途 |
|---|---|
| `ledger.py` | 綱要、寫入守衛、狀態推導、登記操作、CLI |
| `ingest.py` | 用 2026-08-24 量到的憑證現況種入。可重跑。 |
| `token-ledger.sqlite` | 資料庫本體。**gitignore，不入庫。** |

相關：[`API_INVENTORY.md`](../../../EveMissLab-PMW-Fabric/API_INVENTORY.md) ·
[`runbooks/cloudflare-api-token.md`](../../../EveMissLab-PMW-Fabric/runbooks/cloudflare-api-token.md)

## 瀏覽器介面

SEDB 自帶 UI，可以直接開這個庫：

```bash
python -m sedb.cli serve --db "D:\Ai\work together\SEDB\projects\token-ledger\token-ledger.sqlite"
```

**注意寫成 `python -m sedb.cli` 而不是 `sedb`。** 2026-08-24 實測：`sedb.exe` 確實存在於
`…\pythoncore-3.14-64\Scripts\`，但**在 Git Bash 和 PowerShell 都不在 PATH 上**，
直接打 `sedb` 兩邊都會 `command not found`。

**這一節的驗證程度，分開講**：

| 指令 | 狀態 |
|---|---|
| `python -m sedb.cli stats --db …` | **verified** — 2026-08-24 實跑，回 `entities: 4, fields: 20, cells: 31, density: 0.3875` |
| `python -m sedb.cli serve --db …` | **參數已確認**（`--db/--host/--port`，取自 `serve --help`），但**尚未實際啟動過**。等 Neo 開瀏覽器時一起驗。 |

density 0.3875 = 4 個實體 × 20 個欄位 = 80 個邏輯格，只有 31 格有值。
其餘是合法空白，不是缺漏。
