"""Local API integration checks with disposable storage. Never sends email."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import server

class LocalWebsiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_data=server.DATA;server.DATA=Path(self.temp.name)
        server.SESSIONS.clear();server.LIMITS.clear();server.init_db()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.origin=f'http://127.0.0.1:{self.http.server_port}'
        self.cookie=''
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.DATA=self.old_data;self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        head={'Origin':self.origin,'Content-Type':'application/json','Cookie':self.cookie}
        head.update(headers or {})
        client=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=8)
        client.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,head)
        response=client.getresponse();raw=response.read();result=json.loads(raw) if 'application/json' in response.getheader('Content-Type','') else raw
        cookie=response.getheader('Set-Cookie');code=response.status;client.close()
        if cookie:self.cookie=cookie.split(';')[0]
        return code,result
    def login(self):
        self.assertEqual(self.request('/api/owner/setup',{'password':'disposable-test-only-password'})[0],200)
    def test_access_boundary(self):
        self.assertEqual(self.request('/api/owner/dashboard')[0],401)
        self.assertEqual(self.request('/api/owner/setup',{'password':'disposable-test-only-password'},{'Origin':'http://elsewhere.invalid'})[0],403)
        self.assertEqual(self.request('/server.py')[0],404)
        self.assertEqual(self.request('/%2e%2e/server.py')[0],404)
        self.assertEqual(self.request('/owner')[0],200)
        self.login();self.assertEqual(self.request('/api/owner/setup',{'password':'another-test-password'})[0],409)
        self.assertEqual(self.request('/api/owner/logout',{})[0],200)
        self.assertEqual(self.request('/api/owner/dashboard')[0],401)
    def test_enquiry_persists_and_review_is_guarded(self):
        body={'message':'TEST bakery workflow enquiry','name':'Test Visitor','email':'test@example.invalid','contact_preference':'email','contact_consent':True}
        code,row=self.request('/api/enquiry',body);self.assertEqual(code,200);self.assertEqual(row['outcome'],'received')
        with server.database() as db:self.assertEqual(db.execute('SELECT text FROM submissions WHERE id=?',(row['id'],)).fetchone()[0],body['message'])
        self.assertEqual(self.request('/api/owner/update',{'id':row['id'],'status':'reviewing'})[0],401)
        self.login()
        self.assertEqual(self.request('/api/owner/update',{'id':row['id'],'status':'drafted','draft':'A review draft.','note':'test'})[0],200)
        with patch.object(server,'mail_ready',return_value=False),patch.object(server,'send_mail') as mail:
            self.assertEqual(self.request('/api/owner/send',{'id':row['id'],'confirm':True})[0],503);mail.assert_not_called()
        self.assertEqual(self.request('/api/owner/delete',{'id':row['id']})[0],400)
        self.assertEqual(self.request('/api/owner/delete',{'id':row['id'],'confirm':True})[0],200)
    def test_chat_context_and_unshared_text(self):
        history=[{'role':'user','content':'I run a bakery.'},{'role':'assistant','content':'Which task is repetitive?'}]
        with patch.object(server,'wrapper_request',return_value={'status':'reply','answer':'CONTRACT RESPONSE'}) as bridge:
            code,result=self.request('/api/command',{'message':'Order enquiries','history':history,'ai_consent':True})
            self.assertEqual(code,200);self.assertEqual(result['answer'],'CONTRACT RESPONSE')
            bridge.assert_called_once_with('/chat',{'message':'Order enquiries','history':history})
        with server.database() as db:self.assertIsNone(db.execute('SELECT text FROM submissions WHERE id=?',(result['id'],)).fetchone()[0])
        with patch.object(server,'wrapper_request',return_value={'status':'unavailable','reason':'model_service_unavailable'}):
            _,result=self.request('/api/command',{'message':'Try again','ai_consent':True,'share_text':True})
            self.assertEqual(result['outcome'],'unavailable');self.assertIsNone(result['answer'])
        with server.database() as db:self.assertEqual(db.execute('SELECT text FROM submissions WHERE id=?',(result['id'],)).fetchone()[0],'Try again')
        self.assertEqual(self.request('/api/command',{'message':'No consent'})[0],400)
        self.assertEqual(self.request('/api/command',{'message':'Role injection','history':[{'role':'system','content':'x'}],'ai_consent':True})[0],400)
    def test_analytics_consent_dedupe_and_referrer_minimization(self):
        event={'id':'event-123456789012345','session':'visit-123456789012345','kind':'pageview','referrer':'https://example.invalid/private?secret=abc'}
        self.assertEqual(self.request('/api/event',event)[0],400)
        event['consent']=True
        self.assertEqual(self.request('/api/event',event)[0],200);self.assertEqual(self.request('/api/event',event)[0],200)
        with server.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT referrer FROM events').fetchone()[0],'example.invalid')
            db.execute("UPDATE events SET created='2000-01-01T00:00:00+00:00'")
        server.clean_old()
        with server.database() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
    def test_email_requires_requested_followup(self):
        _,row=self.request('/api/enquiry',{'message':'No follow-up wanted','email':'test@example.invalid','contact_preference':'none','contact_consent':True})
        self.login();self.request('/api/owner/update',{'id':row['id'],'status':'drafted','draft':'Unsent draft'})
        with patch.object(server,'mail_ready',return_value=True),patch.object(server,'send_mail') as mail:
            self.assertEqual(self.request('/api/owner/send',{'id':row['id'],'confirm':True})[0],400);mail.assert_not_called()

if __name__=='__main__':unittest.main()
