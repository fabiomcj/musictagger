import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review import describe,effective_values,FIELDS
from research import Research,mb_records,deezer_records,merge_candidates,check_art_url


def row():
    current={key:'' for key in FIELDS};current.update(title='Song (Extended Mix)',artist='Artist',album='Record',date='2020',genre='House')
    return {'id':'test','current':current,'identity':{'title':'Song (Extended Mix)','artist':'Artist','conflict':False},
            'duration':300,'has_cover':True,'selected':0,'decision':'pending','manual':{},'candidates':[],
            'status':'pending','error':''}

class ReviewTests(unittest.TestCase):
    def test_manual_edit_overrides_fill_missing_even_if_blank(self):
        r=row();r['manual']={'title':'My title','genre':''};r['decision']='accepted'
        values=effective_values(r,False)
        self.assertEqual(values['title'],'My title');self.assertEqual(values['genre'],'')
        self.assertIn('genre',describe(r,{})['changes'])

    def test_uncertain_catalog_is_not_silently_written(self):
        r=row();r['status']='review';r['candidates']=[{'safe':False,'proposed':{'title':'Song (Radio Edit)'},'reasons':['Different mix']}]
        self.assertEqual(effective_values(r,True)['title'],r['current']['title'])
        self.assertFalse(describe(r,{'overwrite':True})['will_write'])
        r['manual']={'genre':'Tech House'};r['decision']='accepted'
        self.assertEqual(effective_values(r,True)['title'],r['current']['title'])

    def test_leave_unchanged_disables_every_change_and_rename(self):
        r=row();r.update(decision='skipped',manual={'title':'Other'},local_cover={'path':'unused'})
        r['candidates']=[{'safe':True,'proposed':{'title':'Different'}}]
        result=describe(r,{'rename':True,'overwrite':True})
        self.assertEqual(result['values'],r['current']);self.assertFalse(result['will_write']);self.assertFalse(result['rename']);self.assertFalse(result['cover_pending'])

    def test_optional_missing_fields_do_not_block_other_edits(self):
        r=row();r['has_cover']=False;r['manual']={'title':'New'};r['decision']='accepted'
        result=describe(r,{})
        self.assertTrue(result['will_write']);self.assertTrue(any(p['field']=='cover' for p in result['problems']))

    def test_provider_failure_remains_visible(self):
        r=row();r['research']=[{'name':'MusicBrainz','status':'error','error':'Timeout'}]
        self.assertTrue(any(p['field']=='sources' for p in describe(r,{})['problems']))

    def test_artwork_cannot_fetch_internal_or_untrusted_urls(self):
        for url in ['http://coverartarchive.org/test','https://localhost/test','https://127.0.0.1/x','https://example.com/x','https://archive.org.evil.test/x']:
            with self.assertRaises(ValueError):check_art_url(url)
        check_art_url('https://ia800001.us.archive.org/x.jpg')

    def test_adapters_preserve_worldwide_ids_and_credits(self):
        body={'recordings':[{'id':'abc','title':'Song','length':300000,'artist-credit':[{'name':'A','joinphrase':' & '},{'artist':{'name':'B'}}],
              'releases':[{'id':'release','title':'Album','date':'2020-01-01'}],'isrcs':['GBTEST1234567']}]}
        rec=mb_records(body)[0]
        self.assertEqual(rec['artistName'],'A & B');self.assertEqual(rec['_release'],'release');self.assertEqual(rec['_proposed']['isrc'],'GBTEST1234567')
        dz=deezer_records({'data':[{'id':1,'title':'Song','duration':300,'artist':{'name':'Artist'},'album':{'title':'Record'}}]})[0]
        self.assertEqual(dz['trackTimeMillis'],300000);self.assertEqual(dz['trackId'],'dz:1')

    def test_duplicate_countries_do_not_create_ambiguous_release(self):
        candidate={'safe':True,'score':100,'duration':300,'proposed':{'title':'Song','artist':'A','album':'Album'},'source':'Apple IT','url':'https://a','reasons':[]}
        result=merge_candidates([candidate,dict(candidate,source='Apple US',url='https://b')])
        self.assertEqual(len(result),1);self.assertEqual(len(result[0]['sources']),2);self.assertTrue(result[0]['safe'])

    def test_research_continues_when_one_global_provider_fails(self):
        class FakeCatalog:
            def get_json(self,url,cancelled):
                if 'musicbrainz.org' in url:raise TimeoutError('Service unavailable')
                return {'data':[]}
        found,reports=Research(FakeCatalog(),'/private/tmp').search(row(),{'providers':['musicbrainz','deezer']})
        self.assertEqual(found,[]);self.assertTrue(any(r['status']=='error' for r in reports));self.assertTrue(any(r['name'].startswith('Deezer') and r['status']=='ok' for r in reports))

    def test_world_search_really_queries_all_eight_apple_markets(self):
        from urllib.parse import urlparse, parse_qs
        calls=[]
        class FakeCatalog:
            def get_json(self,url,cancelled):
                calls.append(url)
                return {'results':[]}
        Research(FakeCatalog(),'/private/tmp').search(row(),{'providers':['apple'],'depth':'world'})
        markets=[parse_qs(urlparse(url).query)['country'][0] for url in calls]
        self.assertEqual(markets,['IT','US','GB','DE','FR','NL','JP','BR'])

    def test_cancel_is_not_reported_as_a_provider_error(self):
        class FakeCatalog:
            def get_json(self,url,cancelled):
                raise AssertionError('No request should be sent after cancellation')
        with self.assertRaises(InterruptedError):
            Research(FakeCatalog(),'/private/tmp').search(row(),{'providers':['apple','musicbrainz','deezer']},cancelled=lambda:True)

    def test_unrelated_artist_artwork_is_rejected(self):
        from covers import artwork_matches
        r=row();r['current'].update(artist='Nick Curly',title='Switching Levels')
        self.assertFalse(artwork_matches(r,{'proposed':{'artist':'Artisficial','title':'Switching Levels'}}))
        self.assertTrue(artwork_matches(r,{'proposed':{'artist':'Nick Curly','title':'Switching Levels (Extended Mix)'}}))

    def test_cover_for_verified_track_can_apply_despite_other_tag_warnings(self):
        r=row();r['has_cover']=False;r['candidates']=[{'safe':False,'cover_verified':True,'cover_file':{'path':'cover.jpg'},'proposed':{},'reasons':['Album uncertain']}]
        result=describe(r,{'covers':True})
        self.assertTrue(result['cover_pending']);self.assertEqual(result['cover_status'],'pending')
        r['write_result']={'fields':['title']}
        self.assertFalse(describe(r,{'covers':True})['cover_pending'])
        self.assertEqual(describe(r,{'covers':True})['cover_status'],'missing')
