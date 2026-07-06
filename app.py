#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
חדשות הבוקר — Flask Web App
PWA with live market data, auto-refresh, installable on iPhone
"""
import os, sys, threading, time, datetime, json
from flask import Flask, jsonify, render_template, send_from_directory, request

# ── ngrok config ──────────────────────────────────────────────────────────────
# Set your ngrok authtoken here (free at https://dashboard.ngrok.com/get-started/your-authtoken)
# Leave empty to run local-only
NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from morning_report import (get_market_data, get_fear_greed,
                             get_earnings_today, get_news, get_trending_stocks,
                             get_economic_events, get_social_mentions,
                             analyze_ticker)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['JSON_ENSURE_ASCII'] = False

import math as _math
from flask.json.provider import DefaultJSONProvider

class _NaNSafeProvider(DefaultJSONProvider):
    def dumps(self, obj, **kw):
        import json
        def _fix(o):
            if isinstance(o, float) and (_math.isnan(o) or _math.isinf(o)):
                return None
            if isinstance(o, dict):
                return {k: _fix(v) for k, v in o.items()}
            if isinstance(o, list):
                return [_fix(i) for i in o]
            return o
        return json.dumps(_fix(obj), ensure_ascii=False, **kw)

app.json_provider_class = _NaNSafeProvider
app.json = _NaNSafeProvider(app)

# ══════════════════════════════════════════════════
#  DATA CACHE
# ══════════════════════════════════════════════════
_cache = {
    'market'          : None,
    'fg'              : (None, None, None),
    'earnings'        : [],
    'news'            : [],
    'trending'        : [],
    'economic'        : [],
    'last_market'     : None,
    'last_earnings'   : None,
    'last_trending'   : None,
    'last_economic'   : None,
    'earnings_loading': True,
    'trending_loading': True,
    'economic_loading': True,
    'social'          : [],
    'last_social'     : None,
    'social_loading'  : True,
    'signals'         : [],
}
_lock = threading.Lock()

# ── TradingView webhook signals ───────────────────
# Signals arrive as webhooks from TradingView alerts, get enriched with a
# technical analysis snapshot, and persist to a JSON file (survives restarts
# locally; on Render's free tier the disk is ephemeral, so a redeploy clears it).
SIGNALS_FILE      = os.path.join(BASE, 'signals.json')
TV_WEBHOOK_SECRET = os.environ.get('TV_WEBHOOK_SECRET', '')
MAX_SIGNALS       = 100

def _load_signals():
    try:
        with open(SIGNALS_FILE, encoding='utf-8') as f:
            _cache['signals'] = json.load(f)[:MAX_SIGNALS]
        print(f"Loaded {len(_cache['signals'])} saved signals")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Signals load error: {e}")

def _save_signals_locked():
    """Write signals to disk. Caller must hold _lock."""
    try:
        with open(SIGNALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache['signals'], f, ensure_ascii=False)
    except Exception as e:
        print(f"Signals save error: {e}")

def _enrich_signal(sig_id, ticker):
    """Attach a technical-analysis snapshot to a signal (runs in background)."""
    analysis = analyze_ticker(ticker)
    with _lock:
        for s in _cache['signals']:
            if s.get('id') == sig_id:
                s['analysis'] = analysis
                break
        _save_signals_locked()

_load_signals()

# Small TTL cache so repeated on-demand analysis doesn't hammer Yahoo
_analyze_cache = {}   # sym -> (result, timestamp)
ANALYZE_TTL = 300

def _refresh_market():
    """Refresh market data every 5 minutes."""
    while True:
        try:
            md   = get_market_data()
            fg   = get_fear_greed()
            news = get_news()
            with _lock:
                _cache['market']      = md
                _cache['fg']          = fg
                _cache['news']        = news
                _cache['last_market'] = datetime.datetime.now()
            print(f"[{datetime.datetime.now():%H:%M:%S}] Market data refreshed")
        except Exception as e:
            print(f"Market refresh error: {e}")
        time.sleep(300)   # 5 min

def _refresh_trending():
    """Refresh trending/volume stocks every 30 minutes."""
    time.sleep(20)   # stagger: let the market load settle before this heavy scan
    while True:
        try:
            with _lock:
                _cache['trending_loading'] = True
            data = get_trending_stocks(n=15)
            with _lock:
                _cache['trending']         = data
                _cache['last_trending']    = datetime.datetime.now()
                _cache['trending_loading'] = False
            print(f"[{datetime.datetime.now():%H:%M:%S}] Trending refreshed: {len(data)} stocks")
        except Exception as e:
            print(f"Trending refresh error: {e}")
            with _lock:
                _cache['trending_loading'] = False
        time.sleep(1800)  # 30 min

def _refresh_economic():
    """Refresh economic calendar every 3 hours."""
    while True:
        try:
            with _lock:
                _cache['economic_loading'] = True
            data = get_economic_events()
            with _lock:
                _cache['economic']         = data
                _cache['last_economic']    = datetime.datetime.now()
                _cache['economic_loading'] = False
            print(f"[{datetime.datetime.now():%H:%M:%S}] Economic events refreshed: {len(data)} events")
        except Exception as e:
            print(f"Economic refresh error: {e}")
            with _lock:
                _cache['economic_loading'] = False
        time.sleep(10800)  # 3 h

def _refresh_earnings():
    """Refresh earnings calendar every 60 minutes."""
    while True:
        try:
            with _lock:
                _cache['earnings_loading'] = True
            data = get_earnings_today()
            with _lock:
                _cache['earnings']         = data
                _cache['last_earnings']    = datetime.datetime.now()
                _cache['earnings_loading'] = False
            print(f"[{datetime.datetime.now():%H:%M:%S}] Earnings refreshed: {len(data)} companies")
        except Exception as e:
            print(f"Earnings refresh error: {e}")
            with _lock:
                _cache['earnings_loading'] = False
        time.sleep(3600)  # 60 min

def _refresh_social():
    """Refresh social mentions every 30 minutes."""
    time.sleep(15)
    while True:
        try:
            with _lock:
                _cache['social_loading'] = True
            data = get_social_mentions(n=20)
            with _lock:
                _cache['social']         = data
                _cache['last_social']    = datetime.datetime.now()
                _cache['social_loading'] = False
            print(f"[{datetime.datetime.now():%H:%M:%S}] Social mentions refreshed: {len(data)} stocks")
        except Exception as e:
            print(f"Social refresh error: {e}")
            with _lock:
                _cache['social_loading'] = False
        time.sleep(1800)  # 30 min

# ── Initial synchronous load ──────────────────────
def _initial_load():
    print("⏳ Loading initial market data...")
    _cache['market']      = get_market_data()
    _cache['fg']          = get_fear_greed()
    _cache['news']        = get_news()
    _cache['last_market'] = datetime.datetime.now()
    print("✅ Initial market data ready")
    # Start background threads — trending runs first pass immediately inside _refresh_trending
    threading.Thread(target=_refresh_market,   daemon=True, name="mkt").start()
    threading.Thread(target=_refresh_earnings, daemon=True, name="earn").start()
    threading.Thread(target=_refresh_trending, daemon=True, name="trend").start()
    threading.Thread(target=_refresh_economic, daemon=True, name="econ").start()
    threading.Thread(target=_refresh_social,   daemon=True, name="social").start()
    threading.Thread(target=_keep_alive,       daemon=True, name="ping").start()

def _keep_alive():
    """Ping ourselves every 13 minutes so Render free tier doesn't sleep."""
    import urllib.request
    time.sleep(60)
    url = os.environ.get('RENDER_EXTERNAL_URL', '')
    if not url:
        return
    url = url.rstrip('/') + '/api/status'
    while True:
        try:
            urllib.request.urlopen(url, timeout=10)
            print(f"[{datetime.datetime.now():%H:%M:%S}] keep-alive ping OK")
        except Exception:
            pass
        time.sleep(780)  # 13 min

