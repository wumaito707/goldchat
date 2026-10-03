"""Verified contact registration and recovery. Codes are never returned by APIs."""
import json, base64, hashlib, hmac, os, re, secrets, smtplib, sqlite3, ssl, time
import urllib.parse, urllib.request
from email.message import EmailMessage
from contextlib import contextmanager
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

def init_schema(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(users)')}
    for name,kind in [('verified_email','TEXT'),('verified_phone','TEXT'),('verified_at','REAL')]:
        if name not in columns:conn.execute(f'ALTER TABLE users ADD COLUMN {name} {kind}')
    conn.executescript('''
    CREATE UNIQUE INDEX IF NOT EXISTS verified_email_unique ON users(verified_email);
    CREATE UNIQUE INDEX IF NOT EXISTS verified_phone_unique ON users(verified_phone);
    CREATE TABLE IF NOT EXISTS verification_challenges (
      id TEXT PRIMARY KEY, purpose TEXT NOT NULL, channel TEXT NOT NULL, address TEXT NOT NULL,
      user_id INTEGER, code_hash TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0,
      proof_hash TEXT, proof_expires REAL, ip TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS verification_limits ON verification_challenges(address,created_at);
    ''')

def normalize(channel,address):
    address=address.strip()
    if channel=='email':
        address=address.lower()
        if len(address)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',address):
            raise HTTPException(400,'Enter a valid email address')
    elif channel=='phone':
        address=re.sub(r'[\s()-]','',address)
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}',address):
            raise HTTPException(400,'Use an international phone number, for example +234…')
    else:raise HTTPException(400,'Choose email or phone')
    return address

def delivery_ready(channel):
    if channel=='email' and os.environ.get('GOLDCHAT_EMAIL_PROVIDER')=='brevo':
        return bool(os.environ.get('GOLDCHAT_EMAIL_API_KEY') and os.environ.get('GOLDCHAT_SMTP_FROM'))
    fields=('GOLDCHAT_SMTP_HOST','GOLDCHAT_SMTP_FROM') if channel=='email' else ('GOLDCHAT_TWILIO_SID','GOLDCHAT_TWILIO_TOKEN','GOLDCHAT_TWILIO_FROM')
    return all(os.environ.get(k) for k in fields)

