"""Verified contact registration and recovery. Codes are never returned by APIs."""
import json, base64, hashlib, hmac, os, re, secrets, smtplib, sqlite3, ssl, time
import urllib.parse, urllib.request
from email.message import EmailMessage
from contextlib import contextmanager
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

def init_schema(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(users)')}
    for name,kind in [('verified_email','TEXT'),('verified_phone','TEXT'),('verified_at','REAL')]:
        if name not in columns:conn.execute(f'ALTER TABLE users ADD COLUMN {name} {kind}')
    challenge_columns={r[1] for r in conn.execute('PRAGMA table_info(verification_challenges)')}
    if challenge_columns and 'reusable' not in challenge_columns:conn.execute('ALTER TABLE verification_challenges ADD COLUMN reusable INTEGER NOT NULL DEFAULT 0')
    conn.executescript('''
    CREATE UNIQUE INDEX IF NOT EXISTS verified_email_unique ON users(verified_email);
    CREATE UNIQUE INDEX IF NOT EXISTS verified_phone_unique ON users(verified_phone);
    CREATE TABLE IF NOT EXISTS verification_challenges (
      id TEXT PRIMARY KEY, purpose TEXT NOT NULL, channel TEXT NOT NULL, address TEXT NOT NULL,
      user_id INTEGER, code_hash TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0,
      proof_hash TEXT, proof_expires REAL, ip TEXT NOT NULL, reusable INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS verification_sends(id TEXT PRIMARY KEY,address TEXT NOT NULL,ip TEXT NOT NULL,created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS verification_sends_address ON verification_sends(address,created_at);
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
    text=f'Your GOLDCHAT {purpose} verification code is {code}. It expires in 15 minutes. Repeated requests resend the same code while it remains valid. Do not share it.'
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
    def reusable_code(cid):return f"{int.from_bytes(hmac.new(key,('delivery:'+cid).encode(),hashlib.sha256).digest()[:8],'big')%1000000:06d}"
    def atomic(conn,statements):
        if hasattr(conn,'execute_batch'):conn.execute_batch(statements)
        else:
            try:
                conn.execute('BEGIN IMMEDIATE')
                for sql,args in statements:conn.execute(sql,args)
                conn.commit()
            except Exception:conn.rollback();raise
    def claim_code(conn,body,purpose,marker,user_id=None,proof_expires=None):
        # The second write only runs if this request incremented an eligible
        # challenge; concurrent confirmation cannot reuse a consumed code.
        scope="id=? AND purpose=? AND channel='email' AND consumed=0 AND expires_at>? AND attempts<5"
        args=[body.challenge_id,purpose,time.time()]
        if purpose=='link':scope+=' AND user_id=?';args.append(user_id)
        value=re.sub(r'\s+','',body.code)
        statements=[('UPDATE verification_challenges SET attempts=attempts+1 WHERE '+scope,tuple(args)),
          ("UPDATE verification_challenges SET consumed=1,proof_hash=?,proof_expires=? WHERE changes()=1 AND id=? AND code_hash=? AND consumed=0",(marker,proof_expires,body.challenge_id,code_hash(body.challenge_id,value)))]
        return statements

    @app.get('/api/auth/options')
    def options():return {'email':delivery_ready('email'),'phone':False}

    @app.post('/api/auth/verification/start')
    def start(body:StartIn,request:Request,token:str=Depends(b['session_token'])):
        if body.purpose not in {'register','reset','link'}:raise HTTPException(400,'Invalid verification request')
        if body.channel!='email':raise HTTPException(400,'GOLDCHAT uses email verification only')
        address=normalize(body.channel,body.address)
        if not delivery_ready(body.channel):raise HTTPException(503,'Email verification is not configured yet')
        user_id=b['auth_user'](token)['id'] if body.purpose=='link' else None
        now=time.time();ip=request.client.host if request.client else 'unknown'
        conn=b['get_db']()
        try:
            queries=[('SELECT id FROM users WHERE verified_email=?',(address,)),
                ('SELECT * FROM verification_challenges WHERE address=? AND purpose=? AND channel=? AND consumed=0 AND attempts<5 AND reusable=1 AND expires_at>? ORDER BY created_at DESC LIMIT 1',(address,body.purpose,body.channel,now+60))]
            data=conn.query_batch(queries) if hasattr(conn,'query_batch') else [conn.execute(sql,args).fetchall() for sql,args in queries]
            target=data[0][0]['id'] if data[0] else None
            if body.purpose=='reset':user_id=target
            existing=data[1][0] if data[1] and data[1][0]['user_id']==user_id else None
            cid=existing['id'] if existing else secrets.token_urlsafe(24)
            code=reusable_code(cid)
            deliver=(body.purpose=='reset' and bool(target)) or (body.purpose!='reset' and (not target or target==user_id))
            send_id=secrets.token_urlsafe(18)
            guard="""SELECT ?,?,?,? WHERE
                (SELECT COUNT(*) FROM verification_sends WHERE address=? AND created_at>?)<5
                AND (SELECT COUNT(*) FROM verification_sends WHERE ip=? AND created_at>?)<20
                AND NOT EXISTS(SELECT 1 FROM verification_sends WHERE address=? AND created_at>?)"""
            statements=[('DELETE FROM verification_sends WHERE created_at<?',(now-86400,)),('DELETE FROM verification_challenges WHERE created_at<?',(now-86400,)),('INSERT INTO verification_sends(id,address,ip,created_at) '+guard,(send_id,address,ip,now,address,now-3600,ip,now-3600,address,now-60))]
            if not existing:
                statements.append(('INSERT INTO verification_challenges(id,purpose,channel,address,user_id,code_hash,created_at,expires_at,ip,reusable) SELECT ?,?,?,?,?,?,?,?,?,1 WHERE EXISTS(SELECT 1 FROM verification_sends WHERE id=?)',(cid,body.purpose,body.channel,address,user_id,code_hash(cid,code if deliver else secrets.token_hex(32)),now,now+900,ip,send_id)))
            atomic(conn,statements)
            if not conn.execute('SELECT 1 FROM verification_sends WHERE id=?',(send_id,)).fetchone():raise HTTPException(429,'Wait 60 seconds before resending. You can still use the code already sent.')
        finally:conn.close()
        if deliver:
            try:send_code(body.channel,address,code,body.purpose)
            except Exception:
                # Delivery may already have been accepted upstream. Keep this
                # challenge usable if the email arrives after a timeout.
                return JSONResponse(status_code=503,content={'detail':'Email delivery could not be confirmed. If your code arrives, enter it here. Otherwise wait 60 seconds and resend.','challenge_id':cid,'expires_in':max(0,int((existing['expires_at'] if existing else now+900)-time.time()))})
            if not existing:
                conn=b['get_db']()
                try:atomic(conn,[('UPDATE verification_challenges SET expires_at=? WHERE id=? AND consumed=0',(time.time()+900,cid))])
                finally:conn.close()
        return {'challenge_id':cid,'expires_in':max(0,int((existing['expires_at'] if existing else time.time()+900)-time.time())),'message':'If this address is eligible, a code has been sent. Resending keeps the same code while it is valid.'}

    @app.post('/api/auth/verification/confirm')
    def confirm(body:VerifyIn):
        proof=secrets.token_urlsafe(32);marker=hashlib.sha256(proof.encode()).hexdigest();conn=b['get_db']()
        try:
            atomic(conn,claim_code(conn,body,'register',marker,proof_expires=time.time()+900))
            row=conn.execute('SELECT * FROM verification_challenges WHERE id=? AND proof_hash=?',(body.challenge_id,marker)).fetchone()
        finally:conn.close()
        if not row:raise HTTPException(400,'Incorrect, expired or already used code. Enter the code from this request or resend.')
        return {'verification_proof':proof,'channel':row['channel']}

    @app.post('/api/auth/password/reset')
    async def reset(body:ResetIn):
        pw,salt=b['hash_pw'](body.password);marker=secrets.token_urlsafe(32);conn=b['get_db']()
        claimed='SELECT user_id FROM verification_challenges WHERE id=? AND proof_hash=? AND user_id IS NOT NULL'
        try:
            atomic(conn,[*claim_code(conn,body,'reset',marker),
                ('UPDATE users SET password_hash=?,salt=? WHERE id IN ('+claimed+')',(pw,salt,body.challenge_id,marker)),
                ('DELETE FROM sessions WHERE user_id IN ('+claimed+')',(body.challenge_id,marker)),
                ('UPDATE device_links SET consumed=1 WHERE approved_uid IN ('+claimed+')',(body.challenge_id,marker)),
                ('UPDATE verification_challenges SET consumed=1,proof_hash=NULL WHERE id!=? AND user_id IN ('+claimed+')',(body.challenge_id,body.challenge_id,marker))])
            row=conn.execute('SELECT * FROM verification_challenges WHERE id=? AND proof_hash=? AND user_id IS NOT NULL',(body.challenge_id,marker)).fetchone()
        finally:conn.close()
        if not row:raise HTTPException(400,'Incorrect, expired or already used code. Enter the code from this request or resend.')
        for info in list(b['mgr'].active.values()):
            if info['user_id']==row['user_id']:
                try:await info['ws'].close(code=4401)
                except Exception:pass
        return {'ok':True}

    @app.post('/api/auth/contact/confirm')
    def link(body:VerifyIn,token:str=Depends(b['session_token'])):
        user=b['auth_user'](token)['id'];marker=secrets.token_urlsafe(32);conn=b['get_db']()
        claimed='SELECT address FROM verification_challenges WHERE id=? AND proof_hash=?'
        try:
            atomic(conn,[*claim_code(conn,body,'link',marker,user),('UPDATE users SET verified_email=('+claimed+'),verified_at=? WHERE id=? AND EXISTS('+claimed+')',(body.challenge_id,marker,time.time(),user,body.challenge_id,marker))])
            row=conn.execute('SELECT 1 FROM verification_challenges WHERE id=? AND proof_hash=?',(body.challenge_id,marker)).fetchone()
        except sqlite3.IntegrityError:raise HTTPException(400,'Unable to link this contact')
        finally:conn.close()
        if not row:raise HTTPException(400,'Incorrect, expired or already used code. Enter the code from this request or resend.')
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
