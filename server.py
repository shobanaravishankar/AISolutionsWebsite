"""Local-only JARVIS website service. Python 3.11+, standard library only."""
import argparse
import collections
from contextlib import contextmanager
import datetime as dt
import hashlib
import hmac
import http.cookies
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.message import EmailMessage

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'dist'
DATA = Path(os.environ.get('JARVIS_DATA_DIR', Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'AISolutionsWebsite'))
RETENTION_DAYS = 90
AUDIENCES = {'unspecified', 'creator', 'professional', 'household', 'small_business'}
STATUSES = {'new', 'reviewing', 'drafted', 'followed_up', 'closed'}
SESSIONS = {}
LIMITS = collections.defaultdict(collections.deque)
LOCK = threading.RLock()
AI_SLOTS = threading.BoundedSemaphore(2)
def wrapper_request(path, body=None):
    # Credentials never reach the browser; remote/public endpoints are not accepted.
    endpoint = urllib.parse.urlsplit(os.environ.get('JARVIS_AGENT_URL', 'http://127.0.0.1:8766'))
    if endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or endpoint.path not in ('', '/') or endpoint.username or endpoint.query or endpoint.fragment:
        raise ValueError('Loopback JARVIS endpoint required.')
    token_file = os.environ.get('JARVIS_AGENT_TOKEN_FILE')
    token = Path(token_file).read_text(encoding='utf-8').strip() if token_file else os.environ.get('JARVIS_AGENT_TOKEN', '')
    if len(token) < 32: raise ValueError('Wrapper token is not configured.')
    connection = http.client.HTTPConnection('127.0.0.1', endpoint.port or 8766, timeout=55 if body else 4)
    try:
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        connection.request('POST' if body else 'GET', path, json.dumps(body).encode() if body else None, headers)
        response = connection.getresponse()
        if response.status != 200: raise ValueError('JARVIS wrapper unavailable.')
        raw = response.read(100001)
        if len(raw) > 100000: raise ValueError('Oversized response.')
        result = json.loads(raw)
        if not isinstance(result, dict): raise ValueError('Invalid response.')
        return result
    finally:
        connection.close()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