def send_code(channel,address,code,purpose):
    text=f'Your GOLDCHAT {purpose} verification code is {code}. It expires in 10 minutes. Do not share it.'
    if channel=='email' and os.environ.get('GOLDCHAT_EMAIL_PROVIDER')=='brevo':
        payload={'sender':{'name':'GOLDCHAT','email':os.environ['GOLDCHAT_SMTP_FROM']},'to':[{'email':address}],'subject':'Your GOLDCHAT verification code','textContent':text}
        req=urllib.request.Request('https://api.brevo.com/v3/smtp/email',data=json.dumps(payload).encode(),headers={'api-key':os.environ['GOLDCHAT_EMAIL_API_KEY'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as response:response.read()
    elif channel=='email':
        message=EmailMessage();message['From']=os.environ['GOLDCHAT_SMTP_FROM'];message['To']=address
        message['Subject']='Your GOLDCHAT verification code';message.set_content(text)
        host=os.environ['GOLDCHAT_SMTP_HOST'];port=int(os.environ.get('GOLDCHAT_SMTP_PORT','587'))
        client=smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context()) if port==465 else smtplib.SMTP(host,port,timeout=15)
        with client:
            if port!=465:client.starttls(context=ssl.create_default_context())
            if os.environ.get('GOLDCHAT_SMTP_USER'):client.login(os.environ['GOLDCHAT_SMTP_USER'],os.environ['GOLDCHAT_SMTP_PASSWORD'])
            client.send_message(message)
    else:
        sid=os.environ['GOLDCHAT_TWILIO_SID'];token=os.environ['GOLDCHAT_TWILIO_TOKEN']
        if not re.fullmatch(r'AC[a-fA-F0-9]{32}',sid):raise ValueError('Invalid SMS configuration')
        data=urllib.parse.urlencode({'From':os.environ['GOLDCHAT_TWILIO_FROM'],'To':address,'Body':text}).encode()
        req=urllib.request.Request(f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json',data=data,
            headers={'Authorization':'Basic '+base64.b64encode(f'{sid}:{token}'.encode()).decode()})
        with urllib.request.urlopen(req,timeout=15) as response:response.read()

class StartIn(BaseModel):
    channel:str
    address:str=Field(max_length=254)
    purpose:str='register'
class VerifyIn(BaseModel):
    challenge_id:str=Field(max_length=100)
    code:str=Field(max_length=12)
class ResetIn(VerifyIn):
    password:str=Field(min_length=8,max_length=128)

def install(app,b):
    @contextmanager
    def db():
        connection=b['get_db']()
        try:
            with connection:yield connection
        finally:connection.close()
    configured_key=os.environ.get('GOLDCHAT_VERIFICATION_SECRET')
    if configured_key:
        if len(configured_key)<32:raise ValueError('Verification secret must be at least 32 characters')
        key=configured_key.encode()
    else:
        key_path=b['DATA_DIR']/'.verification-key'
        if not key_path.exists():
            try:
                with key_path.open('xb') as f:f.write(secrets.token_bytes(32))
            except FileExistsError:pass
        key=key_path.read_bytes()
    def code_hash(cid,code):return hmac.new(key,(cid+':'+code).encode(),hashlib.sha256).hexdigest()
    def check_code(conn,body,purpose,user_id=None):
        row=conn.execute('SELECT * FROM verification_challenges WHERE id=?',(body.challenge_id,)).fetchone()
        valid=row and row['purpose']==purpose and row['channel']=='email' and not row['consumed'] and row['expires_at']>time.time() and row['attempts']<5
        if purpose=='link':valid=valid and row['user_id']==user_id
        if not valid:return None
        conn.execute('UPDATE verification_challenges SET attempts=attempts+1 WHERE id=?',(row['id'],))
        return row if hmac.compare_digest(row['code_hash'],code_hash(row['id'],body.code)) else None

    @app.get('/api/auth/options')
    def options():return {'email':delivery_ready('email'),'phone':False}

    @app.post('/api/auth/verification/start')
    def start(body:StartIn,request:Request,token:str=Depends(b['session_token'])):
        if body.purpose not in {'register','reset','link'}:raise HTTPException(400,'Invalid verification request')
        if body.channel!='email':raise HTTPException(400,'GOLDCHAT uses email verification only')
        address=normalize(body.channel,body.address)
        if not delivery_ready(body.channel):raise HTTPException(503,'Email verification is not configured yet' if body.channel=='email' else 'SMS verification is not configured yet')
        user_id=b['auth_user'](token)['id'] if body.purpose=='link' else None
        now=time.time();ip=request.client.host if request.client else 'unknown';cid=secrets.token_urlsafe(24);code=f'{secrets.randbelow(1000000):06d}'
        column='verified_email' if body.channel=='email' else 'verified_phone'
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM verification_challenges WHERE created_at<?',(now-86400,))
            requests=conn.execute('SELECT created_at FROM verification_challenges WHERE address=? AND created_at>?',(address,now-3600)).fetchall()
            ip_count=conn.execute('SELECT COUNT(*) FROM verification_challenges WHERE ip=? AND created_at>?',(ip,now-3600)).fetchone()[0]
            if len(requests)>=5 or ip_count>=20 or any(r[0]>now-60 for r in requests):raise HTTPException(429,'Wait before requesting another code')
            owner=conn.execute(f'SELECT id FROM users WHERE {column}=?',(address,)).fetchone()
            target=owner['id'] if owner else None
            # Unknown recovery addresses receive the same response but no usable code.
            if body.purpose=='reset':user_id=target
            deliver=body.purpose=='reset' and bool(target) or body.purpose!='reset' and (not target or target==user_id)
            conn.execute('INSERT INTO verification_challenges(id,purpose,channel,address,user_id,code_hash,created_at,expires_at,ip) VALUES(?,?,?,?,?,?,?,?,?)',
                (cid,body.purpose,body.channel,address,user_id,code_hash(cid,code if deliver else secrets.token_hex(32)),now,now+600,ip))
        conn.close()
        if deliver:
            try:send_code(body.channel,address,code,body.purpose)
            except Exception:
                with db() as conn:conn.execute('UPDATE verification_challenges SET consumed=1 WHERE id=?',(cid,))
                raise HTTPException(503,'Could not deliver the code. Please try again later.')
        return {'challenge_id':cid,'expires_in':600,'message':'If this address is eligible, a verification code has been sent.'}

    @app.post('/api/auth/verification/confirm')
    def confirm(body:VerifyIn):
        proof=secrets.token_urlsafe(32)
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE');row=check_code(conn,body,'register')
            if row:conn.execute('UPDATE verification_challenges SET proof_hash=?,proof_expires=?,consumed=1 WHERE id=?',
                (hashlib.sha256(proof.encode()).hexdigest(),time.time()+900,row['id']))
        conn.close()
        if not row:raise HTTPException(400,'Invalid, expired or already used code')
        return {'verification_proof':proof,'channel':row['channel']}

    @app.post('/api/auth/password/reset')
    async def reset(body:ResetIn):
        pw,salt=b['hash_pw'](body.password)
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE');row=check_code(conn,body,'reset')
            if row and row['user_id']:
                conn.execute('UPDATE users SET password_hash=?,salt=? WHERE id=?',(pw,salt,row['user_id']))
                conn.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
                conn.execute('UPDATE device_links SET consumed=1 WHERE approved_uid=?',(row['user_id'],))
                conn.execute('UPDATE verification_challenges SET consumed=1,proof_hash=NULL WHERE user_id=? OR id=?',(row['user_id'],row['id']))
            else:row=None
        conn.close()
        if not row:raise HTTPException(400,'Invalid, expired or already used code')
        for info in list(b['mgr'].active.values()):
            if info['user_id']==row['user_id']:
                try:await info['ws'].close(code=4401)
                except Exception:pass
        return {'ok':True}

    @app.post('/api/auth/contact/confirm')
    def link(body:VerifyIn,token:str=Depends(b['session_token'])):
        user=b['auth_user'](token)['id']
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE');row=check_code(conn,body,'link',user)
                if row:
                    col='verified_email' if row['channel']=='email' else 'verified_phone'
                    conn.execute(f'UPDATE users SET {col}=?,verified_at=? WHERE id=?',(row['address'],time.time(),user))
                    conn.execute('UPDATE verification_challenges SET consumed=1 WHERE id=?',(row['id'],))
            conn.close()
        except sqlite3.IntegrityError:raise HTTPException(400,'Unable to link this contact')
        if not row:raise HTTPException(400,'Invalid, expired or already used code')
        return {'ok':True}

    @app.get('/api/auth/contact')
    def own_contact(token:str=Depends(b['session_token'])):
        row=b['auth_user'](token)
        return {'email':row['verified_email'],'phone':row['verified_phone']}

    @app.get('/api/users/{user_id}/profile')
    def public_profile(user_id:int,token:str=Depends(b['session_token'])):
        viewer=b['auth_user'](token)['id']
        with db() as conn:
            if conn.execute('SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)',(viewer,user_id,user_id,viewer)).fetchone():
                raise HTTPException(403,'This profile is unavailable while either user has blocked the other')
            row=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        conn.close()
        if not row:raise HTTPException(404,'User not found')
        return {**b['user_public'](row),'bio':row['bio']}

    def consume_registration(conn,proof):
        row=conn.execute("SELECT * FROM verification_challenges WHERE purpose=? AND channel='email' AND proof_hash=? AND proof_expires>?",
            ('register',hashlib.sha256(proof.encode()).hexdigest(),time.time())).fetchone() if proof else None
        if not row:raise HTTPException(400,'Verify your email before creating an account')
        conn.execute('UPDATE verification_challenges SET proof_hash=NULL WHERE id=?',(row['id'],))
        return row
    return consume_registration
