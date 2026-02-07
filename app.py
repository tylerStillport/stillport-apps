"""
Stillport Apps Server
=====================
Serves both OutreachFlow and Stillport Fundraise CRM as a single deployment,
plus the email open tracking pixel server.

Routes:
  /                         — Landing page with links to both apps
  /outreach                 — OutreachFlow email campaign app
  /crm                      — Stillport Fundraise CRM
  /track?tid=...&cid=...    — Tracking pixel endpoint
  /events?cids=...          — Open event data
  /health                   — Health check
"""

from flask import Flask, request, Response, jsonify, send_file
from flask_cors import CORS
from datetime import datetime
import json
import os
import threading

app = Flask(__name__)
CORS(app)

# ===== STATIC APP FILES =====
APP_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def index():
    return f"""
    <html>
    <head>
      <title>Stillport Apps</title>
      <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#0f1117; color:#e2e5f0; min-height:100vh; display:flex; align-items:center; justify-content:center; }}
        .container {{ text-align:center; max-width:500px; padding:40px; }}
        h1 {{ font-size:28px; font-weight:700; background:linear-gradient(135deg,#6366f1,#10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:8px; }}
        .sub {{ color:#6b7394; font-size:14px; margin-bottom:32px; }}
        .cards {{ display:flex; gap:16px; justify-content:center; }}
        .card {{ background:#1a1d27; border:1px solid #333850; border-radius:12px; padding:24px; flex:1; text-decoration:none; color:#e2e5f0; transition:all .2s; }}
        .card:hover {{ border-color:#6366f1; transform:translateY(-2px); box-shadow:0 8px 24px rgba(99,102,241,.15); }}
        .card h2 {{ font-size:16px; margin-bottom:6px; }}
        .card p {{ font-size:12px; color:#6b7394; }}
        .badge {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:10px; font-weight:600; margin-top:8px; }}
        .badge-purple {{ background:rgba(99,102,241,.12); color:#818cf8; }}
        .badge-green {{ background:rgba(16,185,129,.12); color:#10b981; }}
        .footer {{ margin-top:32px; font-size:11px; color:#6b7394; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Stillport</h1>
        <p class="sub">CRM &amp; Outreach Platform</p>
        <div class="cards">
          <a href="/crm" class="card">
            <h2>Fundraise CRM</h2>
            <p>Investor pipeline, activity tracking, round management</p>
            <span class="badge badge-green">Open App</span>
          </a>
          <a href="/outreach" class="card">
            <h2>OutreachFlow</h2>
            <p>Email campaigns, templates, open tracking</p>
            <span class="badge badge-purple">Open App</span>
          </a>
        </div>
        <div class="footer">Authenticated via Microsoft 365</div>
      </div>
    </body>
    </html>
    """

@app.route('/crm')
def crm():
    return send_file(os.path.join(APP_DIR, 'stillport-fundraise-crm.html'))

@app.route('/outreach')
def outreach():
    return send_file(os.path.join(APP_DIR, 'outreach-app.html'))


# ===== TRACKING PIXEL SERVER =====
EVENTS_FILE = os.path.join(APP_DIR, 'open_events.json')
events_lock = threading.Lock()

PIXEL_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)

def load_events():
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_events(events):
    try:
        with open(EVENTS_FILE, 'w') as f:
            json.dump(events, f)
    except IOError as e:
        print(f"Warning: Could not save events: {e}")

@app.route('/track', methods=['GET'])
def track():
    tid = request.args.get('tid', '')
    cid = request.args.get('cid', '')
    if tid:
        event = {
            'tid': tid, 'cid': cid,
            'ts': datetime.utcnow().isoformat() + 'Z',
            'ip': request.headers.get('X-Forwarded-For', request.remote_addr),
            'ua': request.headers.get('User-Agent', ''),
        }
        with events_lock:
            events = load_events()
            events.append(event)
            save_events(events)
        print(f"[OPEN] tid={tid} cid={cid} ip={event['ip']}")
    return Response(PIXEL_GIF, mimetype='image/gif', headers={
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache', 'Expires': '0',
    })

@app.route('/events', methods=['GET'])
def get_events():
    api_key = os.environ.get('TRACKER_KEY', '')
    if api_key and request.args.get('key', '') != api_key:
        return jsonify({'error': 'Invalid API key'}), 403
    cids = request.args.get('cids', '').split(',') if request.args.get('cids') else []
    since = request.args.get('since', '')
    with events_lock:
        events = load_events()
    if cids:
        events = [e for e in events if e.get('cid', '') in cids]
    if since:
        events = [e for e in events if e.get('ts', '') > since]
    return jsonify(events)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'Stillport Apps Server',
        'events_count': len(load_events()),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    print(f"\n  Stillport Apps Server running on http://0.0.0.0:{port}")
    print(f"  CRM:          http://localhost:{port}/crm")
    print(f"  OutreachFlow:  http://localhost:{port}/outreach")
    print(f"  Tracker:       http://localhost:{port}/track\n")
    app.run(host='0.0.0.0', port=port, debug=False)
