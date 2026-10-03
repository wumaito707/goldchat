"""Local SMTP configuration with Windows-encrypted password storage."""
import base64, getpass, json, os, re
from pathlib import Path
from sms_config import protected_bytes

def load_config(directory):
    path=Path(directory)/'.email-config.json'
    if not path.exists():return
    try:
        config=json.loads(path.read_text(encoding='utf-8'))
        values={'GOLDCHAT_SMTP_HOST':config['host'],'GOLDCHAT_SMTP_PORT':str(config['port']),
                'GOLDCHAT_SMTP_FROM':config['sender'],'GOLDCHAT_SMTP_USER':config['username']}
        if config['encrypted_password'] and not os.environ.get('GOLDCHAT_SMTP_PASSWORD'):
            values['GOLDCHAT_SMTP_PASSWORD']=protected_bytes(base64.b64decode(config['encrypted_password'],validate=True),True).decode()
        for key,value in values.items():
            if value:os.environ.setdefault(key,value)
    except Exception:
        print('Email setup could not be loaded. Run setup-email.bat under the same Windows account as GOLDCHAT.')

def setup():
    print('GOLDCHAT email verification setup')
    print('Use your mail service\'s SMTP settings and SMTP/app password, not a verification code.')
    host=input('SMTP server hostname (press Enter for smtp.gmail.com): ').strip() or 'smtp.gmail.com'
    if not host or len(host)>253 or not re.fullmatch(r'[A-Za-z0-9.-]+',host):raise ValueError('Enter a valid SMTP hostname')
    port=int(input('SMTP port (587 or 465; press Enter for 587): ').strip() or '587')
    if port not in (587,465):raise ValueError('This helper supports port 587 (STARTTLS) or 465 (TLS)')
    sender=input('Sender email address: ').strip()
    if len(sender)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',sender):raise ValueError('Enter a valid sender email address')
    username=input('SMTP username (press Enter to use the sender address): ').strip() or sender
    if host.lower()=='smtp.gmail.com':
        print('Gmail: turn on 2-Step Verification, then create a Google App Password for GOLDCHAT.')
        print('App Passwords: https://myaccount.google.com/apppasswords')
    password=getpass.getpass('SMTP/app password (hidden): ').strip()
    if host.lower()=='smtp.gmail.com':password=password.replace(' ','')
    if not password:raise ValueError('Enter the SMTP password supplied by your mail service')
    directory=Path(os.environ.get('GOLDCHAT_DATA_DIR',str(Path(__file__).parent)));directory.mkdir(parents=True,exist_ok=True)
    config={'host':host,'port':port,'sender':sender,'username':username,
            'encrypted_password':base64.b64encode(protected_bytes(password.encode())).decode()}
    temporary=directory/'.email-config.json.tmp';path=directory/'.email-config.json'
    temporary.write_text(json.dumps(config),encoding='utf-8');temporary.replace(path)
    print('Email settings saved. The password is encrypted for your Windows account.')
    print('Restart GOLDCHAT to load them. No email has been sent by this helper.')

if __name__=='__main__':
    try:setup()
    except (ValueError,OSError,EOFError,KeyboardInterrupt) as error:
        print('Setup was not completed: '+str(error))
        raise SystemExit(1)
