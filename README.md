# 電子報成效資料同步（newsletter-bi-sync）

把 Google Sheets 上的電子報成效資料（sends / links / 對照表 三個分頁），
定期同步成乾淨的 csv／json，放進這個 repo，讓 Qlik、Looker Studio 或其他 BI
工具直接讀 repo 裡的檔案（或透過 GitHub raw URL）。

## 架構

```
Google Sheets（唯一真實資料來源，每月手動貼新一期資料，只增不刪）
        │  GitHub Actions 排程（每月 1 號自動跑，也可手動觸發）
        ▼
scripts/sync_from_sheets.py（整份重新抓、重新算 eid/base_url/category，整份覆蓋 data/）
        │
        ▼
data/sends.csv、data/links.csv、data/articles.csv、data/summary.json
        │
        ▼
Qlik / Looker Studio / 其他 BI 讀取 data/ 底下的檔案
```

**data/ 底下的檔案每次都是整份重寫**，不是累加 —— 因為每次都是拿 Google
Sheet 當下的全貌重新算一次，所以不用擔心漏抓或重複抓。真正「只增不減」的
是 Google Sheets 本身。

## 第一次設定

### 1. Google Sheet 準備

- 需要三個分頁，欄位名稱要跟下面完全一致（大小寫、底線都算）：

  **sends** 分頁：
  `date, report_type, seq, email_name, sent, delivered, hard_bounced, soft_bounced, opened, clicked_email, unsubscribed, first_activity, last_activity`

  **links** 分頁：
  `date, report_type, seq, email_name, link, clicks, people`

  **對照表** 分頁：
  `官網連結, 標題, 生活提案, 大分類, 中分類, 上刊時間, 標籤, 關鍵字`

  > 這三個分頁的欄位跟 `newsletter_bi_master.xlsx` 裡的「輸入欄位」（黃底）
  > 一致。xlsx 裡另外那些用公式算出來的欄位（pct_delivered、eid、category…）
  > 這裡不需要，因為 `sync_from_sheets.py` 會在同步時重新算一次。

- 檔案 → 共用 → 一般存取權限，改成「知道連結的人」→「檢視者」。這支腳本
  是用公開匯出網址抓資料，不需要 Google API 金鑰或登入。

- 三個分頁名稱要完全是 `sends`、`links`、`對照表`（跟 `scripts/sync_from_sheets.py`
  開頭 `SHEET_NAME_*` 常數一致），不需要找 gid。

### 2. 建立 GitHub repo

把這個資料夾整包上傳成一個新 repo（或解壓縮後 `git init` / `git push`）。

### 3. 設定 GitHub repo 的變數

Repo → Settings → Secrets and variables → Actions → Variables 分頁，新增
一個 Repository variable（Sheet ID 不是密碼，用 variables 就好，不需要用
Secrets）：

| Name | Value |
|---|---|
| `SHEET_ID` | Google Sheet 網址裡 `/d/` 跟 `/edit` 中間那一串 |

### 4. 手動跑一次測試

Repo → Actions → 「同步電子報成效資料」→ Run workflow。跑完後 `data/`
底下應該會出現 `sends.csv`、`links.csv`、`articles.csv`、`summary.json`，
並且自動 commit 回 repo。

之後每月 1 號會自動跑；您那邊每月把新一期資料貼進 Google Sheets 底部
就好，不用手動觸發（除非想馬上看到結果）。

## 本機測試

```bash
pip install -r requirements.txt
export SHEET_ID=...
python scripts/sync_from_sheets.py
```

## 檔案說明

- `scripts/sync_from_sheets.py`：主程式，抓資料、算欄位、寫檔案
- `scripts/lib/classify.py`：eid / base_url / category 的判斷邏輯（跟
  xlsx 公式邏輯一致，之後兩邊要一起改）
- `data/summary.json`：給 BI／儀表板快速讀的彙總（每期 KPI、分類加總、
  熱門文章前 30、未歸類網址清單、點擊層沉睡/活躍統計）
- `.github/workflows/sync.yml`：排程 + 手動觸發的 GitHub Action

## 之後要擴充

- **來人與成交**：目前資料完全沒有 GA／CRM，要另外接
- **開信層級的名單健康**：目前只有彙總的 Opened 數量/比例，沒有個人層級
- 新文章上刊時，去 Google Sheets 的「對照表」分頁補一列即可，不用改程式