@contextmanager
def database():
    db = sqlite3.connect(DATA / 'website.sqlite3', timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA secure_delete=ON;
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, session TEXT NOT NULL, kind TEXT NOT NULL,
          value TEXT NOT NULL, referrer TEXT NOT NULL, created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_created ON events(created);
        CREATE TABLE IF NOT EXISTS submissions (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL,
          audience TEXT NOT NULL, topic TEXT NOT NULL, text TEXT,
          name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
          outcome TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
          draft TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS submissions_created ON submissions(created);
        ''')
        columns={r[1] for r in db.execute('PRAGMA table_info(submissions)')}
        for column in ('phone','contact_preference'):
            if column not in columns: db.execute(f"ALTER TABLE submissions ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

def clean_old():
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)).isoformat()
    with database() as db:
        db.execute('PRAGMA secure_delete=ON')
        db.execute('DELETE FROM events WHERE created < ?', (cutoff,))
        db.execute('DELETE FROM submissions WHERE created < ?', (cutoff,))

def setting(key, default=''):
    with database() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default

def save_setting(key, value):
    with database() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, value))

def text_field(body, key, maximum, required=False):
    value = body.get(key, '')
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError(f'{key} is invalid or too long (maximum {maximum} characters).')
    value = value.strip()
    if required and not value:
        raise ValueError(f'Please enter {key}.')
    return value

def category(text):
    terms = [('creation', r'\b(draft|write|document|proposal|create|content|idea)\b'),
             ('research', r'\b(research|compare|analysis|analyze|source|find)\b'),
             ('organization', r'\b(plan|organize|schedule|checklist|task|paperwork)\b'),
             ('product_question', r'\b(jarvis|price|pricing|available|launch|privacy|ai)\b')]
    for name, pattern in terms:
        if re.search(pattern, text, re.I): return name
    return 'other'

def email_valid(value):
    return not value or (len(value) <= 254 and bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value)))

def provider_info():
    try:
        result = wrapper_request('/health')
        return {'provider': 'JARVIS', 'model': result.get('model', ''), 'ai_ready': result.get('ready') is True,
                'wrapper_connected': True, 'reason': result.get('reason', '')}
    except (OSError, ValueError, http.client.HTTPException):
        return {'provider': 'JARVIS', 'model': '', 'ai_ready': False, 'wrapper_connected': False, 'reason': 'wrapper_unavailable'}

def call_ai(prompt, history=None):
    try:
        result = wrapper_request('/chat', {'message': prompt, 'history': history or []})
        answer = result.get('answer')
        if result.get('status') == 'reply' and isinstance(answer, str) and answer.strip() and len(answer) <= 20000:
            return 'responded', answer, None
        return 'unavailable', None, 'JARVIS is connected to this website, but its model did not complete a reply. You can retry or leave an enquiry.'
    except (OSError, ValueError, http.client.HTTPException):
        return 'unconfigured', None, 'The JARVIS connection is not ready. No AI reply was generated. You can leave an enquiry below.'

def hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()

def mail_ready():
    return (os.environ.get('MAIL_SEND_ENABLED') == 'true' and
            all(os.environ.get(k) for k in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM')) and
            email_valid(os.environ.get('SMTP_FROM','')))

def send_mail(to, draft):
    message=EmailMessage()
    message['From']=os.environ['SMTP_FROM']; message['To']=to
    message['Subject']='Your AI Solutions enquiry'
    message.set_content(draft)
    with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.environ.get('SMTP_PORT','587')),timeout=20) as client:
        client.starttls(context=ssl.create_default_context())
        client.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
        client.send_message(message)

class Handler(BaseHTTPRequestHandler):
    server_version = 'JARVIS-local'
    def log_message(self, *args):
        pass  # Do not persist IPs, query strings, cookies or submitted text in access logs.

    def headers_common(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

    def respond(self, status, data, cookie=None):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError): pass

    def allowed_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def authenticated(self):
        cookie = http.cookies.SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: return False
        token = cookie.get('jarvis_owner')
        if not token: return False
        with LOCK:
            expiry = SESSIONS.get(token.value, 0)
            if expiry <= time.time():
                SESSIONS.pop(token.value, None)
                return False
        return True

    def rate_limit(self, bucket, maximum, window=60):
        # IP used transiently only for local abuse control, not identity or analytics.
        key = (self.client_address[0], bucket)
        with LOCK:
            items = LIMITS[key]
            while items and items[0] < time.monotonic() - window: items.popleft()
            if len(items) >= maximum: return False
            items.append(time.monotonic())
        return True

    def do_GET(self):
        if not self.allowed_host(): return self.respond(403, {'error':'Invalid host.'})
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/status':
            return self.respond(200, {**provider_info(),
                'owner_setup_needed': not bool(setting('owner_hash')), 'retention_days': RETENTION_DAYS})
        if path.startswith('/api/owner/'):
            if not self.authenticated(): return self.respond(401, {'error':'Owner login required.'})
            clean_old()
            if path == '/api/owner/dashboard': return self.dashboard()
            return self.respond(404, {'error':'Not found.'})
        if path.startswith('/api/'): return self.respond(404, {'error':'Not found.'})
        if path in ('/', '/index.html'): file = PUBLIC / 'index.html'
        elif path in ('/owner', '/owner/'): file = PUBLIC / 'owner.html'
        else: file = (PUBLIC / urllib.parse.unquote(path).lstrip('/')).resolve()
        if not file.is_relative_to(PUBLIC.resolve()) or not file.is_file() or file.name.startswith('.'):
            return self.respond(404, {'error':'Not found.'})
        raw = file.read_bytes()
        self.send_response(200); self.headers_common()
        self.send_header('Content-Type', (mimetypes.guess_type(file.name)[0] or 'application/octet-stream') + ('; charset=utf-8' if file.suffix in {'.html','.css','.js'} else ''))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def dashboard(self):
        with database() as db:
            totals = dict(db.execute("SELECT COUNT(*) page_views, COUNT(DISTINCT session) visits FROM events WHERE kind='pageview'").fetchone())
            totals['enquiries'] = db.execute("SELECT COUNT(*) FROM submissions WHERE kind='enquiry'").fetchone()[0]
            totals['commands'] = db.execute("SELECT COUNT(*) FROM submissions WHERE kind='command'").fetchone()[0]
            totals['contacts'] = db.execute("SELECT COUNT(DISTINCT lower(email)) FROM submissions WHERE email!=''").fetchone()[0]
            rows = [dict(r) for r in db.execute('SELECT * FROM submissions ORDER BY created DESC LIMIT 250')]
            referrals = [dict(r) for r in db.execute("SELECT referrer label,COUNT(*) count FROM events WHERE kind='pageview' GROUP BY referrer ORDER BY count DESC LIMIT 20")]
            topics = [dict(r) for r in db.execute('SELECT topic label,COUNT(*) count FROM submissions GROUP BY topic ORDER BY count DESC')]
            audiences = [dict(r) for r in db.execute('SELECT audience label,COUNT(*) count FROM submissions GROUP BY audience ORDER BY count DESC')]
            daily = [dict(r) for r in db.execute("SELECT substr(created,1,10) day,COUNT(*) page_views,COUNT(DISTINCT session) visits FROM events WHERE kind='pageview' GROUP BY day ORDER BY day DESC LIMIT 14")]
        self.respond(200, {'totals':totals,'records':rows,'referrals':referrals,'topics':topics,'audiences':audiences,'daily':daily,
            'config':{**provider_info(),
                      'business_email':setting('business_email'), 'mail_ready':bool(mail_ready()),
                      'retention_days':RETENTION_DAYS, 'location':'Not collected'}})

    def do_POST(self):
        if not self.allowed_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host',''):
            return self.respond(403, {'error':'Same-origin request required.'})
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            return self.respond(415, {'error':'JSON required.'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 1 <= length <= 24000: return self.respond(413, {'error':'Request is too large or empty.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError('Invalid request.')
            clean_old()
            path = urllib.parse.urlsplit(self.path).path
            if path in ('/api/owner/setup','/api/owner/login'):
                return self.login(body, path.endswith('setup'))
            if path.startswith('/api/owner/'):
                if not self.authenticated(): return self.respond(401, {'error':'Owner login required.'})
                return self.owner_action(path, body)
            if path == '/api/event': return self.event(body)
            if path in ('/api/command','/api/enquiry'): return self.submission(body, path.endswith('command'))
            self.respond(404, {'error':'Not found.'})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {'error':str(exc)[:180]})
        except sqlite3.Error:
            self.respond(503, {'error':'The local data store is unavailable. Please try again.'})

    def login(self, body, setup):
        if not self.rate_limit('login', 8, 600): return self.respond(429, {'error':'Too many login attempts. Wait ten minutes.'})
        password = text_field(body, 'password', 200, True)
        if setup:
            if len(password) < 12: raise ValueError('Use a password of at least 12 characters.')
            with LOCK:
                if setting('owner_hash'): return self.respond(409, {'error':'Owner is already configured. Sign in instead.'})
                salt = secrets.token_hex(16)
                save_setting('owner_salt', salt); save_setting('owner_hash', hash_password(password,salt))
        else:
            stored = setting('owner_hash')
            if not stored or not hmac.compare_digest(stored, hash_password(password,setting('owner_salt'))):
                return self.respond(401, {'error':'Password not recognized.'})
        token = secrets.token_urlsafe(32)
        with LOCK:
            for key in list(SESSIONS):
                if SESSIONS[key] <= time.time(): del SESSIONS[key]
            SESSIONS[token] = time.time() + 8*3600
        self.respond(200, {'ok':True}, f'jarvis_owner={token}; HttpOnly; SameSite=Strict; Path=/api/owner; Max-Age=28800')

    def event(self, body):
        if body.get('consent') is not True: return self.respond(400, {'error':'Analytics consent required.'})
        if not self.rate_limit('event',60): return self.respond(429, {'error':'Event limit reached.'})
        event_id = text_field(body,'id',64,True); session = text_field(body,'session',64,True)
        if not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',event_id) or not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',session): raise ValueError('Invalid event identity.')
        kind = body.get('kind'); value = body.get('value','')
        if kind not in ('pageview','section') or value not in ('','idea','approach','roadmap','questions'): raise ValueError('Invalid event.')
        ref = text_field(body,'referrer',2000)
        host = urllib.parse.urlsplit(ref).hostname if ref else None
        source = host[:150] if host and re.fullmatch(r'[A-Za-z0-9.-]+',host) else 'Direct / unavailable'
        if host in {'localhost','127.0.0.1'}: source='Local preview'
        with database() as db:
            db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)',(event_id,session,kind,value,source,now()))
        self.respond(200, {'ok':True})

    def submission(self, body, is_command):
        if not self.rate_limit('submission',5): return self.respond(429, {'error':'Please wait a minute before sending more requests.'})
        if body.get('website'): return self.respond(400, {'error':'Submission rejected.'})
        content = text_field(body,'message',3000,True)
        audience = body.get('audience','unspecified')
        if audience not in AUDIENCES: raise ValueError('Invalid audience.')
        name = text_field(body,'name',100); email = text_field(body,'email',254)
        phone=text_field(body,'phone',30)
        if phone and not re.fullmatch(r'[+0-9 ()\-.]{6,30}',phone): raise ValueError('Enter a valid phone number or leave it blank.')
        preference=body.get('contact_preference','none')
        if preference not in ('none','email','phone'): raise ValueError('Invalid contact preference.')
        if preference=='email' and not email: raise ValueError('Add an email for email follow-up.')
        if preference=='phone' and not phone: raise ValueError('Add a phone number for phone follow-up.')
        if not email_valid(email): raise ValueError('Enter a valid email address or leave it blank.')
        if is_command and body.get('ai_consent') is not True: raise ValueError('Confirm the AI processing notice before submitting.')
        if not is_command and body.get('contact_consent') is not True: raise ValueError('Confirm the enquiry storage notice before submitting.')
        share = not is_command or body.get('share_text') is True
        record_id = secrets.token_hex(16)
        outcome, answer, error = ('received', None, None)
        if is_command:
            history=body.get('history',[])
            if not isinstance(history,list) or len(history)>10: raise ValueError('Conversation is too long. Start a new chat.')
            checked=[]
            for item in history:
                if not isinstance(item,dict) or item.get('role') not in ('user','assistant'): raise ValueError('Invalid conversation.')
                checked.append({'role':item['role'],'content':text_field(item,'content',4000,True)})
            if sum(len(m['content']) for m in checked)>12000: raise ValueError('Conversation is too long. Start a new chat.')
            if not AI_SLOTS.acquire(blocking=False): return self.respond(429, {'error':'The AI demo is busy. Please try again shortly.'})
            try: outcome, answer, error = call_ai(content,checked)
            finally: AI_SLOTS.release()
        with database() as db:
            db.execute('INSERT INTO submissions (id,kind,created,audience,topic,text,name,email,outcome,phone,contact_preference) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (record_id,'command' if is_command else 'enquiry',now(),audience,category(content),content if share else None,
                 name if not is_command else '',email if not is_command else '',outcome,phone if not is_command else '',preference if not is_command else 'none'))
        self.respond(200, {'id':record_id,'outcome':outcome,'answer':answer,'message':error or ('Enquiry saved to the owner inbox. No email has been sent.' if not is_command else 'AI response received.'),'text_saved':share})

    def owner_action(self,path,body):
        if path == '/api/owner/logout':
            cookie=http.cookies.SimpleCookie(self.headers.get('Cookie',''))
            with LOCK: SESSIONS.pop(cookie['jarvis_owner'].value,None)
            return self.respond(200,{'ok':True},'jarvis_owner=; HttpOnly; SameSite=Strict; Path=/api/owner; Max-Age=0')
        if path == '/api/owner/settings':
            email=text_field(body,'business_email',254)
            if not email_valid(email): raise ValueError('Invalid business email.')
            save_setting('business_email',email)
            return self.respond(200,{'ok':True})
        record_id=text_field(body,'id',64,True)
        if path == '/api/owner/send':
            if not mail_ready(): return self.respond(503,{'error':'Outbound email is not configured and enabled.'})
            if body.get('confirm') is not True: raise ValueError('Review and confirm this email before sending.')
            with LOCK:
                with database() as db:
                    row=db.execute('SELECT * FROM submissions WHERE id=?',(record_id,)).fetchone()
                    if not row or row['contact_preference'] != 'email' or not row['email'] or not row['draft']: raise ValueError('A supplied contact email and saved draft are required.')
                    if row['outcome'] in ('email_sending','email_sent','email_uncertain'):
                        return self.respond(409,{'error':'This record was sent or has an uncertain delivery. Check your mail provider before any follow-up.'})
                    db.execute("UPDATE submissions SET outcome='email_sending' WHERE id=?",(record_id,))
                try:
                    send_mail(row['email'],row['draft'])
                    outcome='email_sent'; status='followed_up'; message='Mail server accepted the reply. Inbox delivery is not confirmed.'
                except (OSError, smtplib.SMTPException, ValueError):
                    outcome='email_uncertain'; status=row['status']; message='Delivery could not be confirmed. Check your mail provider before retrying; no automatic retry was made.'
                with database() as db:
                    db.execute('UPDATE submissions SET outcome=?,status=? WHERE id=?',(outcome,status,record_id))
            return self.respond(200,{'ok':outcome=='email_sent','message':message})
        with database() as db:
            row=db.execute('SELECT * FROM submissions WHERE id=?',(record_id,)).fetchone()
            if not row: return self.respond(404,{'error':'Record not found.'})
            if path == '/api/owner/update':
                status=body.get('status')
                if status not in STATUSES: raise ValueError('Invalid status.')
                draft=text_field(body,'draft',6000); note=text_field(body,'note',1000)
                db.execute('UPDATE submissions SET status=?,draft=?,note=? WHERE id=?',(status,draft,note,record_id))
            elif path == '/api/owner/delete':
                if body.get('confirm') is not True: raise ValueError('Deletion confirmation required.')
                db.execute('PRAGMA secure_delete=ON')
                db.execute('DELETE FROM submissions WHERE id=?',(record_id,))
            else: return self.respond(404,{'error':'Not found.'})
        self.respond(200,{'ok':True})

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args(); init_db(); clean_old()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Visitor: http://127.0.0.1:{args.port}/ | Owner: http://127.0.0.1:{args.port}/owner',flush=True)
    print('Local-only service. JARVIS connection credentials stay on the server.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
