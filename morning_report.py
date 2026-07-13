#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
חדשות הבוקר — Daily infographic, sent to RATRADE25@GMAIL.COM
2 PNG images: (1) Markets  (2) Stocks + Earnings

Usage:
  python morning_report.py pre    → 14:00 pre-market  (default)
  python morning_report.py mid    → 20:00 mid-session (3.5h into trading)
"""

import smtplib, datetime, os, sys, concurrent.futures, math
import xml.etree.ElementTree as ET

# ── Mode ─────────────────────────────────────────
MODE = sys.argv[1].lower() if len(sys.argv) > 1 else "pre"
# MODE = "pre"  → 14:00 — לפני פתיחה
# MODE = "mid"  → 20:00 — אמצע יום (3.5 שעות אחרי פתיחה)
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# ── settings ─────────────────────────────────
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")
TO_EMAIL       = os.environ.get("TO_EMAIL", GMAIL_USER)
SAVE_DIR       = os.path.dirname(os.path.abspath(__file__))

try:
    import yfinance as yf
    import requests
    from PIL import Image, ImageDraw, ImageFont
    from bidi.algorithm import get_display
except ImportError as e:
    print(f"Missing: {e}  →  pip install yfinance requests pillow python-bidi lxml")
    sys.exit(1)

# ══════════════════════════════════════════════
#  DESIGN TOKENS
# ══════════════════════════════════════════════
W = 1080; PAD = 40
C = {
    'bg':    (7, 9, 14),    'card':  (13,17,27),   'card2': (19,24,38),
    'border':(30,38,56),    'text':  (218,226,242), 'muted': (98,114,136),
    'blue':  (56,125,240),  'green': (32,192,88),   'red':   (234,62,62),
    'yellow':(240,154,8),   'white': (255,255,255),
    'btc':   (247,147,26),  'eth':   (98,126,234),  'sol':   (153,69,255),
    'dim':   (10,13,21),
}
FP = 'C:/Windows/Fonts/'

def fonts():
    reg = FP+'segoeui.ttf'; bold = FP+'segoeuib.ttf'; semi = FP+'seguisb.ttf'
    try:
        return {
            'xs'  : ImageFont.truetype(reg,  20),
            'sm'  : ImageFont.truetype(reg,  24),
            'base': ImageFont.truetype(reg,  28),
            'semi': ImageFont.truetype(semi, 30),
            'bd'  : ImageFont.truetype(bold, 30),
            'bd_m': ImageFont.truetype(bold, 38),
            'bd_l': ImageFont.truetype(bold, 48),
            'bd_xl': ImageFont.truetype(bold,62),
            'hd'  : ImageFont.truetype(bold, 52),
        }
    except:
        d = ImageFont.load_default()
        return {k:d for k in ['xs','sm','base','semi','bd','bd_m','bd_l','bd_xl','hd']}

# ══════════════════════════════════════════════
#  1. MARKET DATA
# ══════════════════════════════════════════════
def pct(sym, period="5d"):
    try:
        h = yf.Ticker(sym).history(period=period)
        if len(h)>=2:
            p,c = h["Close"].iloc[-2], h["Close"].iloc[-1]
            return round(c,2), round((c-p)/p*100, 2)
        elif len(h)==1:
            return round(h["Close"].iloc[-1],2), 0.0
    except: pass
    return None, None

def get_market_data():
    syms = {
        "sp500":"^GSPC","dji":"^DJI","nasdaq":"^IXIC","russell":"^RUT","vix":"^VIX",
        "gold":"GC=F","wti":"CL=F","brent":"BZ=F","silver":"SI=F","copper":"HG=F",
        "dxy":"DX-Y.NYB","eurusd":"EURUSD=X","usdjpy":"JPY=X","usdils":"ILS=X",
        "tnx":"^TNX","tyx":"^TYX","qqq":"QQQ","spy":"SPY",
        "nvda":"NVDA","avgo":"AVGO","msft":"MSFT","aapl":"AAPL","meta":"META",
        "googl":"GOOGL","amzn":"AMZN","tsla":"TSLA",
        "btc":"BTC-USD","eth":"ETH-USD","sol":"SOL-USD","bnb":"BNB-USD",
        # ── S&P sector ETFs (SPDR Select Sector) ──
        "xlk":"XLK","xlf":"XLF","xle":"XLE","xlv":"XLV","xly":"XLY","xlp":"XLP",
        "xli":"XLI","xlb":"XLB","xlre":"XLRE","xlu":"XLU","xlc":"XLC",
    }
    # Batched download — far fewer HTTP calls, so it isn't rate-limited on cloud
    # IPs, and a 6-day window always contains the last trading day (so values
    # stay populated on weekends / holidays instead of going blank).
    data = {k: {"val": None, "chg": None} for k in syms}
    symbols = list(dict.fromkeys(syms.values()))
    try:
        df = yf.download(symbols, period="6d", interval="1d",
                         group_by="ticker", auto_adjust=True,
                         threads=True, progress=False)
        for k, s in syms.items():
            try:
                closes = df[s]["Close"].dropna()
                if len(closes) >= 2:
                    p, c = float(closes.iloc[-2]), float(closes.iloc[-1])
                    if p:
                        data[k] = {"val": round(c, 2), "chg": round((c - p) / p * 100, 2)}
                elif len(closes) == 1:
                    data[k] = {"val": round(float(closes.iloc[-1]), 2), "chg": 0.0}
            except Exception:
                pass
    except Exception as e:
        print(f"  market batch error: {e} — falling back to per-symbol")
        for k, s in syms.items():
            v, c = pct(s)
            data[k] = {"val": v, "chg": c}
    return data

# ══════════════════════════════════════════════
#  2. CNN FEAR & GREED
# ══════════════════════════════════════════════
def get_fear_greed():
    try:
        h = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
             'Referer':'https://edition.cnn.com/markets/fear-and-greed','Accept':'application/json'}
        r = requests.get('https://production.dataviz.cnn.io/index/fearandgreed/graphdata/',
                         headers=h, timeout=8)
        d = r.json()["fear_and_greed"]
        return round(d["score"]), d["rating"].replace("_"," ").title(), round(d.get("previous_close", d["score"]))
    except Exception as e:
        print(f"  F&G error: {e}")
        return None, None, None

# ══════════════════════════════════════════════
#  3. EARNINGS CALENDAR  (today + yesterday for after-hours)
# ══════════════════════════════════════════════
# Focused on the most-watched reporters — kept tight so the per-ticker calendar
# scan completes without tripping Yahoo's per-IP rate limit on cloud hosts.
WATCHLIST = [
    'NVDA','AAPL','MSFT','GOOGL','AMZN','META','TSLA','AVGO','AMD','INTC',
    'NFLX','ORCL','CRM','ADBE','PLTR','SNOW','CRWD','PANW','MU','QCOM',
    'JPM','BAC','GS','MS','WFC','V','MA','AXP',
    'JNJ','PFE','ABBV','MRK','LLY','UNH',
    'WMT','COST','HD','NKE','SBUX','MCD',
    'XOM','CVX','BA','CAT','GE','DIS','UBER','COIN',
]

def _check_one(sym, target_dates):
    try:
        t = yf.Ticker(sym)
        cal = t.calendar
        if not cal or 'Earnings Date' not in cal:
            return None
        ed_list = cal['Earnings Date']
        first_ed = ed_list[0] if isinstance(ed_list,list) else ed_list
        if isinstance(first_ed, datetime.datetime):
            first_ed = first_ed.date()
        if first_ed not in target_dates:
            return None

        # Determine timing from hours (after close = 16:xx ET)
        raw_ed = ed_list[0] if isinstance(ed_list,list) else ed_list
        timing = "AFTER"
        if hasattr(raw_ed,'hour'):
            timing = "PRE" if raw_ed.hour < 12 else "AFTER"

        eps_est = cal.get('Earnings Average') or cal.get('Earnings Low')
        rev_est = cal.get('Revenue Average')

        # Try actual EPS from earnings_dates
        eps_actual = surprise_pct = None
        try:
            ed_df = t.earnings_dates
            if ed_df is not None:
                for idx, row in ed_df.iterrows():
                    idx_date = idx.date() if hasattr(idx,'date') else None
                    if idx_date in target_dates:
                        if row.get('Reported EPS') and str(row['Reported EPS']) != 'nan':
                            eps_actual = float(row['Reported EPS'])
                            sp = row.get('Surprise(%)')
                            if sp and str(sp) != 'nan':
                                surprise_pct = float(sp)
                        break
        except: pass

        beat_eps = None
        if eps_actual is not None and eps_est:
            beat_eps = eps_actual > float(eps_est)

        # Try actual revenue from quarterly_income_stmt
        rev_actual = beat_rev = None
        if eps_actual is not None:  # only if already reported
            try:
                fin = t.quarterly_income_stmt
                if fin is not None and 'Total Revenue' in fin.index:
                    rev_row = fin.loc['Total Revenue']
                    # First column is most recent quarter
                    rev_actual = float(rev_row.iloc[0])
                    if rev_est and rev_est > 0:
                        beat_rev = rev_actual > float(rev_est)
            except: pass

        info = t.info

        # ── Stock price reaction ──────────────────────────────────────────
        stock_price = stock_prev = stock_reaction = None
        pre_mkt_price = pre_mkt_chg = None
        try:
            # Current / regular market
            stock_price = info.get('regularMarketPrice') or info.get('currentPrice')
            stock_prev  = info.get('regularMarketPreviousClose') or info.get('previousClose')
            if stock_price and stock_prev and stock_prev > 0:
                stock_reaction = round((stock_price - stock_prev) / stock_prev * 100, 2)

            # Pre-market (if available)
            pm_p = info.get('preMarketPrice')
            if pm_p and stock_prev and stock_prev > 0:
                pre_mkt_price = pm_p
                pre_mkt_chg   = round((pm_p - stock_prev) / stock_prev * 100, 2)

            # Post-market (if available)
            post_p = info.get('postMarketPrice')
            if post_p and stock_price and stock_price > 0:
                # override reaction with AH price vs today's close
                stock_reaction = round((post_p - stock_price) / stock_price * 100, 2)
                stock_price = post_p
        except: pass

        return {
            'ticker'        : sym,
            'name'          : info.get('shortName', sym)[:28],
            'sector'        : info.get('sector',''),
            'timing'        : timing,
            'eps_est'       : float(eps_est) if eps_est else None,
            'eps_actual'    : eps_actual,
            'beat_eps'      : beat_eps,
            'surprise'      : surprise_pct,
            'rev_est'       : float(rev_est) if rev_est else None,
            'rev_actual'    : rev_actual,
            'beat_rev'      : beat_rev,
            'reported'      : eps_actual is not None,
            'stock_price'   : stock_price,
            'stock_reaction': stock_reaction,   # today vs prev close (or AH vs close)
            'pre_mkt_chg'   : pre_mkt_chg,
        }
    except: return None

def get_earnings_today(mode="pre"):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    tomorrow  = today + datetime.timedelta(days=1)

    if mode == "pre":
        # 14:00 — show today's expected + yesterday's after-hours (already reported)
        targets = {today, yesterday}
        desc = f"{today} / {yesterday} (yesterday AH)"
    else:
        # 20:00 — show today's (already reported + still expected) + tomorrow's pre-market
        targets = {today, yesterday, tomorrow}
        desc = f"{yesterday} / {today} / {tomorrow} (incl tomorrow PRE)"

    print(f"  Checking {len(WATCHLIST)} stocks for earnings on {desc}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda s: _check_one(s, targets), WATCHLIST))

    found = sorted([r for r in results if r], key=lambda x: (x['timing'], x['ticker']))
    print(f"  Found {len(found)} earners")
    return found

# ══════════════════════════════════════════════
#  4. TRENDING STOCKS BY VOLUME
# ══════════════════════════════════════════════
# Kept to ~60 liquid large/mega-caps so the single batched download stays light
# enough to finish quickly on a small (free-tier) cloud instance.
TRENDING_UNIVERSE = [
    'NVDA','AAPL','MSFT','AMZN','META','GOOGL','TSLA','AVGO','AMD','INTC',
    'QCOM','MU','ARM','SMCI','MRVL','ORCL','CRM','ADBE','NOW','PLTR',
    'NET','CRWD','PANW','AMAT','LRCX','KLAC','ASML','DELL',
    'JPM','BAC','GS','MS','WFC','V','MA','PYPL','COIN','HOOD',
    'LLY','JNJ','PFE','ABBV','MRK','UNH','TMO','ISRG','AMGN',
    'WMT','COST','HD','NKE','SBUX','MCD',
    'XOM','CVX','SLB',
    'BA','GE','CAT','LMT','RTX',
    'NFLX','DIS','UBER','ABNB','SNAP','RDDT',
    'F','GM','MSTR','SCHW',
]

def _get_vol_info(sym):
    try:
        t  = yf.Ticker(sym)
        fi = t.fast_info
        mc = fi.market_cap
        if not mc or mc < 1e9:
            return None
        hist = t.history(period="15d")
        if len(hist) < 5:
            return None
        # Drop rows missing Close or Volume, then find last COMPLETED day
        hist = hist[['Close', 'Volume']].dropna()
        if len(hist) < 5:
            return None
        today     = datetime.date.today()
        last_date = hist.index[-1].date()
        # If last bar is today (market open/closed holiday) skip it — use -2
        idx = -2 if last_date >= today else -1
        if len(hist) < abs(idx) + 1:
            return None
        vols     = hist['Volume']
        closes   = hist['Close']
        last_vol = int(vols.iloc[idx])
        avg_vol  = int(vols.iloc[:idx].mean())
        if avg_vol == 0:
            return None
        ratio = last_vol / avg_vol
        if ratio < 1.4:
            return None
        price_raw = float(closes.iloc[idx])
        prev_raw  = float(closes.iloc[idx - 1])
        if math.isnan(price_raw) or math.isnan(prev_raw):
            return None
        price = round(price_raw, 2)
        chg   = round((price_raw - prev_raw) / prev_raw * 100, 2) if prev_raw else None
        return {
            'ticker': sym,
            'price':  price,
            'chg':    chg,
            'mc':     mc,
            'vol':    last_vol,
            'avg_vol':avg_vol,
            'ratio':  round(ratio, 1),
        }
    except:
        return None

def get_trending_stocks(n=12):
    """Scan the universe for volume spikes using ONE batched download.

    Batching keeps us under Yahoo's per-IP rate limits (so it actually works on
    cloud hosts), and picking the last *completed* daily bar means it shows the
    most recent trading day's data even when the market is closed.
    """
    print(f"  Scanning {len(TRENDING_UNIVERSE)} stocks (batched)...")
    try:
        df = yf.download(TRENDING_UNIVERSE, period="25d", interval="1d",
                         group_by="ticker", auto_adjust=True,
                         threads=True, progress=False)
    except Exception as e:
        print(f"  trending download error: {e}")
        return []

    today = datetime.date.today()
    out = []
    for sym in TRENDING_UNIVERSE:
        try:
            sub = df[sym][['Close', 'Volume']].dropna()
            if len(sub) < 6:
                continue
            # Use the last COMPLETED session: if the last bar is today, step back one
            last_date = sub.index[-1].date()
            pos = len(sub) - 1 if last_date < today else len(sub) - 2
            if pos < 2:
                continue
            vols, closes = sub['Volume'], sub['Close']
            last_vol = float(vols.iloc[pos])
            prior    = vols.iloc[max(0, pos - 10):pos]
            avg_vol  = float(prior.mean()) if len(prior) else 0.0
            if not avg_vol or math.isnan(avg_vol):
                continue
            ratio = last_vol / avg_vol
            if ratio < 1.4:
                continue
            price = float(closes.iloc[pos])
            prev  = float(closes.iloc[pos - 1])
            if math.isnan(price) or math.isnan(prev) or not prev:
                continue
            out.append({
                'ticker': sym,
                'price':  round(price, 2),
                'chg':    round((price - prev) / prev * 100, 2),
                'mc':     None,
                'vol':    int(last_vol),
                'avg_vol': int(avg_vol),
                'ratio':  round(ratio, 1),
            })
        except Exception:
            continue

    out.sort(key=lambda x: x['ratio'], reverse=True)
    print(f"  Found {len(out)} with elevated volume, showing top {n}")
    return out[:n]

# ══════════════════════════════════════════════
#  4a-2. SOCIAL MENTIONS SCANNER  (apewisdom.io — Reddit + X/Twitter)
# ══════════════════════════════════════════════
def get_social_mentions(n=20):
    """Top stocks by social-media mention count (Reddit + X) via apewisdom.io."""
    url = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"
    try:
        r = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if r.status_code != 200:
            print(f"  social mentions HTTP {r.status_code}")
            return []
        data = r.json().get('results', [])
        out = []
        for item in data[:n]:
            ticker = item.get('ticker', '')
            mentions = item.get('mentions', 0)
            upvotes = item.get('upvotes', 0)
            rank = item.get('rank', 0)
            name = item.get('name', ticker)
            mentions_24h_ago = item.get('mentions_24h_ago', 0)
            if mentions_24h_ago and mentions_24h_ago > 0:
                change_pct = round((mentions - mentions_24h_ago) / mentions_24h_ago * 100, 1)
            else:
                change_pct = None
            out.append({
                'ticker': ticker,
                'name': name,
                'mentions': mentions,
                'upvotes': upvotes,
                'rank': rank,
                'mentions_24h_ago': mentions_24h_ago,
                'change_pct': change_pct,
            })
        print(f"  Social mentions: {len(out)} stocks")
        return out
    except Exception as e:
        print(f"  social mentions error: {e}")
        return []

# ══════════════════════════════════════════════
#  4b. ECONOMIC CALENDAR  (ForexFactory weekly XML via browser-impersonating TLS)
# ══════════════════════════════════════════════
def get_economic_events(countries=("USD",), impacts=("High", "Medium")):
    """This week's high/medium-impact US economic events.

    The feed sits behind Cloudflare and blocks plain `requests`; curl_cffi
    impersonates a real Chrome TLS fingerprint so the server can read it.
    """
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    try:
        from curl_cffi import requests as _cffi
        r = _cffi.get(url, impersonate="chrome", timeout=15)
        if r.status_code != 200:
            print(f"  econ feed HTTP {r.status_code}")
            return []
        try:
            from lxml import etree as _LET
            root = _LET.fromstring(r.content, _LET.XMLParser(recover=True))
        except Exception:
            root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  econ events error: {e}")
        return []

    out = []
    for ev in root.findall(".//event"):
        country = (ev.findtext("country") or "").strip()
        impact  = (ev.findtext("impact")  or "").strip()
        if country not in countries or impact not in impacts:
            continue
        date_s = (ev.findtext("date") or "").strip()   # MM-DD-YYYY
        iso = date_s
        try:
            iso = datetime.datetime.strptime(date_s, "%m-%d-%Y").date().isoformat()
        except Exception:
            pass
        out.append({
            "title":    (ev.findtext("title")    or "").strip(),
            "country":  country,
            "impact":   impact,
            "date":     iso,
            "time":     (ev.findtext("time")     or "").strip(),
            "forecast": (ev.findtext("forecast") or "").strip(),
            "previous": (ev.findtext("previous") or "").strip(),
            "actual":   (ev.findtext("actual")   or "").strip(),
        })

    def _key(e):
        try:
            t = datetime.datetime.strptime(e["time"].upper().replace(" ", ""), "%I:%M%p").time()
        except Exception:
            t = datetime.time(0, 0)
        return (e["date"], t)
    out.sort(key=_key)
    return out

# ══════════════════════════════════════════════
#  5. NEWS RSS  (only a few headlines now)
# ══════════════════════════════════════════════
def get_rss(url, n=4):
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:n]
        return [{"title": i.findtext("title","").strip(),
                 "link" : i.findtext("link","").strip()} for i in items if i.findtext("title","")]
    except: return []

def get_news():
    return (get_rss("https://finance.yahoo.com/news/rssindex", 4) +
            get_rss("https://feeds.content.dowjones.io/public/rss/mw_topstories", 3))

# ══════════════════════════════════════════════
#  5. HELPERS
# ══════════════════════════════════════════════
def fv(v, dec=2, px='$'):
    if v is None: return '—'
    if dec==0: return f'{px}{v:,.0f}'
    return f'{px}{v:,.{dec}f}'

def fc(v):
    if v is None: return '—'
    return f"{'▲' if v>=0 else '▼'} {abs(v):.2f}%"

def cc(v):
    if v is None: return C['muted']
    return C['green'] if v>=0 else C['red']

def hb(t):
    try: return get_display(t)
    except: return t

def tw(d, t, f):
    try: return d.textlength(t, font=f)
    except: return len(t)*10

def right_text(d, text, font, rx, cy, color):
    """Draw text right-aligned at rx, vertically centered at cy."""
    w = tw(d, text, font)
    try:
        bb = d.textbbox((0,0), text, font=font)
        h = bb[3]-bb[1]
    except:
        h = 20
    d.text((rx-w, cy-h//2), text, font=font, fill=color)

def fit_font(d, text, F, target_w, keys):
    """Return the largest font from keys whose rendered width fits target_w."""
    for k in keys:
        if tw(d, text, F[k]) <= target_w:
            return F[k]
    return F[keys[-1]]

# ══════════════════════════════════════════════
#  6. CANVAS
# ══════════════════════════════════════════════
class Canvas:
    def __init__(self, w=W):
        self.w = w; self._rows = []; self.total_h = 0
    def push(self, h, fn):
        self._rows.append((h, fn)); self.total_h += h
    def sp(self, h=10):
        self.push(h, lambda img,d,y: None)
    def render(self):
        img = Image.new('RGB', (self.w, self.total_h), C['bg'])
        d = ImageDraw.Draw(img); y = 0
        for h, fn in self._rows:
            fn(img, d, y); y += h
        return img

# ══════════════════════════════════════════════
#  7. HEBREW DATE HELPERS
# ══════════════════════════════════════════════
import math

HE_DAYS = {0:"יום שני",1:"יום שלישי",2:"יום רביעי",
           3:"יום חמישי",4:"יום שישי",5:"שבת",6:"יום ראשון"}
HE_MONTHS = {1:"ינואר",2:"פברואר",3:"מרץ",4:"אפריל",5:"מאי",6:"יוני",
             7:"יולי",8:"אוגוסט",9:"ספטמבר",10:"אוקטובר",11:"נובמבר",12:"דצמבר"}

def he_date_parts(dt):
    """Return (day_he, date_str) separately to avoid bidi mixing issues."""
    day   = hb(HE_DAYS[dt.weekday()])
    month = hb(HE_MONTHS[dt.month])
    date  = f"{dt.day} {month} {dt.year}"
    time  = dt.strftime('%H:%M')
    return day, date, time

# ══════════════════════════════════════════════
#  8. DRAW COMPONENTS
# ══════════════════════════════════════════════

# ── HEADER ─────────────────────────────────────────────────────────────
def d_header(cv, today, sp_val, sp_chg, fg, F, mode="pre"):
    H = 116
    title_he  = "חדשות הבוקר"  if mode == "pre" else "עדכון אמצע יום"
    badge_he  = "לפני פתיחה"   if mode == "pre" else "אמצע יום"
    badge_col = C['blue']       if mode == "pre" else C['yellow']
    day_he, date_str, time_str = he_date_parts(today)

    def fn(img, d, y):
        # Gradient background
        for i in range(H):
            t = i/H
            d.line([(0,y+i),(W,y+i)],
                   fill=(int(12+t*14), int(15+t*18), int(22+t*50)))
        d.line([(0,y+H-1),(W,y+H-1)], fill=C['border'])

        # ── Title + badge (left) ──
        title = hb(title_he)
        d.text((PAD, y+14), title, font=F['hd'], fill=C['white'])
        badge = hb(badge_he)
        btw   = int(tw(d, badge, F['xs']))
        bx    = int(PAD + tw(d, title, F['hd']) + 16)
        d.rounded_rectangle([bx, y+22, bx+btw+16, y+46], radius=6, fill=badge_col)
        d.text((bx+8, y+25), badge, font=F['xs'], fill=C['white'])

        # ── Hebrew date subtitle ──
        d.text((PAD,    y+80), day_he,   font=F['sm'], fill=C['text'])
        dw = int(tw(d, day_he, F['sm']))
        d.text((PAD+dw+14, y+80), f"·  {date_str}  ·  {time_str}",
               font=F['sm'], fill=C['muted'])

        # ── S&P 500 (right column) ──
        rx = W - PAD
        if sp_val:
            sp_s  = f"{sp_val:,.2f}"
            chg_s = fc(sp_chg)
            lbl   = "S&P 500"
            lw = int(tw(d,lbl, F['sm'])); sw = int(tw(d,sp_s, F['bd_m']))
            cw = int(tw(d,chg_s, F['bd']))
            d.text((rx-lw,  y+14), lbl,   font=F['sm'],  fill=C['muted'])
            d.text((rx-sw,  y+38), sp_s,  font=F['bd_m'],fill=C['white'])
            d.text((rx-cw,  y+80), chg_s, font=F['bd'],  fill=cc(sp_chg))
    cv.push(H, fn)

# ── SECTION DIVIDER ────────────────────────────────────────────────────
def d_section(cv, label, F, top=14, bot=4, accent=None):
    H = top + 38 + bot
    safe = hb(label) if any('א' <= c <= 'ת' for c in label) else label
    col  = accent or C['blue']
    def fn(img, d, y):
        d.rectangle([(PAD, y+top+2), (PAD+5, y+top+32)], fill=col)
        d.text((PAD+16, y+top+4), safe, font=F['bd'], fill=C['text'])
        d.line([(PAD, y+H-2),(W-PAD, y+H-2)], fill=C['border'])
    cv.push(H, fn)

# ── INDEX GRID  (3-col colored cards) ─────────────────────────────────
def d_index_grid(cv, indices, F, cols=3):
    gap    = 10
    card_w = (W - PAD*2 - gap*(cols-1)) // cols
    card_h = 96
    rows   = math.ceil(len(indices)/cols)
    total_h = rows*(card_h+gap) + 14

    def fn(img, d, y):
        for i,(label,val,chg) in enumerate(indices):
            col = i % cols;  row = i // cols
            cx1 = PAD + col*(card_w+gap)
            cy1 = y + 6 + row*(card_h+gap)
            is_pos = (chg or 0) >= 0
            edge   = C['green'] if is_pos else C['red']
            bg     = (17,27,20) if is_pos else (27,17,17)
            d.rounded_rectangle([cx1,cy1,cx1+card_w,cy1+card_h], radius=9, fill=bg)
            # Top accent stripe
            d.rounded_rectangle([cx1,cy1,cx1+card_w,cy1+4], radius=3, fill=edge)
            # Label
            safe_lbl = hb(label) if any('א'<=c<='ת' for c in label) else label
            lw  = int(tw(d,safe_lbl,F['xs']))
            mid = cx1 + card_w//2
            d.text((mid - lw//2, cy1+10), safe_lbl, font=F['xs'], fill=C['muted'])
            # Value — adaptive size
            vf = fit_font(d,val,F,card_w-14,['bd_m','bd','semi','base','sm'])
            vw = int(tw(d,val,vf))
            d.text((mid - vw//2, cy1+30), val, font=vf, fill=C['white'])
            # % change pill
            cs  = fc(chg); csw = int(tw(d,cs,F['xs']))
            px1 = mid - csw//2 - 7
            d.rounded_rectangle([px1, cy1+68, px1+csw+14, cy1+86], radius=4,
                                 fill=(*(C['green'] if is_pos else C['red']),))
            d.text((px1+7, cy1+69), cs, font=F['xs'], fill=C['white'])
    cv.push(total_h, fn)

# ── CRYPTO HERO CARD ───────────────────────────────────────────────────
def d_crypto(cv, sym, name_he, val, chg, col, F):
    H = 96
    def fn(img, d, y):
        # Card with colored border
        d.rounded_rectangle([PAD-4,y+5,W-PAD+4,y+H-5], radius=12, fill=C['card'])
        d.rounded_rectangle([PAD-4,y+5,W-PAD+4,y+H-5], radius=12, outline=col)
        # Left accent bar
        d.rounded_rectangle([PAD-4,y+5,PAD+2,y+H-5], radius=3, fill=col)
        cy = y + H//2
        # Symbol + Hebrew name
        d.text((PAD+18, cy-28), sym,            font=F['bd_l'], fill=col)
        d.text((PAD+18, cy+10), hb(name_he),    font=F['sm'],   fill=C['muted'])
        # Price (adaptive) + change — right-aligned
        ps   = fv(val, 0)
        cs   = fc(chg)
        rz   = W - PAD - 12
        avail = rz - (PAD + 250)
        fp   = fit_font(d, ps, F, avail-10, ['bd_xl','bd_l','bd_m','bd'])
        fc2  = F['bd']
        psw  = int(tw(d,ps,fp)); csw = int(tw(d,cs,fc2))
        d.text((rz-psw, cy-30), ps, font=fp,  fill=C['white'])
        d.text((rz-csw, cy+16), cs, font=fc2, fill=cc(chg))
    cv.push(H, fn)

# ── FEAR & GREED BAR ───────────────────────────────────────────────────
def d_fng_bar(cv, score, prev, rating, F):
    H = 96
    BW = W - PAD*2
    HE_RATINGS = {"Extreme Fear":hb("פחד קיצוני"),"Fear":hb("פחד"),
                  "Neutral":hb("ניטרלי"),"Greed":hb("חמדנות"),
                  "Extreme Greed":hb("חמדנות קיצונית")}
    def fn(img, d, y):
        d.rounded_rectangle([PAD-4,y+4,W-PAD+4,y+H-4], radius=12, fill=C['card'])
        sc    = score or 0
        fc_   = C['red'] if sc<25 else C['yellow'] if sc<45 else C['green'] if sc<75 else C['red']
        label = HE_RATINGS.get(rating, rating or "—")
        # Left: title + Hebrew rating (draw Hebrew and "CNN" separately to avoid bidi mixing)
        title_he = hb("פחד וחמדנות")
        d.text((PAD+14, y+10), title_he, font=F['bd'], fill=C['white'])
        thw = int(tw(d, title_he, F['bd']))
        d.text((PAD+14+thw+10, y+10), "— CNN", font=F['bd'], fill=C['muted'])
        d.text((PAD+14, y+46), label,  font=F['semi'], fill=fc_)
        if prev:
            d.text((PAD+14, y+H-22), f"prev close: {prev}", font=F['xs'], fill=C['muted'])
        # Right: big score
        sc_s = str(score) if score else "—"
        sw   = int(tw(d,sc_s,F['bd_xl']))
        d.text((W-PAD-sw-14, y+8), sc_s, font=F['bd_xl'], fill=fc_)
        # Gradient bar
        bx, by = PAD+14, y+H-20; bl = BW-28; bh = 11
        for xi in range(bl):
            t = xi/bl
            r = int(239*(1-t)+34*t); g = int(68*(1-t)+197*t); b_ = int(68*(1-t)+94*t)
            d.rectangle([(bx+xi,by),(bx+xi+1,by+bh)], fill=(r,g,b_))
        # Dot
        if score:
            ix = bx + int((score/100)*bl)
            d.ellipse([ix-7,by-4,ix+7,by+bh+4], fill=C['white'])
    cv.push(H, fn)

# ── COMMODITY GRID (3-col cards with Hebrew labels) ────────────────────
def d_commodity_grid(cv, commodities, F, cols=3):
    gap    = 10
    card_w = (W - PAD*2 - gap*(cols-1)) // cols
    card_h = 90
    rows   = math.ceil(len(commodities)/cols)
    total_h = rows*(card_h+gap) + 12

    def fn(img, d, y):
        for i,(label,val,chg) in enumerate(commodities):
            col = i % cols; row = i // cols
            cx1 = PAD + col*(card_w+gap)
            cy1 = y + 6 + row*(card_h+gap)
            is_pos = (chg or 0) >= 0
            d.rounded_rectangle([cx1,cy1,cx1+card_w,cy1+card_h],
                                 radius=9, fill=C['card2'])
            d.rounded_rectangle([cx1,cy1,cx1+card_w,cy1+card_h],
                                 radius=9, outline=C['border'])
            mid = cx1 + card_w//2
            # Hebrew label
            safe_lbl = hb(label) if any('א'<=c<='ת' for c in label) else label
            lw = int(tw(d,safe_lbl,F['xs']))
            d.text((mid-lw//2, cy1+8), safe_lbl, font=F['xs'], fill=C['muted'])
            # Value
            vf = fit_font(d,val,F,card_w-14,['bd','semi','base','sm'])
            vw = int(tw(d,val,vf))
            d.text((mid-vw//2, cy1+28), val, font=vf, fill=C['white'])
            # % change pill
            cs   = fc(chg); csw = int(tw(d,cs,F['xs']))
            px1  = mid - csw//2 - 7
            edge = C['green'] if is_pos else C['red']
            d.rounded_rectangle([px1, cy1+64, px1+csw+14, cy1+82],
                                 radius=4, fill=edge)
            d.text((px1+7, cy1+65), cs, font=F['xs'], fill=C['white'])
    cv.push(total_h, fn)

# ── FX / BONDS STATS STRIP ─────────────────────────────────────────────
def d_stats(cv, stats, F):
    N = len(stats); gap = 8
    bw = (W-PAD*2-gap*(N-1))//N; H = 106
    def fn(img, d, y):
        for i,(lbl,val,chg) in enumerate(stats):
            x = PAD+i*(bw+gap); x2 = x+bw
            d.rounded_rectangle([x,y+5,x2,y+H-5], radius=9, fill=C['card2'])
            d.rounded_rectangle([x,y+5,x2,y+H-5], radius=9, outline=C['border'])
            cx = (x+x2)//2
            safe_lbl = hb(lbl) if any('א'<=c<='ת' for c in lbl) else lbl
            fl = fit_font(d,safe_lbl,F,bw-12,['xs','xs'])
            lw = int(tw(d,safe_lbl,fl))
            d.text((cx-lw//2, y+12), safe_lbl, font=fl, fill=C['muted'])
            fv2 = fit_font(d,val,F,bw-12,['bd','semi','base','sm'])
            vw  = int(tw(d,val,fv2))
            d.text((cx-vw//2, y+36), val, font=fv2, fill=C['white'])
            if chg is not None:
                cs  = fc(chg); csw = int(tw(d,cs,F['xs']))
                d.text((cx-csw//2, y+74), cs, font=F['xs'], fill=cc(chg))
    cv.push(H, fn)

# ── STOCK ROW WITH PERFORMANCE BAR ─────────────────────────────────────
def d_stock_row(cv, label, val, chg, F, h=56, alt=False):
    def fn(img, d, y):
        if alt: d.rectangle([(0,y),(W,y+h)], fill=(19,23,33))
        cy = y + h//2

        # Side performance bar (6px wide strip on far left)
        is_pos = (chg or 0) >= 0
        bar_col = C['green'] if is_pos else C['red']
        bar_frac = min(abs(chg or 0)/10.0, 1.0)
        bar_full = h - 10
        bar_h = max(4, int(bar_frac * bar_full))
        bar_y_top = cy - bar_h//2
        d.rectangle([(4, bar_y_top),(10, bar_y_top+bar_h)], fill=bar_col)

        # Label
        d.text((PAD+4, cy-12), label, font=F['base'], fill=C['text'])

        # Value + change right-aligned
        chg_str = fc(chg); cw = int(tw(d,chg_str,F['semi']))
        vw      = int(tw(d,val,F['bd']))
        d.text((W-PAD-cw,        cy-12), chg_str, font=F['semi'], fill=cc(chg))
        d.text((W-PAD-cw-vw-22,  cy-12), val,     font=F['bd'],   fill=C['white'])
        d.line([(PAD,y+h-1),(W-PAD,y+h-1)], fill=C['border'])
    cv.push(h, fn)

# ── EARNINGS TABLE ─────────────────────────────────────────────────────
def d_earn_header_row(cv, F):
    H = 32
    def fn(img, d, y):
        d.rectangle([(0,y),(W,y+H)], fill=C['card2'])
        d.text((PAD,     y+8), hb("מניה / חברה"),       font=F['xs'], fill=C['muted'])
        d.text((PAD+270, y+8), hb("רווח למניה"),        font=F['xs'], fill=C['muted'])
        d.text((PAD+460, y+8), hb("הכנסות"),             font=F['xs'], fill=C['muted'])
        d.text((PAD+640, y+8), hb("הפתעה"),              font=F['xs'], fill=C['muted'])
        d.text((PAD+790, y+8), hb("תגובת מניה"),        font=F['xs'], fill=C['muted'])
        d.line([(0,y+H-1),(W,y+H-1)], fill=C['border'])
    cv.push(H, fn)

def _beat_badge(d, x, y, beat, F):
    if beat is None: return
    col = C['green'] if beat else C['red']
    txt = hb("הכה") if beat else hb("החטיא")
    tw_ = int(tw(d,txt,F['xs']))
    d.rounded_rectangle([x,y,x+tw_+10,y+20], radius=3, fill=col)
    d.text((x+5,y+2), txt, font=F['xs'], fill=C['white'])

def d_earn_row(cv, e, F, alt=False):
    H = 86
    def fn(img, d, y):
        if alt: d.rectangle([(0,y),(W,y+H)], fill=(19,23,33))

        # ── Timing badge + Ticker + Name ───────────────────────────────
        t_he  = hb("לפני פתיחה") if e['timing']=='PRE' else hb("אחרי סגירה")
        t_col = C['blue'] if e['timing']=='PRE' else C['yellow']
        tw_   = int(tw(d,t_he,F['xs']))
        d.rounded_rectangle([PAD,y+8,PAD+tw_+14,y+28], radius=4, fill=t_col)
        d.text((PAD+7,y+10), t_he, font=F['xs'], fill=C['white'])

        d.text((PAD, y+32), e['ticker'], font=F['bd'],  fill=C['white'])
        d.text((PAD, y+64), e['name'],   font=F['xs'],  fill=C['muted'])

        # ── EPS (x=PAD+270) ────────────────────────────────────────────
        EX = PAD+270
        if e['reported']:
            ea_s = f"${e['eps_actual']:.2f}" if e['eps_actual'] is not None else "—"
            ee_s = f"צפי ${e['eps_est']:.2f}" if e['eps_est'] else ""
            d.text((EX, y+12), ea_s, font=F['bd'],   fill=C['white'])
            d.text((EX, y+46), hb(ee_s), font=F['xs'], fill=C['muted'])
            _beat_badge(d, EX, y+66, e['beat_eps'], F)
        else:
            ep_s = hb(f"צפי ${e['eps_est']:.2f}") if e['eps_est'] else hb("טרם דיווח")
            d.text((EX, y+30), ep_s, font=F['sm'], fill=C['muted'])

        # ── Revenue (x=PAD+460) ────────────────────────────────────────
        RX = PAD+460
        if e['reported'] and e['rev_actual'] is not None:
            rv   = e['rev_actual']
            ra_s = f"${rv/1e9:.2f}B" if rv>=1e9 else f"${rv/1e6:.0f}M"
            re_s = (f"צפי ${e['rev_est']/1e9:.1f}B" if e['rev_est'] and e['rev_est']>=1e9
                    else f"צפי ${e['rev_est']/1e6:.0f}M" if e['rev_est'] else "")
            d.text((RX, y+12), ra_s,    font=F['bd'],  fill=C['white'])
            d.text((RX, y+46), hb(re_s),font=F['xs'],  fill=C['muted'])
            _beat_badge(d, RX, y+66, e['beat_rev'], F)
        elif e['rev_est']:
            re_s = (f"צפי ${e['rev_est']/1e9:.1f}B" if e['rev_est']>=1e9
                    else f"צפי ${e['rev_est']/1e6:.0f}M")
            d.text((RX, y+30), hb(re_s), font=F['sm'], fill=C['muted'])

        # ── Surprise% (x=PAD+640) ──────────────────────────────────────
        SX = PAD+640
        if e['surprise'] is not None:
            sc = C['green'] if e['surprise']>=0 else C['red']
            ss = f"{'+'if e['surprise']>=0 else ''}{e['surprise']:.1f}%"
            d.text((SX, y+20), ss, font=F['bd_m'], fill=sc)

        # ── Stock Reaction — prominent right side ───────────────────────
        REACT_X = PAD+790
        sr = e.get('stock_reaction')
        sp = e.get('stock_price')
        pm = e.get('pre_mkt_chg')
        if sr is not None:
            r_col = C['green'] if sr>=0 else C['red']
            r_str = f"{'▲' if sr>=0 else '▼'} {abs(sr):.2f}%"
            fr    = fit_font(d,r_str,F,W-REACT_X-PAD,['bd_l','bd_m','bd','semi'])
            rw    = int(tw(d,r_str,fr))
            d.text((W-PAD-rw, y+14), r_str, font=fr, fill=r_col)
            if sp:
                lbl = f"${sp:,.2f}"
                if pm is not None:
                    lbl += f"  pre:{'+' if pm>=0 else ''}{pm:.1f}%"
                lw = int(tw(d,lbl,F['xs']))
                d.text((W-PAD-lw, y+60), lbl, font=F['xs'], fill=C['muted'])
            react_lbl = hb("AH") if e['timing']=='AFTER' else hb("PRE")
            if e.get('reported'):
                rlw = int(tw(d,react_lbl,F['xs']))
                d.rounded_rectangle([W-PAD-rlw-10,y+6,W-PAD,y+24],
                                     radius=3, fill=r_col)
                d.text((W-PAD-rlw-5, y+8), react_lbl, font=F['xs'], fill=C['white'])
        else:
            d.text((REACT_X, y+30), "—", font=F['bd'], fill=C['muted'])

        d.line([(0,y+H-1),(W,y+H-1)], fill=C['border'])
    cv.push(H, fn)

# ── TRENDING STOCKS ────────────────────────────────────────────────────
def d_trending_row(cv, t, F, alt=False):
    H = 60
    def fn(img, d, y):
        if alt:
            d.rectangle([(0,y),(W,y+H)], fill=C['dim'])
        cy = y + H//2

        # Left bar — height proportional to volume ratio (max 8x)
        is_pos = (t['chg'] or 0) >= 0
        bar_col = C['green'] if is_pos else C['red']
        frac = min(t['ratio'] / 8.0, 1.0)
        bh = max(6, int(frac * (H-10)))
        d.rectangle([(4, cy-bh//2),(10, cy+bh//2)], fill=bar_col)

        # Ticker (bold)
        d.text((PAD+4, cy-18), t['ticker'], font=F['bd'], fill=C['white'])

        # Volume ratio pill
        ratio_txt = f"{t['ratio']}x"
        rtw = int(tw(d, ratio_txt, F['xs']))
        rx1 = PAD + 4
        d.rounded_rectangle([rx1, cy+4, rx1+rtw+12, cy+20],
                             radius=3, fill=C['card2'])
        d.text((rx1+6, cy+5), ratio_txt, font=F['xs'], fill=C['blue'])

        # Price
        price_s = f"${t['price']:,.2f}"
        pw = int(tw(d, price_s, F['semi']))
        d.text((W//2 - pw//2, cy-14), price_s, font=F['semi'], fill=C['white'])

        # % change
        chg_s = fc(t['chg'])
        cw_ = int(tw(d, chg_s, F['bd']))
        d.text((W-PAD-cw_, cy-14), chg_s, font=F['bd'], fill=cc(t['chg']))

        # Market cap small label
        mc = t['mc']
        if not mc:
            mc_s = "—"
        elif mc >= 1e12:
            mc_s = f"${mc/1e12:.1f}T"
        else:
            mc_s = f"${mc/1e9:.0f}B"
        mcw = int(tw(d, mc_s, F['xs']))
        d.text((W-PAD-mcw, cy+6), mc_s, font=F['xs'], fill=C['muted'])

        d.line([(PAD,y+H-1),(W-PAD,y+H-1)], fill=C['border'])
    cv.push(H, fn)

def d_trending_header_row(cv, F):
    H = 28
    def fn(img, d, y):
        d.rectangle([(0,y),(W,y+H)], fill=C['card2'])
        d.text((PAD+4,   y+6), hb("מניה"),           font=F['xs'], fill=C['muted'])
        mid = W//2
        mw = int(tw(d, hb("מחיר"), F['xs']))
        d.text((mid-mw//2, y+6), hb("מחיר"),         font=F['xs'], fill=C['muted'])
        chgh = hb("שינוי %")
        chgw = int(tw(d, chgh, F['xs']))
        d.text((W-PAD-chgw-90, y+6), chgh,           font=F['xs'], fill=C['muted'])
        mch = hb("שווי שוק")
        mcw = int(tw(d, mch, F['xs']))
        d.text((W-PAD-mcw, y+6), mch,                font=F['xs'], fill=C['muted'])
        d.line([(0,y+H-1),(W,y+H-1)], fill=C['border'])
    cv.push(H, fn)

# ── FOOTER ─────────────────────────────────────────────────────────────
def d_footer(cv, today, F):
    H = 52
    def fn(img, d, y):
        d.line([(0,y),(W,y)], fill=C['border'])
        ft  = f"yfinance · CNN Fear&Greed  |  {today.strftime('%d.%m.%Y %H:%M')}  |  "
        ft2 = hb("לצרכי מידע בלבד — אינו ייעוץ השקעות")
        fw  = int(tw(d,ft,F['xs'])) + int(tw(d,ft2,F['xs']))
        sx  = (W - fw)//2
        d.text((sx, y+16), ft, font=F['xs'], fill=C['muted'])
        d.text((sx + int(tw(d,ft,F['xs'])), y+16), ft2, font=F['xs'], fill=C['muted'])
    cv.push(H, fn)

# ── MINI HEADER (image 2) ───────────────────────────────────────────────
def d_mini_header(cv, today, F, mode="pre"):
    H = 64
    mini_title = "חדשות הבוקר"  if mode == "pre" else "עדכון אמצע יום"
    mini_tag   = "לפני פתיחה"   if mode == "pre" else "אמצע יום"
    tag_col    = C['blue']       if mode == "pre" else C['yellow']
    day_he, date_str, time_str = he_date_parts(today)
    def fn(img, d, y):
        d.rectangle([(0,y),(W,y+H)], fill=C['card'])
        d.line([(0,y+H-1),(W,y+H-1)], fill=C['border'])
        t   = hb(mini_title)
        d.text((PAD, y+12), t, font=F['bd_m'], fill=C['white'])
        tag = hb(mini_tag)
        tw_ = int(tw(d,tag,F['xs']))
        bx  = int(PAD + tw(d,t,F['bd_m']) + 16)
        d.rounded_rectangle([bx, y+16, bx+tw_+16, y+40], radius=5, fill=tag_col)
        d.text((bx+8, y+19), tag, font=F['xs'], fill=C['white'])
        # Date right
        ts  = f"{day_he}  ·  {date_str}  ·  {time_str}"
        tsw = int(tw(d,ts,F['xs']))
        d.text((W-PAD-tsw, y+22), ts, font=F['xs'], fill=C['muted'])
    cv.push(H, fn)

# ══════════════════════════════════════════════
#  9. BUILD IMAGES
# ══════════════════════════════════════════════
def build_images(md, earnings, news, fg, today, mode="pre", trending=None):
    F = fonts()
    m = md

    # ════════════════════════════════════════
    #  IMAGE 1 — שוק, קריפטו, סחורות, FX
    # ════════════════════════════════════════
    cv1 = Canvas()
    d_header(cv1, today, m['sp500']['val'], m['sp500']['chg'], fg, F, mode=mode)

    # — מדדים (Indices grid) —
    d_section(cv1, "מדדים", F, accent=C['blue'])
    d_index_grid(cv1, [
        ("S&P 500",      fv(m['sp500']['val'],  2,''), m['sp500']['chg']),
        ("נאסד\"ק",      fv(m['nasdaq']['val'], 2,''), m['nasdaq']['chg']),
        ("דאו ג'ונס",    fv(m['dji']['val'],    2,''), m['dji']['chg']),
        ("ראסל 2000",    fv(m['russell']['val'],2,''), m['russell']['chg']),
        ("VIX",          fv(m['vix']['val'],    1,''), m['vix']['chg']),
        ("QQQ",          fv(m['qqq']['val'],    2,'$'),m['qqq']['chg']),
        ("SPY",          fv(m['spy']['val'],    2,'$'),m['spy']['chg']),
    ], F, cols=3)

    # — קריפטו —
    cv1.sp(6)
    d_section(cv1, "קריפטו  ₿", F, accent=C['btc'])
    d_crypto(cv1, "BTC",  "ביטקוין",  m['btc']['val'], m['btc']['chg'], C['btc'], F)
    cv1.sp(8)
    d_crypto(cv1, "ETH",  "את'ריום", m['eth']['val'], m['eth']['chg'], C['eth'], F)
    cv1.sp(8)
    d_index_grid(cv1, [
        ("Solana (SOL)", fv(m['sol']['val'],1,'$'), m['sol']['chg']),
        ("BNB",          fv(m['bnb']['val'],1,'$'), m['bnb']['chg']),
    ], F, cols=2)

    # — פחד וחמדנות —
    cv1.sp(4)
    d_fng_bar(cv1, fg[0], fg[2], fg[1], F)

    # — סחורות (Commodity grid) —
    cv1.sp(4)
    d_section(cv1, "סחורות", F, accent=C['yellow'])
    d_commodity_grid(cv1, [
        ("נפט WTI",  fv(m['wti']['val'],  2,'$'), m['wti']['chg']),
        ("נפט ברנט", fv(m['brent']['val'],2,'$'), m['brent']['chg']),
        ("זהב",      fv(m['gold']['val'],  0,'$'), m['gold']['chg']),
        ("כסף",      fv(m['silver']['val'],2,'$'), m['silver']['chg']),
        ("נחושת",    fv(m['copper']['val'],3,'$'), m['copper']['chg']),
    ], F, cols=3)

    # — מטבע חוץ ואגרות חוב —
    cv1.sp(6)
    d_section(cv1, "מטבע חוץ ואגרות חוב", F, accent=C['muted'])
    d_stats(cv1, [
        ("מדד דולר",  fv(m['dxy']['val'],  2,''), m['dxy']['chg']),
        ("EUR/USD",   fv(m['eurusd']['val'],4,''),m['eurusd']['chg']),
        ("דולר/ין",   fv(m['usdjpy']['val'],2,''),m['usdjpy']['chg']),
        ("דולר/שקל",  fv(m['usdils']['val'],3,''),m['usdils']['chg']),
        ("ריבית 10Y", fv(m['tnx']['val'],  3,''), m['tnx']['chg']),
        ("ריבית 30Y", fv(m['tyx']['val'],  3,''), m['tyx']['chg']),
    ], F)

    d_footer(cv1, today, F)
    img1 = cv1.render()

    # ════════════════════════════════════════
    #  IMAGE 2 — מניות טכ' + דוחות תוצאות
    # ════════════════════════════════════════
    cv2 = Canvas()
    d_mini_header(cv2, today, F, mode=mode)

    # — מניות טכנולוגיה —
    d_section(cv2, "מניות טכנולוגיה  —  Mag 7", F, accent=C['blue'])
    stocks = [
        ("NVIDIA  (NVDA)",   fv(m['nvda']['val'],  2,'$'), m['nvda']['chg']),
        ("Broadcom (AVGO)",  fv(m['avgo']['val'],  2,'$'), m['avgo']['chg']),
        ("Microsoft (MSFT)", fv(m['msft']['val'],  2,'$'), m['msft']['chg']),
        ("Apple  (AAPL)",    fv(m['aapl']['val'],  2,'$'), m['aapl']['chg']),
        ("Meta  (META)",     fv(m['meta']['val'],  2,'$'), m['meta']['chg']),
        ("Alphabet (GOOGL)", fv(m['googl']['val'], 2,'$'), m['googl']['chg']),
        ("Amazon  (AMZN)",   fv(m['amzn']['val'],  2,'$'), m['amzn']['chg']),
        ("Tesla  (TSLA)",    fv(m['tsla']['val'],  2,'$'), m['tsla']['chg']),
    ]
    for i,(l,v,c) in enumerate(stocks):
        d_stock_row(cv2, l, v, c, F, h=54, alt=bool(i%2))

    # — מניות טרנד — ווליום גבוה מהרגיל —
    cv2.sp(10)
    d_section(cv2, "מניות חמות — ווליום גבוה מהממוצע", F, top=12, accent=C['yellow'])
    if trending:
        d_trending_header_row(cv2, F)
        for i, t in enumerate(trending):
            d_trending_row(cv2, t, F, alt=bool(i % 2))
    else:
        def no_trend(img, d, y):
            d.text((PAD, y+16), hb("לא נמצאו מניות עם ווליום חריג"), font=F['base'], fill=C['muted'])
        cv2.push(52, no_trend)

    # — דוחות תוצאות —
    cv2.sp(10)
    earn_lbl = ("דוחות תוצאות — לפני ואחרי סגירה"
                if mode == "pre"
                else "דוחות תוצאות  ·  עדכון + צפי מחר")
    d_section(cv2, earn_lbl, F, top=12, accent=C['green'])

    if earnings:
        d_earn_header_row(cv2, F)
        pre  = [e for e in earnings if e['timing']=='PRE']
        post = [e for e in earnings if e['timing']=='AFTER']
        for grp_he, grp in [(hb("לפני פתיחה"), pre),
                             (hb("אחרי סגירה / דווח"), post)]:
            if not grp: continue
            def _gl(img, d, y, lbl=grp_he):
                d.rectangle([(0,y),(W,y+28)], fill=(18,22,35))
                lw = int(tw(d,lbl,F['xs']))
                d.text((W-PAD-lw, y+7), lbl, font=F['xs'], fill=C['blue'])
            cv2.push(28, _gl)
            for i,e in enumerate(grp):
                d_earn_row(cv2, e, F, alt=bool(i%2))
    else:
        def no_earn(img, d, y):
            msg = hb("לא נמצאו דיווחי תוצאות לשעות אלו")
            d.text((PAD, y+18), msg, font=F['base'], fill=C['muted'])
        cv2.push(58, no_earn)

    d_footer(cv2, today, F)
    img2 = cv2.render()
    return [img1, img2]

# ══════════════════════════════════════════════
#  9. SAVE + SEND
# ══════════════════════════════════════════════
def save_images(images, today):
    saved = []
    ds = today.strftime('%Y-%m-%d')
    for i, img in enumerate(images, 1):
        fname = f"morning-news-{ds}-{i}.png"
        fpath = os.path.join(SAVE_DIR, fname)
        img.save(fpath, 'PNG', optimize=True)
        print(f"  ✅ Saved: {fname}  ({img.size[0]}×{img.size[1]})")
        saved.append((fpath, fname))
    return saved

def send_email(images, saved, today, mode="pre"):
    if mode == "pre":
        subj = f"📰 חדשות הבוקר — לפני פתיחה — {today.strftime('%d.%m.%Y %H:%M')}"
    else:
        subj = f"📈 עדכון אמצע יום — {today.strftime('%d.%m.%Y %H:%M')}"
    msg = MIMEMultipart('related')
    msg['From'] = GMAIL_USER; msg['To'] = TO_EMAIL; msg['Subject'] = subj

    if mode == "pre":
        email_title = "📰 חדשות הבוקר — לפני פתיחה"
        email_color = "#3b82f6"
    else:
        email_title = "📈 עדכון אמצע יום"
        email_color = "#f59e0b"

    html = f"""
    <html dir="rtl"><body style="margin:0;padding:0;background:#0f1117;font-family:Arial">
      <div style="max-width:600px;margin:0 auto;padding:12px">
        <div style="background:#161b27;border:1px solid #2a3447;border-radius:12px;padding:16px 20px;margin-bottom:12px">
          <h2 style="color:{email_color};margin:0 0 4px">{email_title}</h2>
          <p style="color:#8899aa;font-size:12px;margin:0">{today.strftime('%A · %d.%m.%Y · %H:%M')}</p>
        </div>
        <img src="cid:img1" style="width:100%;border-radius:10px;display:block;margin-bottom:10px"/>
        <img src="cid:img2" style="width:100%;border-radius:10px;display:block;margin-bottom:10px"/>
        <p style="color:#4b5563;font-size:10px;text-align:center">
          לצרכי מידע בלבד · yfinance · CNN Fear&amp;Greed · אינו ייעוץ השקעות
        </p>
      </div>
    </body></html>"""

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText("חדשות הבוקר — פתח ב-HTML.", 'plain', 'utf-8'))
    alt.attach(MIMEText(html, 'html', 'utf-8'))
    msg.attach(alt)

    for i, (img, (path, fname)) in enumerate(zip(images, saved), 1):
        buf = BytesIO(); img.save(buf,'PNG'); buf.seek(0)
        mi = MIMEImage(buf.read(),'png')
        mi.add_header('Content-ID', f'<img{i}>')
        mi.add_header('Content-Disposition', 'inline', filename=fname)
        msg.attach(mi)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASSWORD)
        s.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"  ✅ Email sent → {TO_EMAIL}")

# ══════════════════════════════════════════════
#  10. MAIN
# ══════════════════════════════════════════════
def main():
    today = datetime.datetime.now()
    mode_label = "לפני פתיחה" if MODE == "pre" else "אמצע יום"
    print(f"📰 חדשות הבוקר [{mode_label}] — {today.strftime('%d.%m.%Y %H:%M')}")
    print(f"   Mode: {MODE}")
    print("─"*52)

    print("📊 Market data...")
    md = get_market_data()
    print(f"  S&P:{md['sp500']['val']}  BTC:${md['btc']['val']:,.0f}  ETH:${md['eth']['val']:,.0f}"
          if md['btc']['val'] else f"  S&P:{md['sp500']['val']}")

    print("🌡️ CNN Fear & Greed...")
    fg = get_fear_greed()
    print(f"  Score:{fg[0]}  Rating:{fg[1]}  Prev:{fg[2]}")

    print("📋 Earnings calendar...")
    earnings = get_earnings_today(mode=MODE)

    print("🔥 Trending stocks by volume...")
    trending = get_trending_stocks(n=12)

    print("📰 News RSS...")
    news = get_news()
    print(f"  {len(news)} headlines")

    print("🎨 Building infographic images...")
    images = build_images(md, earnings, news, fg, today, mode=MODE, trending=trending)
    print(f"  Image 1: {images[0].size}  Image 2: {images[1].size}")

    print("💾 Saving...")
    saved = save_images(images, today)

    print("📧 Sending email...")
    send_email(images, saved, today, mode=MODE)

    print("─"*52)
    print("✅ Done!")

if __name__ == "__main__":
    main()
