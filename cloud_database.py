"""SQLite-compatible access to Turso's authenticated SQL-over-HTTP protocol."""
import base64,json,sqlite3,urllib.request,urllib.parse

def encode(value):
    if value is None:return {'type':'null'}
    if isinstance(value,(bool,int)):return {'type':'integer','value':str(int(value))}
    if isinstance(value,float):return {'type':'float','value':value}
    if isinstance(value,bytes):return {'type':'blob','base64':base64.b64encode(value).decode()}
    return {'type':'text','value':str(value)}

def decode(value):
    kind=value['type']
    if kind=='null':return None
    if kind=='integer':return int(value['value'])
    if kind=='float':return float(value['value'])
    if kind=='blob':return base64.b64decode(value['base64'])
    return value['value']

def post_pipeline(url,token,body):
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    except Exception:raise sqlite3.OperationalError('Cloud database request failed') from None

class Row:
    def __init__(self,columns,values):self.columns=columns;self.values=values
    def keys(self):return self.columns
    def __getitem__(self,key):return self.values[self.columns.index(key)] if isinstance(key,str) else self.values[key]
    def __iter__(self):return iter(self.values)
    def __len__(self):return len(self.values)

class Cursor:
    def __init__(self,connection):self.connection=connection;self.rows=[];self.offset=0;self.lastrowid=None;self.rowcount=-1
    def execute(self,sql,args=()):
        result=self.connection._execute(sql,args);columns=[c['name'] for c in result.get('cols',[])]
        self.rows=[Row(columns,[decode(v) for v in row]) for row in result.get('rows',[])];self.offset=0
        value=result.get('last_insert_rowid');self.lastrowid=int(value) if value is not None else None
        self.rowcount=result.get('affected_row_count',0);return self
    def fetchone(self):
        if self.offset>=len(self.rows):return None
        row=self.rows[self.offset];self.offset+=1;return row
    def fetchall(self):rows=self.rows[self.offset:];self.offset=len(self.rows);return rows
    def __iter__(self):return iter(self.fetchall())
    def executescript(self,script):self.connection.executescript(script);return self

class Connection:
    def __init__(self,url,token):
        url=url.replace('libsql://','https://',1).replace('turso://','https://',1).rstrip('/')
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query:raise ValueError('Use an HTTPS or libsql Turso database URL')
        self.base_url=url;self.token=token;self.baton=None;self.in_transaction=False;self.closed=False;self.row_factory=None
    def _raw(self,sql,args=()):
        body={'requests':[{'type':'execute','stmt':{'sql':sql,'args':[encode(v) for v in args]}}]}
        if self.baton:body['baton']=self.baton
        response=post_pipeline(self.base_url+'/v2/pipeline',self.token,body);self.baton=response.get('baton')
        redirected=response.get('base_url')
        if redirected:
            parsed=urllib.parse.urlparse(redirected);original=urllib.parse.urlparse(self.base_url)
            if parsed.scheme!='https' or parsed.hostname!=original.hostname:raise sqlite3.OperationalError('Untrusted database redirect')
            self.base_url=redirected.rstrip('/')
        item=response['results'][0]
        if item['type']=='error':
            code=item.get('error',{}).get('code','')
            if 'CONSTRAINT' in code:raise sqlite3.IntegrityError('Database constraint failed')
            raise sqlite3.OperationalError('Cloud database SQL operation failed: '+code)
        return item['response']['result']
    def _execute(self,sql,args):
        if self.closed:raise sqlite3.ProgrammingError('Connection is closed')
        command=sql.lstrip().split(None,1)[0].upper() if sql.strip() else ''
        if command in {'INSERT','UPDATE','DELETE','REPLACE'} and not self.in_transaction:
            self._raw('BEGIN');self.in_transaction=True
        result=self._raw(sql,args)
        if command=='BEGIN':self.in_transaction=True
        elif command in {'COMMIT','ROLLBACK'}:self.in_transaction=False
        return result
    def execute_batch(self, statements):
        if self.closed or self.in_transaction:raise sqlite3.ProgrammingError('Batch requires an open connection without a transaction')
        commands=[('BEGIN IMMEDIATE',()),*statements,('COMMIT',())]
        steps=[]
        for i,(sql,args) in enumerate(commands):
            step={'stmt':{'sql':sql,'args':[encode(v) for v in args]}}
            if i:step['condition']={'type':'ok','step':i-1}
            steps.append(step)
        steps.append({'condition':{'type':'not','cond':{'type':'ok','step':len(commands)-1}},'stmt':{'sql':'ROLLBACK'}})
        body={'requests':[{'type':'batch','batch':{'steps':steps}}]}
        if self.baton:body['baton']=self.baton
        self.in_transaction=True
        response=post_pipeline(self.base_url+'/v2/pipeline',self.token,body)
        self.baton=response.get('baton')
        item=response['results'][0]
        if item['type']=='error':raise sqlite3.OperationalError('Cloud database batch request failed')
        result=item['response']['result']
        self.in_transaction=False
        errors=[v for v in result['step_errors'] if v]
        if errors:raise sqlite3.OperationalError('Cloud database batch failed: '+errors[0].get('code',''))

    def cursor(self):return Cursor(self)
    def execute(self,sql,args=()):return self.cursor().execute(sql,args)
    def executemany(self,sql,rows):
        cursor=self.cursor();count=0
        for args in rows:cursor.execute(sql,args);count+=cursor.rowcount
        cursor.rowcount=count;return cursor
    def executescript(self,script):
        self.commit();statement=''
        for char in script:
            statement+=char
            if char==';' and sqlite3.complete_statement(statement):self._raw(statement);statement=''
        if statement.strip():self._raw(statement)
        return self.cursor()
    def commit(self):
        if self.in_transaction:self._raw('COMMIT');self.in_transaction=False
    def rollback(self):
        if self.in_transaction:self._raw('ROLLBACK');self.in_transaction=False
    def close(self):
        if self.closed:return
        try:
            self.rollback()
            if self.baton:post_pipeline(self.base_url+'/v2/pipeline',self.token,{'baton':self.baton,'requests':[{'type':'close'}]})
        finally:self.closed=True;self.baton=None
    def __enter__(self):return self
    def __exit__(self,kind,value,traceback):
        if kind:self.rollback()
        else:self.commit()

def connect(url,token):return Connection(url,token)
