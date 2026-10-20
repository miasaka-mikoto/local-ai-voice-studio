import sys, os, asyncio, json, hashlib, socket, tempfile, csv
from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def denied(*args,**kwargs):
    raise RuntimeError('offline ASGI fixture forbids socket connections')

async def run(case,fmt):
    with tempfile.TemporaryDirectory(prefix='voice-api-export-') as temp:
        root=Path(temp)
        app=create_app(Settings(backend_root=ROOT,data_root=root,database_path=root/'db.sqlite',worker_enabled=False))
        assert any(p.startswith('/api/japanese/') for p in app.openapi()['paths'])
        assert app.state.settings.worker_enabled is False
        trace=[]
        async with app.router.lifespan_context(app):
          if True:
            async def req(method,path,body=None,expected=200):
                raw=json.dumps(body).encode() if body is not None else b''
                messages=[]
                received=False
                async def receive():
                    nonlocal received
                    if not received:
                        received=True
                        return {'type':'http.request','body':raw,'more_body':False}
                    await asyncio.Future()
                async def send(message): messages.append(message)
                scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','root_path':'','headers':[(b'content-type',b'application/json'),(b'content-length',str(len(raw)).encode())],'client':('127.0.0.1',12345),'server':('127.0.0.1',80)}
                await app(scope,receive,send)
                start=next(m for m in messages if m['type']=='http.response.start')
                content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
                response=SimpleNamespace(status_code=start['status'],headers={k.decode():v.decode() for k,v in start['headers']},content=content,text=content.decode(errors='replace'),json=lambda:json.loads(content))
                trace.append({'method':method,'path':path,'body':body,'status':response.status_code})
                assert response.status_code==expected,(path,response.status_code,response.text)
                return response
            async def data(method,path,body=None,expected=200):
                return (await req(method,path,body,expected)).json()
            created=await data('POST','/api/v1/projects',{'name':'synthetic HTTP export regression','kind':'game'},201)
            pid=created['projects'][0]['id']
            lines=[]
            for i in range(5 if case=="multi_reserved" else 3):
                lines.append(await data('POST',f'/api/v1/projects/{pid}/lines',{'text':f'synthetic {i}','ordinal':i,'start_ms':i*1000,'end_ms':i*1000+600},201))
            p=lines[-1]['id'][:8]
            names={
                'collision':['clip','clip_'+p,'clip'],
                'two_duplicate_control':['clip','other','clip'],
                'order_control':['clip','clip','clip_'+p],
                'multi_reserved':['clip','clip_'+p,'clip_'+p+'_2','clip_'+p+'_3','clip'],
                'case_insensitive':['clip','CLIP_'+p.upper(),'Clip'],
            }[case]
            count=len(names)
            for line,name in zip(lines,names):
                patched=await data('PATCH',f"/api/v1/lines/{line['id']}",{'changes':{'asset_name':name,'duration_budget_ms':600},'expected_revision':line['revision']})
                assert patched['asset_name']==name and patched['duration_budget_ms']==600
            fetched=await data('GET',f'/api/v1/projects/{pid}/lines')
            assert [l['asset_name'] for l in fetched]==names
            assert [l['ordinal'] for l in fetched]==list(range(count))
            async def task(path,payload):
                response=await req('POST',path,payload,202);queued=response.json()
                assert queued['status']=='queued'
                assert response.headers['location']==f"/api/v1/tasks/{queued['id']}"
                executed=app.state.runner.run_once()
                assert executed['id']==queued['id'] and executed['status']=='completed',executed
                completed=await data('GET',response.headers['location'])
                assert completed['status']=='completed' and completed['id']==queued['id']
                return completed
            generated=await task(f'/api/v1/projects/{pid}/generations',{'engine_id':'mock','take_count':1,'seed':42})
            source_hashes=[];source_paths=[]
            for line in lines:
                takes=await data('GET',f"/api/v1/lines/{line['id']}/takes")
                assert len(takes)==1;take=takes[0]
                selected=await data('POST',f"/api/v1/lines/{line['id']}/takes/{take['id']}/select",{'locked':True})
                assert selected['selected_take_id']==take['id'] and selected['selection_locked']
                audio=await req('GET',f"/api/v1/takes/{take['id']}/audio")
                source_hashes.append(hashlib.sha256(audio.content).hexdigest())
                source_paths.append(app.state.repository.take_audio_path(take['id']))
            assert len(set(source_hashes))==count
            exported=await task(f'/api/v1/projects/{pid}/exports',{'format':fmt})
            result=exported['result'];output=Path(result['output_path']);dest=output.parent
            if fmt=='project_json': rows=json.loads(output.read_text())['lines']
            elif fmt=='json': rows=json.loads(output.read_text())
            elif fmt=='jsonl': rows=[json.loads(s) for s in output.read_text().splitlines()]
            elif fmt=='csv':
                with output.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
            else: rows=None
            assert [sha256_file(p) for p in source_paths]==source_hashes
            selected_lines=await data('GET',f'/api/v1/projects/{pid}/lines')
            assert all(l['selection_locked'] for l in selected_lines)
            files=sorted((dest/'audio').glob('*.wav'))
            item={'case':case,'format':fmt,'status':exported['status'],'prefix':p,'audio_file_count':len(files),'source_hashes':source_hashes,'source_unchanged':True,'selection_locked':True,'warnings':result['warnings'],'http_trace':trace}
            if rows is not None:
                paths=[row['audio_path'] for row in rows]
                actual=[sha256_file(dest/p) for p in paths]
                matches=[a==b for a,b in zip(actual,source_hashes)]
                item.update(audio_paths=paths,unique_paths=len(set(paths)),destination_hashes=actual,row_matches_source=matches)
                assert len(set(path.lower() for path in paths))==count, item
                assert all(matches), item
                if case=='collision': assert paths==['audio/clip.wav',f'audio/clip_{p}.wav',f'audio/clip_{p}_2.wav']
                if case=='multi_reserved': assert paths[-1]==f'audio/clip_{p}_4.wav'
                if case=='case_insensitive': assert paths[-1]==f'audio/Clip_{p}_2.wav'
                if case=='two_duplicate_control': assert paths==['audio/clip.wav','audio/other.wav',f'audio/clip_{p}.wav']
                if case=='order_control': assert paths==['audio/clip.wav',f"audio/clip_{lines[1]['id'][:8]}.wav",f'audio/clip_{p}.wav']
            else:
                assert output.read_text().count('-->')==count
                assert len(files)==count
                assert sorted(sha256_file(f) for f in files)==sorted(source_hashes)
                item['srt_entries']=count
            old={str(p.relative_to(dest)):sha256_file(p) for p in dest.rglob('*') if p.is_file()}
            again=await task(f'/api/v1/projects/{pid}/exports',{'format':fmt})
            assert Path(again['result']['output_path']).parent!=dest
            assert old=={str(p.relative_to(dest)):sha256_file(p) for p in dest.rglob('*') if p.is_file()}
            assert app.state.runner.run_once() is None
            item['previous_export_unchanged']=True
            return item

