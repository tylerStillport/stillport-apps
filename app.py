"""
Stillport Apps Server
=====================
Serves both OutreachFlow and Stillport Fundraise CRM as a single deployment,
plus the email open tracking pixel server.

Routes:
  /                         — Landing page with links to all apps
  /outreach                 — OutreachFlow email campaign app
  /crm                      — Stillport Fundraise CRM
  /scorecard                — RE Scorecard (AI-powered deal scoring)
  /api/score                — Anthropic API proxy (keeps key server-side)
  /track?tid=...&cid=...    — Tracking pixel endpoint
  /events?cids=...          — Open event data
  /health                   — Health check
"""

from flask import Flask, request, Response, jsonify, send_file, redirect
from flask_cors import CORS
from datetime import datetime
import json
import os
import io
import threading
import requests as http_requests
import base64
from fpdf import FPDF

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024   # 50 MB max upload
CORS(app)

# ===== STATIC APP FILES =====
APP_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def index():
    # If accessed via scorecard.stillport.co, serve the scorecard directly
    host = request.headers.get('Host', '')
    if host.startswith('scorecard.'):
        return send_file(os.path.join(APP_DIR, 'stillport-re-scorecard.html'))
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
        .cards {{ display:flex; gap:16px; justify-content:center; flex-wrap:wrap; }}
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
          <a href="/scorecard" class="card">
            <h2>RE Scorecard</h2>
            <p>AI-powered deal scoring &amp; investment analysis</p>
            <span class="badge badge-green">Open App</span>
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

@app.route('/scorecard')
def scorecard():
    return send_file(os.path.join(APP_DIR, 'stillport-re-scorecard.html'))


# ===== PDF GENERATION =====

def hex_to_rgb(h):
    """Convert hex colour like '#1B2A4A' to (r, g, b) tuple."""
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

