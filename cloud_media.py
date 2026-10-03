"""Private Supabase storage; app authorization happens before media retrieval."""
import json,os,urllib.request,urllib.parse,urllib.error
from fastapi import HTTPException
from fastapi.responses import Response,FileResponse

def configured():return all(os.environ.get(k) for k in ('GOLDCHAT_STORAGE_URL','GOLDCHAT_STORAGE_KEY','GOLDCHAT_STORAGE_BUCKET'))
def validate_private():
    if not configured():return
    token=os.environ['GOLDCHAT_STORAGE_KEY']
    request=urllib.request.Request(os.environ['GOLDCHAT_STORAGE_URL'].rstrip('/')+'/storage/v1/bucket/'+urllib.parse.quote(os.environ['GOLDCHAT_STORAGE_BUCKET'],safe=''),headers={'Authorization':'Bearer '+token,'apikey':token})
    try:
        with urllib.request.urlopen(request,timeout=20) as result:bucket=json.load(result)
    except Exception:raise RuntimeError('Cannot verify private storage bucket') from None
    if bucket.get('public') is not False:raise RuntimeError('GOLDCHAT storage bucket must be private')
def object_request(folder,key,method='GET',data=None,mime=None):
    base=os.environ['GOLDCHAT_STORAGE_URL'].rstrip('/')
    if not base.startswith('https://'):raise HTTPException(503,'Storage requires HTTPS')
    bucket=os.environ['GOLDCHAT_STORAGE_BUCKET'];token=os.environ['GOLDCHAT_STORAGE_KEY']
    path='/'.join(urllib.parse.quote(part,safe='') for part in (bucket,folder,key))
    request=urllib.request.Request(base+'/storage/v1/object/'+path,method=method,data=data,
        headers={'Authorization':'Bearer '+token,'apikey':token,**({'Content-Type':mime or 'application/octet-stream'} if data is not None else {})})
    try:
        with urllib.request.urlopen(request,timeout=20) as response:return response.read()
    except urllib.error.HTTPError as error:
        if error.code==404:raise HTTPException(404,'Media unavailable') from None
        raise HTTPException(503,'Media storage is unavailable') from None
    except OSError:raise HTTPException(503,'Media storage is unavailable') from None
def put(root,key,data,mime):
    if configured():object_request(root.name,key,'POST',data,mime)
    else:root.mkdir(exist_ok=True);(root/key).write_bytes(data)
def exists(root,key):return configured() or (root/key).is_file()
def response(root,key,mime,headers,filename=None):
    if configured():
        if filename:headers={**headers,'Content-Disposition':"attachment; filename*=UTF-8''"+urllib.parse.quote(filename)}
        return Response(object_request(root.name,key),media_type=mime,headers=headers)
    if not (root/key).is_file():raise HTTPException(404,'Media unavailable')
    return FileResponse(root/key,media_type=mime,headers=headers,filename=filename)