async def main():
    socket.socket.connect=denied;socket.create_connection=denied
    results=[]
    for fmt in ['project_json','json','jsonl','csv','srt']:
        results.append(await run(sys.argv[2],fmt))
    print(json.dumps(results,ensure_ascii=False,indent=2))

class ExportHttpNameTests(unittest.TestCase):
    def check_case(self, case):
        with tempfile.TemporaryDirectory(prefix='export-http-child-') as temp:
            env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','LANG','LC_ALL'}}
            env.update(HOME=temp,USERPROFILE=temp,TMP=temp,TEMP=temp,TMPDIR=temp,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--case',case],cwd=temp,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_reserved_fallback(self): self.check_case('collision')
    def test_plain_duplicate_compatibility(self): self.check_case('two_duplicate_control')
    def test_order_control(self): self.check_case('order_control')
    def test_multiple_reserved_suffixes(self): self.check_case('multi_reserved')
    def test_case_insensitive_reservations(self): self.check_case('case_insensitive')

if __name__=='__main__':
    # The real main module creates its default app on import. Isolate that app too.
    import_data=tempfile.TemporaryDirectory(prefix='voice-api-import-')
    os.environ['VOICE_STUDIO_DATA_ROOT']=import_data.name
    os.environ['VOICE_STUDIO_WORKER_ENABLED']='false'
    from app.main import create_app
    from app.config import Settings
    from app.util import sha256_file
    
    try:
        asyncio.run(main())
    finally:
        import_data.cleanup()
