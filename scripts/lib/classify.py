"""
把 links 分頁裡「一列 = 一期一報型一連結」的原始資料，
轉成帶有 eid / base_url / category / building_code / 文章資訊 的乾淨資料。

這裡的邏輯是 newsletter_bi_master.xlsx 裡 links 分頁公式的 Python 版本，
兩邊算出來的結果必須一致 —— 修改任一邊的分類規則時，記得另一邊也要跟著改。
"""
import re
from urllib.parse import urlparse, parse_qs

DOMAIN = "farglory-realty.com.tw"


def extract_eid(link: str) -> str:
    """從連結的 query string 抓 eid=xxx（沒有就回傳空字串）。"""
    if not link:
        return ""
    m = re.search(r"[?&]eid=([^&]+)", link)
    return m.group(1) if m else ""


def extract_base_url(link: str) -> str:
    """把追蹤參數（?eid=...、?utm_...）拿掉，只留乾淨網址。"""
    if not link:
        return ""
    return link.split("?")[0]


def extract_url_path(base_url: str) -> str:
    """base_url 屬於官網網域時，回傳去掉網域、去掉結尾斜線的路徑；否則回傳空字串。"""
    if not base_url or DOMAIN not in base_url:
        return ""
    path = urlparse(base_url).path
    if path.endswith("/"):
        path = path[:-1]
    return path


def extract_building_code(base_url: str) -> str:
    """/buildings/bh13/ -> bh13"""
    m = re.search(r"/buildings/([^/?]+)", base_url or "")
    return m.group(1) if m else ""


def classify(base_url: str, url_path: str, ref_paths: set) -> str:
    """
    決定 category，規則跟 xlsx 的 IF 公式一致，由上而下判斷：
    /buildings/ -> 建案；/case/search -> 建案搜尋；facebook.com -> 外部-FB；
    maac.io -> 外部-短網址；unsubscribe -> 退訂；
    有 url_path 且出現在對照表 -> 生活提案文章；
    有 url_path 但對照表沒有 -> 未歸類(對照表無此網址)；
    其餘（外部網域、無法解析）-> 其他
    """
    b = base_url or ""
    if "/buildings/" in b:
        return "建案"
    if "/case/search" in b:
        return "建案搜尋"
    if "facebook.com" in b:
        return "外部-FB"
    if "maac.io" in b:
        return "外部-短網址"
    if "unsubscribe" in b:
        return "退訂"
    if url_path:
        return "生活提案文章" if url_path in ref_paths else "未歸類(對照表無此網址)"
    return "其他"


def enrich_link_row(row: dict, ref_by_path: dict) -> dict:
    """
    row 需要有 'link' 欄位。回傳新增了 eid/base_url/url_path/category/
    building_code/article_title/大分類/中分類 的新 dict（不改動原本欄位）。
    ref_by_path: {url_path: {"標題":..., "大分類":..., "中分類":...}}
    """
    link = row.get("link", "")
    base_url = extract_base_url(link)
    url_path = extract_url_path(base_url)
    ref = ref_by_path.get(url_path, {})
    out = dict(row)
    out["eid"] = extract_eid(link)
    out["base_url"] = base_url
    out["url_path"] = url_path
    out["category"] = classify(base_url, url_path, set(ref_by_path.keys()))
    out["building_code"] = extract_building_code(base_url) if "/buildings/" in base_url else ""
    out["article_title"] = ref.get("標題", "")
    out["大分類"] = ref.get("大分類", "")
    out["中分類"] = ref.get("中分類", "")
    return out