_initial_load()

# ══════════════════════════════════════════════════
#  API ROUTES
# ══════════════════════════════════════════════════
@app.route('/api/market')
def api_market():
    with _lock:
        md   = _cache['market']
        fg   = _cache['fg']
        news = _cache['news']
        last = _cache['last_market']
    if not md:
        return jsonify({'error': 'Loading...'}), 503
    return jsonify({
        'market'     : md,
        'fear_greed' : {'score': fg[0], 'rating': fg[1], 'prev': fg[2]},
        'news'       : news,
        'last_update': last.strftime('%H:%M') if last else None,
        'date'       : datetime.datetime.now().strftime('%A · %d.%m.%Y'),
    })

@app.route('/api/earnings')
def api_earnings():
    with _lock:
        data    = _cache['earnings']
        last    = _cache['last_earnings']
        loading = _cache['earnings_loading']
    return jsonify({
        'earnings'   : data,
        'last_update': last.strftime('%H:%M') if last else None,
        'loading'    : loading,
    })

@app.route('/api/trending')
def api_trending():
    import math
    with _lock:
        data    = _cache['trending']
        last    = _cache['last_trending']
        loading = _cache['trending_loading']
    # Strip out any stocks where price or chg slipped through as NaN
    clean = [s for s in (data or [])
             if s.get('price') is not None
             and not (isinstance(s['price'], float) and math.isnan(s['price']))
             and s.get('chg') is not None
             and not (isinstance(s['chg'], float) and math.isnan(s['chg']))]
    return jsonify({
        'trending'   : clean,
        'last_update': last.strftime('%H:%M') if last else None,
        'loading'    : loading,
    })

@app.route('/api/economic')
def api_economic():
    with _lock:
        data    = _cache['economic']
        last    = _cache['last_economic']
        loading = _cache['economic_loading']
    return jsonify({
        'economic'   : data,
        'last_update': last.strftime('%H:%M') if last else None,
        'loading'    : loading,
    })

@app.route('/api/social')
def api_social():
    with _lock:
        data    = _cache['social']
        last    = _cache['last_social']
        loading = _cache['social_loading']
    return jsonify({
        'social'     : data,
        'last_update': last.strftime('%H:%M') if last else None,
        'loading'    : loading,
    })

