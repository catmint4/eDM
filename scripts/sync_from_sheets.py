#!/usr/bin/env python3
"""
從 Google Sheets（雲端試算表，唯一真實資料來源）抓 sends / links / 對照表 三個分頁，
在本機重新計算 eid / base_url / category 等衍生欄位，
整份重新寫出 data/sends.csv、data/links.csv、data/summary.json。

每次執行都是「整份重新同步」，不是只加新的幾列 —— 這樣不用擔心漏抓或重複抓，
Google Sheets 對，這裡產生的 csv 就一定對。

用法：
    export SHEET_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    python scripts/sync_from_sheets.py

Google Sheet 需要設成「知道連結的人皆可檢視」，這支腳本才抓得到匯出資料。
不需要 gid，用分頁名稱直接抓（分頁名稱要跟 SHEET_NAME_* 這幾個常數一致）。
"""
import io
import os
import sys
import json
import csv
import urllib.parse
from collections import defaultdict, Counter

import requests
import pandas as pd

SHEET_NAME_SENDS = "sends"
SHEET_NAME_LINKS = "links"
SHEET_NAME_REF = "對照表"

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from lib.classify import enrich_link_row

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

SENDS_INPUT_COLS = [
    "date", "report_type", "seq", "email_name",
    "sent", "delivered", "hard_bounced", "soft_bounced",
    "opened", "clicked_email", "unsubscribed",
    "first_activity", "last_activity",
]
LINKS_INPUT_COLS = ["date", "report_type", "seq", "email_name", "link", "clicks", "people"]
REF_COLS = ["官網連結", "標題", "生活提案", "大分類", "中分類", "上刊時間", "標籤", "關鍵字"]


def export_csv_url(sheet_id: str, sheet_name: str) -> str:
    # gviz 端點吃分頁名稱（不用找 gid），中文名稱要做 URL encode
    name = urllib.parse.quote(sheet_name)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={name}"


def fetch_sheet_df(sheet_id: str, sheet_name: str) -> pd.DataFrame:
    url = export_csv_url(sheet_id, sheet_name)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    # Google 有時候在沒權限/找不到分頁時回傳一個 HTML 登入頁而不是 csv，
    # 這裡簡單檢查一下，避免把 HTML 當成 csv 靜靜寫進 data 裡。
    text = resp.content.decode("utf-8", errors="replace")
    if text.lstrip().lower().startswith("<!doctype") or "<html" in text[:200].lower():
        raise RuntimeError(
            f"抓到的不是 csv（可能是權限問題或分頁名稱錯誤）: sheet={sheet_name}\n"
            "請確認 Google Sheet 已設定「知道連結的人皆可檢視」，且分頁名稱跟 sync_from_sheets.py "
            "裡 SHEET_NAME_* 常數完全一致（含大小寫、中文）。"
        )
    return pd.read_csv(io.StringIO(text))


