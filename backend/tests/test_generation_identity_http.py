import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

async def run(name_length, observe=False, case="sequential"):
    with tempfile.TemporaryDirectory(prefix="voice-identity-") as temp:
        root = Path(temp)
        app = create_app(Settings(backend_root=ROOT, data_root=root, database_path=root / "db.sqlite", worker_enabled=False))
        trace = []
        async with app.router.lifespan_context(app):
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
            created = await data('POST', '/api/v1/projects', {'name': 'Synthetic identity regression', 'kind': 'game'}, 201)
            pid = created['projects'][0]['id']
            name = ('音' if case == 'unicode' else '😀' if case == 'unicode4' else 'A') * name_length
            if case == 'collapsed': name = 'A' * 50 + ' ' * 100
            if case == 'uuid': name = None
            line = await data('POST', f'/api/v1/projects/{pid}/lines', {'text': 'test', 'external_line_id': name, 'duration_limit_ms': 600}, 201)
            lid = line['id']
            if case == 'uuid': name = lid
            if case == 'priority':
                name = 'short_asset'
                line = await data('PATCH', f'/api/v1/lines/{lid}', {'changes': {'asset_name': name}, 'expected_revision': line['revision']})
            if case == 'asset_name':
                # Use the real import route, rather than pretending LineCreate supports asset_name.
                imported = await data('POST', f'/api/v1/projects/{pid}/imports',
                                      {'lines': [{'lineId': 'Imported', 'text': 'test', 'assetName': name, 'durationLimitMs': 600}]}, 200)
                line = next(l for l in await data('GET', f'/api/v1/projects/{pid}/lines') if l['external_line_id'] == 'Imported')
                lid = line['id']
                assert line['asset_name'] == name
            from app.util import safe_filename
            import app.task_runner as runner_module
            legacy_filename = lambda value, *a, **kw: safe_filename(value)
            before_outputs = []
            real_generate = app.state.runner.mock.generate
            def recording_generate(*args):
                generated = real_generate(*args)
                before_outputs.append((generated.path, generated.path.read_bytes()))
                return generated
            app.state.runner.mock.generate = recording_generate
            async def generate(amplitude, count=1):
                response = await req('POST', f'/api/v1/projects/{pid}/generations', {'line_ids': [lid], 'engine_id': 'mock', 'take_count': count, 'seed': 42, 'parameters': {'amplitude': amplitude}}, 202)
                queued = response.json()
                assert queued['status'] == 'queued'
                completed = app.state.runner.run_once()
                assert completed['id'] == queued['id'] and completed['status'] == 'completed', completed
                assert (await data('GET', response.headers['location']))['status'] == 'completed'
                return [app.state.repository.get_take(t) for t in completed['result']['take_ids']]
            if case == 'legacy':
                with patch.object(runner_module, 'safe_filename', side_effect=legacy_filename):
                    first = (await generate(.05))[0]
            else:
                first = (await generate(.05))[0]
            original = (await req('GET', f"/api/v1/takes/{first['id']}/audio")).content
            selected = await data('POST', f"/api/v1/lines/{lid}/takes/{first['id']}/select", {'locked': True})
            assert selected['selection_locked'] and selected['selected_take_id'] == first['id']
            if case == 'legacy':
                with patch.object(runner_module, 'safe_filename', side_effect=legacy_filename):
                    second = (await generate(.10))[0]
                legacy_files = {p: p.read_bytes() for p in (root / 'projects').rglob('*') if p.is_file()}
                old_rows = app.state.repository.list_takes(lid)
                repeated = (await generate(.10))[0]
                assert repeated['id'] == second['id']
                assert {p: p.read_bytes() for p in (root / 'projects').rglob('*') if p.is_file()} == legacy_files
                assert app.state.repository.list_takes(lid) == old_rows
                third = (await generate(.15))[0]
                assert third['asset_id'] not in [first['asset_id'], second['asset_id']]
                assert all(p.read_bytes() == b for p, b in legacy_files.items())
            else:
                second = (await generate(.10))[0]
            if case == 'retry':
                prior_files = {p: p.read_bytes() for p in (root / 'projects').rglob('*') if p.is_file()}
                repeated = (await generate(.10))[0]
                assert repeated['id'] == second['id']
                assert len(await data('GET', f'/api/v1/lines/{lid}/takes')) == 2
                assert {p: p.read_bytes() for p in (root / 'projects').rglob('*') if p.is_file()} == prior_files
            if case == 'variants':
                batch = await generate(.15, count=8)
                assert len({t['asset_id'] for t in batch}) == 8
                assert len({t['asset_path'] for t in batch}) == 8
                assert [t['variant_no'] for t in batch] == list(range(1, 9))
                assert all(p.read_bytes() == b for p, b in before_outputs)
                assert len({b for p, b in before_outputs[-8:]}) == 8
            old_audio = await req('GET', f"/api/v1/takes/{first['id']}/audio")
            new_audio = await req('GET', f"/api/v1/takes/{second['id']}/audio")
            selected = next(l for l in await data('GET', f'/api/v1/projects/{pid}/lines') if l['id'] == lid)
            with app.state.repository.db.connection() as connection:
                assets = [dict(connection.execute('SELECT * FROM assets WHERE id=?', (take['asset_id'],)).fetchone()) for take in [first, second]]
            sha = lambda b: hashlib.sha256(b).hexdigest()
            actual = [sha(old_audio.content), sha(new_audio.content)]
            result = {'name_length': name_length, 'takes': [first, second], 'assets': assets, 'original_sha': sha(original), 'actual_shas': actual, 'same_asset': first['asset_id'] == second['asset_id'], 'same_path': first['asset_path'] == second['asset_path'], 'old_bytes_unchanged': original == old_audio.content, 'db_sha_matches': [a['sha256'] == s for a, s in zip(assets, actual)], 'selection_unchanged': selected['selected_take_id'] == first['id'] and bool(selected['selection_locked']), 'http_trace': trace}
            assert first['id'] != second['id'] and first['input_hash'] != second['input_hash']
            assert first['input_hash'][:10] != second['input_hash'][:10]
            assert result['selection_unchanged']
            for response in [old_audio, new_audio]:
                assert response.headers['content-type'].startswith('audio/wav')
                with wave.open(io.BytesIO(response.content)) as wav:
                    assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (48000, 3, 1)
            if not observe and case != 'legacy':
                assert result['old_bytes_unchanged'], 'LOCKED_TAKE_BYTES_CHANGED: ' + json.dumps(result)
                assert not result['same_asset'] and not result['same_path']
                assert all(result['db_sha_matches'])
                assert old_audio.content != new_audio.content
            if case == 'legacy':
                assert result['same_asset'] and not result['old_bytes_unchanged']
                assert result['db_sha_matches'] == [False, False]
                result['legacy_existing_corruption_preserved_not_repaired'] = True
            if not observe:
                for t in [first, second] if case != 'legacy' else [third]:
                    basename = Path(t['asset_path']).name
                    if name_length > 102 and case not in {'collapsed', 'priority', 'uuid'}:
                        assert '/by-input/' in t['asset_path'] and t['input_hash'] in basename
                        assert basename.endswith(f"_v{t['variant_no']}_{t['input_hash']}.wav")
                        assert len(basename) <= 120
                    else:
                        assert basename == safe_filename(f"{name}_v{t['variant_no']}_{t['input_hash'][:10]}.wav")
                        assert '/by-input/' not in t['asset_path']
                if case not in {'unicode', 'unicode4'}:
                    # The old selection must still export its current bytes; legacy corruption is not recoverable here.
                    queued = await data('POST', f'/api/v1/projects/{pid}/exports', {'format': 'project_json'}, 202)
                    exported = app.state.runner.run_once()
                    assert exported['id'] == queued['id'] and exported['status'] == 'completed'
                    output = Path(exported['result']['output_path'])
                    row = next(r for r in json.loads(output.read_text())['lines'] if r['selected_take_id'] == first['id'])
                    assert (output.parent / row['audio_path']).read_bytes() == old_audio.content
            return result