@app.route('/api/generate-pdf', methods=['POST'])
def generate_pdf():
    """Generate a Strategy Briefing PDF from structured data using fpdf2."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON body'}), 400

        prop = data.get('property', {})
        dims = data.get('dimensions', [])
        sections = data.get('sections', [])
        composite = str(data.get('compositeScore', '—'))
        qual_label = data.get('qualLabel', '')
        tier_label = data.get('tierLabel', '')
        tier_color = data.get('tierColor', '#1B2A4A')
        gold = data.get('gold', '#C9A84C')
        qual_color = data.get('qualColor', '#4CAF50')
        light_gold = data.get('lightGold', '#F5F0E1')

        tc = hex_to_rgb(tier_color)
        gc = hex_to_rgb(gold)
        qc = hex_to_rgb(qual_color)
        lgc = hex_to_rgb(light_gold)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pw = pdf.w - pdf.l_margin - pdf.r_margin  # printable width

        # ---- HEADER BAR ----
        pdf.set_fill_color(*tc)
        pdf.rect(pdf.l_margin, pdf.get_y(), pw, 28, 'F')
        y_start = pdf.get_y()

        # Title (left side)
        pdf.set_xy(pdf.l_margin + 6, y_start + 4)
        pdf.set_text_color(*gc)
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(pw * 0.65, 7, 'Stillport Strategy Briefing', new_x='LMARGIN')
        pdf.set_xy(pdf.l_margin + 6, y_start + 12)
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(200, 200, 200)
        pdf.cell(pw * 0.65, 5, f'Real Estate Selection Scorecard  —  {tier_label}', new_x='LMARGIN')

        # Score (right side)
        pdf.set_xy(pdf.l_margin + pw * 0.65, y_start + 3)
        pdf.set_text_color(*gc)
        pdf.set_font('Helvetica', 'B', 26)
        pdf.cell(pw * 0.35 - 6, 10, composite, align='R', new_x='LMARGIN')
        pdf.set_xy(pdf.l_margin + pw * 0.65, y_start + 15)
        pdf.set_text_color(*qc)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(pw * 0.35 - 6, 5, qual_label, align='R', new_x='LMARGIN')

        pdf.set_y(y_start + 32)

        # ---- PROPERTY INFO BOX ----
        pdf.set_fill_color(249, 249, 249)
        pdf.set_draw_color(220, 220, 220)
        box_y = pdf.get_y()
        box_h = 38
        pdf.rect(pdf.l_margin, box_y, pw, box_h, 'DF')

        label_color = (140, 140, 140)
        value_color = (30, 30, 30)
        col_w = pw / 2

        info_rows = [
            [('Property', prop.get('name', '—')),
             ('Market', f"{prop.get('market', '—')} ({prop.get('marketComposite', '—')})")],
            [('Building', f"{prop.get('buildingType', '—')}, {prop.get('totalSF', '—')} SF"),
             ('Price', f"{prop.get('askingPrice', '—')} ({prop.get('priceSF', '—')}/SF)")],
            [('Date Evaluated', prop.get('dateEvaluated', '—')),
             ('Evaluator', prop.get('evaluator', '—'))],
        ]

        cy = box_y + 2
        for row in info_rows:
            for idx, (label, value) in enumerate(row):
                x = pdf.l_margin + 4 + idx * col_w
                pdf.set_xy(x, cy)
                pdf.set_text_color(*label_color)
                pdf.set_font('Helvetica', '', 7)
                pdf.cell(col_w - 8, 4, label)
                pdf.set_xy(x, cy + 4)
                pdf.set_text_color(*value_color)
                pdf.set_font('Helvetica', 'B', 9)
                pdf.cell(col_w - 8, 4, value[:50])
            cy += 12

        pdf.set_y(box_y + box_h + 6)

        # ---- DIMENSION SCORES TABLE ----
        col_widths = [pw * 0.55, pw * 0.2, pw * 0.25]
        headers = ['Dimension', 'Weight', 'Score']

        # Header row
        pdf.set_fill_color(*tc)
        pdf.set_text_color(*gc)
        pdf.set_font('Helvetica', 'B', 9)
        for i, h in enumerate(headers):
            align = 'L' if i == 0 else 'C'
            pdf.cell(col_widths[i], 8, f'  {h}' if i == 0 else h, fill=True, align=align)
        pdf.ln()

        # Dimension rows
        pdf.set_text_color(30, 30, 30)
        pdf.set_font('Helvetica', '', 9)
        for d in dims:
            pdf.set_draw_color(230, 230, 230)
            y_before = pdf.get_y()
            pdf.cell(col_widths[0], 7, f"  {d.get('name', '')}", border='B')
            pdf.cell(col_widths[1], 7, d.get('weight', ''), border='B', align='C')
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(27, 42, 74)
            pdf.cell(col_widths[2], 7, str(d.get('score', '—')), border='B', align='C')
            pdf.ln()
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(30, 30, 30)

        # Composite row
        pdf.set_fill_color(*lgc)
        pdf.set_text_color(27, 42, 74)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(col_widths[0], 8, '  Composite', fill=True)
        pdf.cell(col_widths[1], 8, '100%', fill=True, align='C')
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(col_widths[2], 8, composite, fill=True, align='C')
        pdf.ln(12)

        # ---- BRIEFING SECTIONS ----
        for s in sections:
            # Check if we need a new page (at least 30mm needed)
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()

            title = s.get('title', '')
            content = s.get('content', '')

            pdf.set_text_color(27, 42, 74)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.cell(pw, 7, title, new_x='LMARGIN', new_y='NEXT')
            # Gold underline
            pdf.set_draw_color(*gc)
            pdf.set_line_width(0.5)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
            pdf.ln(3)

            pdf.set_text_color(50, 50, 50)
            pdf.set_font('Helvetica', '', 9)
            pdf.multi_cell(pw, 5, content)
            pdf.ln(5)

        # ---- FOOTER ----
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pw, pdf.get_y())
        pdf.ln(3)
        pdf.set_text_color(180, 180, 180)
        pdf.set_font('Helvetica', '', 7)
        pdf.cell(pw, 5, f"Stillport RE Selection Scorecard  —  {tier_label}  —  Generated {datetime.utcnow().strftime('%m/%d/%Y')}", align='C')

        # Output
        pdf_bytes = pdf.output()
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={'Content-Disposition': 'inline; filename=strategy_briefing.pdf'}
        )
    except Exception as e:
        print(f"[generate-pdf] Error: {str(e)}", flush=True)
        import traceback, sys
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        return jsonify({'error': str(e)}), 500


# ===== ANTHROPIC API PROXY =====
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# ===== DROPBOX CONFIG =====
DROPBOX_REFRESH_TOKEN = os.environ.get('DROPBOX_REFRESH_TOKEN', '')
DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY', '')
DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET', '')
DROPBOX_ROOT_NAMESPACE = os.environ.get('DROPBOX_ROOT_NAMESPACE', '13775737299')  # Stillport team root
# Cache for the short-lived access token
_dropbox_token_cache = {'token': '', 'expires_at': 0}

def get_dropbox_access_token():
    """Get a valid Dropbox access token, refreshing if needed."""
    import time
    now = time.time()
    if _dropbox_token_cache['token'] and _dropbox_token_cache['expires_at'] > now + 60:
        return _dropbox_token_cache['token']

    if not DROPBOX_REFRESH_TOKEN or not DROPBOX_APP_KEY or not DROPBOX_APP_SECRET:
        return ''

    try:
        resp = http_requests.post(
            'https://api.dropboxapi.com/oauth2/token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': DROPBOX_REFRESH_TOKEN,
                'client_id': DROPBOX_APP_KEY,
                'client_secret': DROPBOX_APP_SECRET,
            },
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            _dropbox_token_cache['token'] = data['access_token']
            _dropbox_token_cache['expires_at'] = now + data.get('expires_in', 14400)
            print(f"[dropbox] Refreshed access token (expires in {data.get('expires_in', '?')}s)", flush=True)
            return _dropbox_token_cache['token']
        else:
            print(f"[dropbox] Token refresh failed: {resp.status_code} {resp.text}", flush=True)
            return ''
    except Exception as e:
        print(f"[dropbox] Token refresh error: {e}", flush=True)
        return ''

@app.route('/api/score', methods=['POST'])
def api_score():
    """Proxy endpoint for Anthropic API calls — keeps API key server-side.

    Streams the raw request body directly to Anthropic to avoid
    parsing + re-serialising large PDF base64 payloads in memory
    (critical on Render free-tier 512 MB instances).
    """
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured on server'}), 500
    try:
        import traceback, sys
        raw_body = request.get_data()            # raw bytes — no JSON parse
        content_len = len(raw_body)
        key_preview = ANTHROPIC_API_KEY[:20] + '...' if len(ANTHROPIC_API_KEY) > 20 else '(empty)'
        print(f"[api/score] Incoming request: {content_len:,} bytes | key starts: {key_preview}", flush=True)

        resp = http_requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'Content-Type': 'application/json',
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
            },
            data=raw_body,                        # forward raw bytes
            timeout=150,
            stream=True,                          # stream the response
        )
        # Read response in chunks to keep memory low
        response_chunks = []
        for chunk in resp.iter_content(chunk_size=8192):
            response_chunks.append(chunk)
        response_body = b''.join(response_chunks)
        del raw_body                              # free request memory early

        print(f"[api/score] Anthropic responded: {resp.status_code} ({len(response_body):,} bytes)", flush=True)
        if resp.status_code >= 400:
            # Log error responses so we can debug in Render logs
            print(f"[api/score] ERROR body: {response_body[:2000]}", flush=True)
            print(f"[api/score] Response headers: {dict(resp.headers)}", flush=True)
        return Response(response_body, status=resp.status_code,
                        content_type=resp.headers.get('Content-Type', 'application/json'))
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        return jsonify({'error': str(e)}), 500


# ===== DROPBOX UPLOAD ENDPOINT =====
@app.route('/api/dropbox-upload', methods=['POST'])
def dropbox_upload():
    """Upload a file to Dropbox in a structured folder hierarchy.

    Request JSON body:
    {
        "filename": "document.pdf",
        "fileData": "base64-encoded-file-data",
        "propertyAddress": "123 Main St, San Francisco, CA",
        "contentType": "application/pdf"
    }
    """
    try:
        access_token = get_dropbox_access_token()
        if not access_token:
            return jsonify({'error': 'Dropbox not configured — set DROPBOX_REFRESH_TOKEN, DROPBOX_APP_KEY, DROPBOX_APP_SECRET'}), 500

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400

        filename = data.get('filename', '')
        file_data_b64 = data.get('fileData', '')
        property_address = data.get('propertyAddress', '')
        content_type = data.get('contentType', 'application/octet-stream')

        if not filename or not file_data_b64 or not property_address:
            return jsonify({'error': 'Missing required fields: filename, fileData, propertyAddress'}), 400

        # Decode base64 file data
        try:
            file_bytes = base64.b64decode(file_data_b64)
        except Exception as e:
            return jsonify({'error': f'Invalid base64 encoding: {str(e)}'}), 400

        # Generate today's date in YYYY-MM-DD format
        today = datetime.utcnow().strftime('%Y-%m-%d')

        # Construct folder path
        folder_path = f"/Stillport Team Folder/03_REAL ESTATE & ACQUISITIONS/01_Deal Pipeline/01_Active Prospects/1_ Early Prospects Scorecards/{property_address} - {today}"
        file_path = f"{folder_path}/{filename}"

        # Step 1: Create folder (if it doesn't exist, we'll get a 409 which is fine)
        # Use Dropbox-API-Path-Root to target the team root namespace (not member folder)
        path_root_header = json.dumps({".tag": "root", "root": DROPBOX_ROOT_NAMESPACE})
        headers_auth = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Dropbox-API-Path-Root': path_root_header,
        }

        create_folder_body = json.dumps({
            'path': folder_path,
            'autorename': False
        })

        print(f"[dropbox-upload] Creating folder: {folder_path}", flush=True)
        folder_resp = http_requests.post(
            'https://api.dropboxapi.com/2/files/create_folder_v2',
            headers=headers_auth,
            data=create_folder_body,
            timeout=30
        )

        # 409 means folder already exists, which is fine
        if folder_resp.status_code not in [200, 409]:
            print(f"[dropbox-upload] Folder creation error: {folder_resp.status_code} - {folder_resp.text}", flush=True)
            return jsonify({'error': f'Failed to create folder: {folder_resp.status_code}'}), 500

        # Step 2: Upload file
        upload_headers = {
            'Authorization': f'Bearer {access_token}',
            'Dropbox-API-Arg': json.dumps({
                'path': file_path,
                'mode': 'overwrite'
            }),
            'Content-Type': 'application/octet-stream',
            'Dropbox-API-Path-Root': path_root_header,
        }

        print(f"[dropbox-upload] Uploading file: {file_path} ({len(file_bytes):,} bytes)", flush=True)
        upload_resp = http_requests.post(
            'https://content.dropboxapi.com/2/files/upload',
            headers=upload_headers,
            data=file_bytes,
            timeout=60
        )

        if upload_resp.status_code != 200:
            print(f"[dropbox-upload] Upload error: {upload_resp.status_code} - {upload_resp.text}", flush=True)
            return jsonify({'error': f'Failed to upload file: {upload_resp.status_code}'}), 500

        print(f"[dropbox-upload] Success: {filename} uploaded to {file_path}", flush=True)
        return jsonify({
            'success': True,
            'message': f'File uploaded successfully to {file_path}',
            'filename': filename,
            'path': file_path
        }), 200

    except Exception as e:
        import traceback, sys
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        return jsonify({'error': str(e)}), 500


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
    print(f"  RE Scorecard:  http://localhost:{port}/scorecard")
    print(f"  Tracker:       http://localhost:{port}/track\n")
    app.run(host='0.0.0.0', port=port, debug=False)
