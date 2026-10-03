"""Local SMS setup; Windows encrypts the saved token for the current user."""
import base64, ctypes, getpass, json, os, re
from pathlib import Path
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protected_bytes(payload,decrypt=False):
    if os.name!='nt':raise RuntimeError('This setup helper requires Windows')
    buffer=ctypes.create_string_buffer(payload)
    source=Blob(len(payload),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));result=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    operation=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    operation.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not operation(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(),'Windows could not protect or unlock the SMS token')
    try:return ctypes.string_at(result.data,result.size)
    finally:kernel.LocalFree(ctypes.cast(result.data,ctypes.c_void_p))

def load_config(directory):
    path=Path(directory)/'.sms-config.json'
    if not path.exists():return
    try:
        config=json.loads(path.read_text(encoding='utf-8'))
        values={'GOLDCHAT_TWILIO_SID':config['sid'],'GOLDCHAT_TWILIO_FROM':config['sender']}
        if not os.environ.get('GOLDCHAT_TWILIO_TOKEN'):
            values['GOLDCHAT_TWILIO_TOKEN']=protected_bytes(base64.b64decode(config['encrypted_token'],validate=True),True).decode()
        for key,value in values.items():os.environ.setdefault(key,value)
    except Exception:
        # Do not log credential values or decrypted content.
        print('SMS setup could not be loaded. Run setup-sms.bat under the same Windows account as GOLDCHAT.')

def setup():
    print('GOLDCHAT Twilio SMS setup')
    print('Find Account SID and Auth Token in your Twilio console. Use a Twilio SMS-capable sender number.')
    sid=input('Twilio Account SID: ').strip()
    if not re.fullmatch(r'AC[a-fA-F0-9]{32}',sid):raise ValueError('Account SID must start with AC followed by 32 hexadecimal characters')
    token=getpass.getpass('Twilio Auth Token (hidden): ').strip()
    if not re.fullmatch(r'[a-fA-F0-9]{32}',token):raise ValueError('Enter the 32-character Twilio Auth Token')
    sender=input('Twilio sender number (for example +12345678901): ').strip()
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}',sender):raise ValueError('Use the full international sender number, starting with +')
    directory=Path(os.environ.get('GOLDCHAT_DATA_DIR',str(Path(__file__).parent)))
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'.sms-config.json';temporary=directory/'.sms-config.json.tmp'
    config={'sid':sid,'sender':sender,'encrypted_token':base64.b64encode(protected_bytes(token.encode())).decode()}
    temporary.write_text(json.dumps(config),encoding='utf-8');temporary.replace(path)
    print('SMS settings saved. The token is encrypted for your Windows account.')
    print('Restart GOLDCHAT to load them. No SMS has been sent by this helper.')

if __name__=='__main__':
    try:setup()
    except (ValueError,OSError,EOFError,KeyboardInterrupt) as error:
        print('Setup was not completed: '+str(error))
        raise SystemExit(1)