async def main():
    def denied(*args, **kwargs):
        raise RuntimeError('Offline identity fixture forbids socket connections')
    socket.socket.connect = denied
    socket.create_connection = denied
    result = await run(int(sys.argv[2]), '--observe' in sys.argv, sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else 'sequential')
    print(json.dumps(result, ensure_ascii=False, indent=2))

class GenerationIdentityHttpTests(unittest.TestCase):
    def check_length(self, length, case="sequential"):
        with tempfile.TemporaryDirectory(prefix='identity-child-') as temp:
            env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'LANG', 'LC_ALL'}}
            env.update(HOME=temp, USERPROFILE=temp, TMP=temp, TEMP=temp, TMPDIR=temp, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--case', str(length), case], cwd=temp, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    def test_long_external_id_preserves_locked_take(self): self.check_length(120)
    def test_102_character_control(self): self.check_length(102)
    def test_103_character_boundary(self): self.check_length(103)
    def test_eight_variants(self): self.check_length(120, 'variants')
    def test_same_input_retry(self): self.check_length(120, 'retry')
    def test_legacy_collision_preserved_without_orphan(self): self.check_length(120, 'legacy')
    def test_long_imported_asset_name(self): self.check_length(120, 'asset_name')
    def test_long_unicode_name(self): self.check_length(120, 'unicode')
    def test_long_four_byte_unicode_name(self): self.check_length(120, 'unicode4')
    def test_uuid_fallback(self): self.check_length(120, 'uuid')
    def test_asset_name_priority(self): self.check_length(120, 'priority')
    def test_sanitized_short_name_compatibility(self): self.check_length(120, 'collapsed')

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='identity-import-') as temp:
        os.environ['VOICE_STUDIO_DATA_ROOT'] = temp
        os.environ['VOICE_STUDIO_WORKER_ENABLED'] = 'false'
        from app.main import create_app
        from app.config import Settings
        asyncio.run(main())
