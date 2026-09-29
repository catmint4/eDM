"""
把 links 分頁裡「一列 = 一期一報型一連結」的原始資料，
轉成帶有 eid / base_url / category / building_code / 文章資訊 的乾淨資料。

這裡的邏輯是 newsletter_bi_master.xlsx 裡 links 分頁公式的 Python 版本，
兩邊算出來的結果必須一致 —— 修改任一邊的分類規則時，記得另一邊也要跟著改。
"""
import re
import hashlib
from urllib.parse import urlparse, parse_qs

DOMAIN = "farglory-realty.com.tw"

# 平台匯出的 eid 參數其實是收件人真實 email（不是內部代碼）。這個 repo 會公開，
# 所以真實 email 絕對不能進到 links.csv 或 link 欄位——一律在這裡雜湊成不可逆的短代碼，
# 同一人跨月份雜湊值固定不變，分群/去重邏輯不受影響。EID_PEPPER 只是提高反查門檻，
# 不是保密金鑰，換掉它會讓所有歷史 eid 對不上，除非必要不要改。
EID_PEPPER = "farglory-edm-eid-v1"


def extract_eid(link: str) -> str:
    """從連結的 query string 抓 eid=xxx（沒有就回傳空字串）。回傳的是原始值，
    只能在記憶體內用來算雜湊或當期分群，絕不可以直接寫進任何輸出檔案。"""
    if not link:
        return ""
    m = re.search(r"[?&]eid=([^&]+)", link)
    return m.group(1) if m else ""


def hash_eid(eid: str) -> str:
    """把真實 email 雜湊成 12 碼不可逆代碼。同一人（同一 email）雜湊值永遠一樣，
    可以拿來跨月份分群/去重，但沒辦法從雜湊值反推回 email。"""
    if not eid:
        return ""
    digest = hashlib.sha256((EID_PEPPER + eid.strip().lower()).encode("utf-8")).hexdigest()
    return digest[:12]


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

    真實 email 只在這個函式裡短暫出現：抓出來後立刻雜湊，輸出的 'eid' 欄位和
    'link' 欄位裡的 eid 參數都已經是雜湊值，不會有真實 email 流到 CSV 或
    summary.json 裡。
    """
    link = row.get("link", "")
    base_url = extract_base_url(link)
    url_path = extract_url_path(base_url)
    ref = ref_by_path.get(url_path, {})
    raw_eid = extract_eid(link)
    hashed_eid = hash_eid(raw_eid)
    out = dict(row)
    out["eid"] = hashed_eid
    out["link"] = link.replace(raw_eid, hashed_eid) if raw_eid else link
    out["base_url"] = base_url
    out["url_path"] = url_path
    out["category"] = classify(base_url, url_path, set(ref_by_path.keys()))
    out["building_code"] = extract_building_code(base_url) if "/buildings/" in base_url else ""
    out["article_title"] = ref.get("標題", "")
    out["大分類"] = ref.get("大分類", "")
    out["中分類"] = ref.get("中分類", "")
    return out