@app.route('/webhook/tradingview', methods=['POST'])
def tv_webhook():
    """Receives TradingView alert webhooks.
    Alert message should be JSON, e.g.:
    {"secret":"...","ticker":"{{ticker}}","action":"buy","price":{{close}},"message":"פריצה"}
    Plain-text alerts are accepted too (stored as message only)."""
    raw = request.get_data(as_text=True) or ''
    payload = None
    try:
        payload = json.loads(raw)
    except Exception:
        pass
    if not isinstance(payload, dict):
        payload = {}

    secret = payload.get('secret') or request.args.get('secret') or ''
    if TV_WEBHOOK_SECRET and secret != TV_WEBHOOK_SECRET:
        return jsonify({'error': 'bad secret'}), 403

    now    = datetime.datetime.now()
    ticker = str(payload.get('ticker', '')).upper().strip()[:12]
    # TradingView's {{ticker}} can arrive as EXCHANGE:SYMBOL
    if ':' in ticker:
        ticker = ticker.split(':')[-1]
    action = str(payload.get('action', '')).lower().strip()[:10]
    try:
        price = float(payload.get('price')) if payload.get('price') is not None else None
    except (TypeError, ValueError):
        price = None
    message = str(payload.get('message', '') or (raw[:300] if not payload else ''))[:300]

    sig = {
        'id'      : f"{now.timestamp():.6f}",
        'time'    : now.strftime('%d.%m %H:%M'),
        'ts'      : now.isoformat(),
        'ticker'  : ticker,
        'action'  : action,
        'price'   : price,
        'message' : message,
        'analysis': None,
    }
    with _lock:
        _cache['signals'].insert(0, sig)
        del _cache['signals'][MAX_SIGNALS:]
        _save_signals_locked()
    print(f"[{now:%H:%M:%S}] TradingView signal: {ticker} {action} @ {price}")

    # Enrich async so TradingView gets its 200 within its short timeout
    if ticker:
        threading.Thread(target=_enrich_signal, args=(sig['id'], ticker),
                         daemon=True, name="sig-enrich").start()
    return jsonify({'ok': True})

@app.route('/api/signals')
def api_signals():
    with _lock:
        data = list(_cache['signals'])
    return jsonify({
        'signals'   : data,
        'secret_set': bool(TV_WEBHOOK_SECRET),
    })

@app.route('/api/analyze/<sym>')
def api_analyze(sym):
    sym = sym.upper().strip()
    if not sym or len(sym) > 12 or not all(c.isalnum() or c in '.-^=' for c in sym):
        return jsonify({'error': 'invalid ticker'}), 400
    now = time.time()
    cached = _analyze_cache.get(sym)
    if cached and now - cached[1] < ANALYZE_TTL:
        return jsonify({'analysis': cached[0], 'cached': True})
    result = analyze_ticker(sym)
    _analyze_cache[sym] = (result, now)
    if result is None:
        return jsonify({'analysis': None, 'error': 'not found'}), 404
    return jsonify({'analysis': result, 'cached': False})

@app.route('/api/status')
def api_status():
    with _lock:
        lm = _cache['last_market']
        le = _cache['last_earnings']
    return jsonify({
        'market_age_min': int((datetime.datetime.now() - lm).total_seconds()/60) if lm else None,
        'next_market_refresh': '5 min',
        'next_earnings_refresh': '60 min',
    })

# ── Serve App ─────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:p>')
def static_files(p):
    return send_from_directory('static', p)

# ══════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════
if __name__ == '__main__':
    import socket
    host = '0.0.0.0'
    port = int(os.environ.get('PORT', 5050))
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except:
        local_ip = 'localhost'

    # ── ngrok public tunnel ───────────────────────────────────────────────────
    public_url = None
    try:
        from pyngrok import ngrok, conf
        token = NGROK_AUTHTOKEN or os.environ.get("NGROK_AUTHTOKEN", "")
        if not token:
            raise ValueError("No NGROK_AUTHTOKEN set")
        conf.get_default().auth_token = token
        tunnel = ngrok.connect(port, "http")
        public_url = tunnel.public_url.replace("http://", "https://")
    except Exception as e:
        print(f"  [ngrok] Could not start tunnel: {e}")

    url_line  = f"║  Public:  {public_url}" if public_url else "║  (no ngrok token — local only)"
    pad_len   = max(0, 44 - len(url_line))
    url_line  = url_line + " " * pad_len + "║"

    print(f"""
╔══════════════════════════════════════════════╗
║        חדשות הבוקר — Web App                ║
╠══════════════════════════════════════════════╣
║  Local:   http://localhost:{port}              ║
║  Network: http://{local_ip}:{port}        ║
{url_line}
╚══════════════════════════════════════════════╝
""")
    if public_url:
        print(f"  ✅ Share this link: {public_url}\n")
    else:
        print("""  ℹ️  To get a public shareable link:
  1. Sign up free at https://ngrok.com
  2. Copy your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
  3. Run:  set NGROK_AUTHTOKEN=your_token_here
     Then restart:  python app.py
""")

    app.run(host=host, port=port, debug=False, threaded=True)