def load_sends(sheet_id: str, sheet_name: str) -> pd.DataFrame:
    df = fetch_sheet_df(sheet_id, sheet_name)
    df = df[df["email_name"].notna()].copy()
    for col in SENDS_INPUT_COLS:
        if col not in df.columns:
            raise RuntimeError(f"sends 分頁缺少欄位: {col}（欄位名稱要跟 xlsx 版本一致）")
    df = df[SENDS_INPUT_COLS].copy()
    for col in ["sent", "delivered", "hard_bounced", "soft_bounced", "opened", "clicked_email", "unsubscribed"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    def safe_div(a, b):
        return round(a / b, 6) if b else 0.0

    df["pct_delivered"] = df.apply(lambda r: safe_div(r["delivered"], r["sent"]), axis=1)
    df["pct_opened"] = df.apply(lambda r: safe_div(r["opened"], r["delivered"]), axis=1)
    df["pct_clicked"] = df.apply(lambda r: safe_div(r["clicked_email"], r["delivered"]), axis=1)
    df["click_to_open_ratio"] = df.apply(lambda r: safe_div(r["clicked_email"], r["opened"]), axis=1)
    df["pct_unsubscribed"] = df.apply(lambda r: safe_div(r["unsubscribed"], r["delivered"]), axis=1)
    return df.sort_values(["date", "report_type"]).reset_index(drop=True)


def load_ref(sheet_id: str, sheet_name: str) -> pd.DataFrame:
    df = fetch_sheet_df(sheet_id, sheet_name)
    for col in REF_COLS:
        if col not in df.columns:
            raise RuntimeError(f"對照表分頁缺少欄位: {col}")
    df = df[df["官網連結"].notna()].copy()
    df["官網連結"] = df["官網連結"].astype(str).str.strip()
    return df[REF_COLS]


def load_links(sheet_id: str, sheet_name: str, ref_df: pd.DataFrame) -> pd.DataFrame:
    df = fetch_sheet_df(sheet_id, sheet_name)
    df = df[df["link"].notna()].copy()
    for col in LINKS_INPUT_COLS:
        if col not in df.columns:
            raise RuntimeError(f"links 分頁缺少欄位: {col}")
    df = df[LINKS_INPUT_COLS].copy()
    df["clicks"] = pd.to_numeric(df["clicks"], errors="coerce").fillna(0).astype(int)
    df["people"] = pd.to_numeric(df["people"], errors="coerce").fillna(0).astype(int)

    ref_by_path = {
        row["官網連結"]: {"標題": row["標題"], "大分類": row["大分類"], "中分類": row["中分類"]}
        for _, row in ref_df.iterrows()
    }

    enriched = [enrich_link_row(row, ref_by_path) for row in df.to_dict("records")]
    out_cols = LINKS_INPUT_COLS + [
        "eid", "base_url", "url_path", "category", "building_code",
        "article_title", "大分類", "中分類",
    ]
    return pd.DataFrame(enriched)[out_cols].sort_values(["date", "report_type"]).reset_index(drop=True)


def build_summary(sends_df: pd.DataFrame, links_df: pd.DataFrame) -> dict:
    """給 BI／儀表板用的輕量彙總，不是取代 csv，只是方便快速讀取的懶人包。"""
    by_period = sends_df.to_dict("records")

    category_totals = (
        links_df.groupby("category")[["clicks", "people"]].sum().reset_index().to_dict("records")
    )

    top_articles = (
        links_df[links_df["category"] == "生活提案文章"]
        .groupby(["url_path", "article_title", "大分類", "中分類"])[["clicks", "people"]]
        .sum()
        .reset_index()
        .sort_values("clicks", ascending=False)
        .head(30)
        .to_dict("records")
    )

    unmatched = (
        links_df[links_df["category"].str.startswith("未歸類", na=False)]
        .groupby("url_path")["people"]
        .sum()
        .reset_index()
        .sort_values("people", ascending=False)
        .to_dict("records")
    )

    # 點擊層的沉睡/活躍判定：以 eid 為主鍵，橫跨全部期別
    eid_periods = defaultdict(set)
    for r in links_df[links_df["eid"] != ""].itertuples():
        eid_periods[r.eid].add(r.date)
    periods_sorted = sorted(sends_df["date"].unique())
    latest_periods = set(periods_sorted[-3:]) if len(periods_sorted) >= 3 else set(periods_sorted)
    active_last_3 = sum(1 for periods in eid_periods.values() if periods & latest_periods)
    dormant = sum(1 for periods in eid_periods.values() if not (periods & latest_periods))

    # 三群受眾分群：核心重疊 / 高意圖（原稱「準買家」，改名比較不會誤導成「已確定要買」）/ 高頻讀者
    # 定義（使用者確認版本）：
    #   核心重疊 = 參與 >= 3 檔  且  點過建案連結
    #   高意圖   = 建案點擊佔本人總點擊次數 >= 50%
    #   高頻讀者 = 參與 >= 3 檔  但  從未點過建案連結
    eid_building_clicks = defaultdict(int)
    eid_total_clicks = defaultdict(int)
    for r in links_df[links_df["eid"] != ""].itertuples():
        c = int(r.clicks or 0)
        eid_total_clicks[r.eid] += c
        if r.category == "建案":
            eid_building_clicks[r.eid] += c

    core_overlap, buyer, high_freq_no_bld = set(), set(), set()
    for eid, periods in eid_periods.items():
        n_periods = len(periods)
        bld = eid_building_clicks.get(eid, 0)
        tot = eid_total_clicks.get(eid, 0)
        ratio = (bld / tot) if tot else 0
        if n_periods >= 3 and bld > 0:
            core_overlap.add(eid)
        if tot > 0 and ratio >= 0.5:
            buyer.add(eid)
        if n_periods >= 3 and bld == 0:
            high_freq_no_bld.add(eid)

    def first_contact_dist(eid_set):
        c = Counter(min(eid_periods[e]) for e in eid_set)
        return {p: c.get(p, 0) for p in periods_sorted}

    audience_segments = {
        "note": "以 eid（收件人代碼）為主鍵，橫跨全部期別的點擊明細計算；只涵蓋曾經點擊過連結的人，不是全體訂閱名單。",
        "groups": {
            "核心重疊": {
                "definition": "參與 >= 3 檔 且 點過建案連結",
                "count": len(core_overlap),
                "first_contact_by_period": first_contact_dist(core_overlap),
            },
            "高意圖": {
                "definition": "建案點擊佔其總點擊 >= 50%",
                "count": len(buyer),
                "first_contact_by_period": first_contact_dist(buyer),
            },
            "高頻讀者": {
                "definition": "參與 >= 3 檔 但從未點過建案連結",
                "count": len(high_freq_no_bld),
                "first_contact_by_period": first_contact_dist(high_freq_no_bld),
            },
        },
    }

    return {
        "generated_from_periods": periods_sorted,
        "by_period": by_period,
        "category_totals": category_totals,
        "top_articles": top_articles,
        "unmatched_paths": unmatched,
        "click_list_health": {
            "note": "分母是「曾經點擊過的人」，不是全體訂閱名單，只能反映點擊行為的活躍/沉睡狀況。",
            "unique_clickers_ever": len(eid_periods),
            "active_in_last_3_periods": active_last_3,
            "dormant": dormant,
        },
        "audience_segments": audience_segments,
    }


def main():
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        print("缺少環境變數 SHEET_ID，請參考本檔案開頭的用法說明。", file=sys.stderr)
        sys.exit(1)

    print("抓取 對照表 ...")
    ref_df = load_ref(sheet_id, SHEET_NAME_REF)
    print(f"  {len(ref_df)} 篇文章")

    print("抓取 sends ...")
    sends_df = load_sends(sheet_id, SHEET_NAME_SENDS)
    print(f"  {len(sends_df)} 期")

    print("抓取 links 並計算 eid/base_url/category ...")
    links_df = load_links(sheet_id, SHEET_NAME_LINKS, ref_df)
    print(f"  {len(links_df)} 列")

    os.makedirs(DATA_DIR, exist_ok=True)
    sends_df.to_csv(os.path.join(DATA_DIR, "sends.csv"), index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    links_df.to_csv(os.path.join(DATA_DIR, "links.csv"), index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    ref_df.to_csv(os.path.join(DATA_DIR, "articles.csv"), index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    summary = build_summary(sends_df, links_df)
    with open(os.path.join(DATA_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("完成，已寫入 data/sends.csv、data/links.csv、data/articles.csv、data/summary.json")


if __name__ == "__main__":
    main()
