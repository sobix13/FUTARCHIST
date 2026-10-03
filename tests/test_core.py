import hashlib
import hmac
import json
import sqlite3
from decimal import Decimal
from urllib.parse import urlencode
from ownership.core import AppError, PERMISSIONS, tg_auth
from ownership.forms import validate, questions, split_answers
from tests.helpers import Fixture

class FormTests(Fixture):
    def test_general_form_short(self): self.assertEqual(len(questions('general',{})),7)
    def test_no_raise_plan_has_no_amount_questions(self):
        q=questions('raise',{'raise_status':'not_started'});self.assertEqual(len(q),9);self.assertNotIn('currency',q)
    def test_failed_raise_has_retry(self): self.assertIn('retry',questions('raise',{'raise_status':'unsuccessful'}))
    def test_stage_and_network_independent(self):
        self.assertEqual(validate('stage','live'),'live');self.assertEqual(validate('network','testnet'),'testnet')
    def test_required_and_optional(self):
        self.assertIsNone(validate('website',None))
        with self.assertRaises(AppError): validate('name',None)
    def test_multiple_categories_and_duplicates(self): self.assertEqual(validate('categories',['defi','gaming','gaming']),['defi','gaming'])
    def test_empty_category_rejected(self):
        with self.assertRaises(AppError): validate('categories',[])
    def test_invalid_category_rejected(self):
        with self.assertRaises(AppError): validate('categories',['invalid'])
    def test_url_credentials_or_script_rejected(self):
        for text in ('javascript:alert(1)','https://user:password@example.com','not a url'):
            with self.subTest(text=text),self.assertRaises(AppError): validate('website',text)
    def test_socials_validate_line_by_line(self):
        self.assertEqual(validate('socials','@valid_name\nhttps://x.com/example'),'@valid_name\nhttps://x.com/example')
        with self.assertRaises(AppError): validate('socials','@okay\nnot a link')
    def test_money_decimal_persian_and_zero(self):
        self.assertEqual(validate('target_amount','1,000.50'),'1000.50');self.assertEqual(validate('raised_amount','0'),'0')
    def test_money_rejects_nonfinite_negative_and_extreme(self):
        for x in ('NaN','Infinity','-1','1e20','0.0000000001'):
            with self.subTest(x=x),self.assertRaises(AppError): validate('target_amount',x)
    def test_custom_currency(self):
        data={'name':'A','categories':['infra'],'stage':'building','network':'na','raise_status':'planning','currency':'OTHER','currency_code':'gbp','target_amount':'100','metadao':'considering'}
        self.assertEqual(split_answers('raise',data,'Guest')[1]['currency'],'GBP')
    def test_stale_conditional_answers_are_dropped(self):
        data={'name':'A','categories':['infra'],'stage':'building','network':'na','raise_status':'not_started','retry':'yes','currency':'USD','raised_amount':'10','metadao':'no'}
        f=split_answers('raise',data,'Guest')[1];self.assertNotIn('raised_amount',f);self.assertNotIn('retry',f)
    def test_unknown_currency_does_not_mean_zero(self):
        data={'name':'A','categories':['infra'],'stage':'building','network':'na','raise_status':'success','currency':'unknown','metadao':'no'}
        f=split_answers('raise',data,'Guest')[1];self.assertNotIn('target_amount',f)

class AccessTests(Fixture):
    def test_owner_only_admin_management(self):
        with self.assertRaises(AppError): self.s.add_admin(2,55,'New')
    def test_owner_can_see_every_workspace(self): self.assertEqual(len(self.s.spaces(1)),4)
    def test_personal_spaces_are_isolated(self):
        private=self.s.one("SELECT id FROM spaces WHERE creator=2 AND kind='personal'")['id']
        with self.assertRaises(AppError): self.s.check(3,private,'read_general')
    def test_team_membership_does_not_share_personal_projects(self):
        private=self.s.one("SELECT id FROM spaces WHERE creator=2 AND kind='personal'")['id']
        with self.s.tx(): route=self.s.route(2,private,'Private','both',2)
        pid=self.create(route=route)
        with self.assertRaises(AppError): self.s.project(3,pid)
    def test_financial_details_and_cases_redacted(self):
        pid=self.create();p=self.s.project(3,pid);self.assertIsNone(p['fundraising']);self.assertEqual([c['purpose'] for c in p['cases']],['general'])
    def test_financial_filter_requires_access(self):
        self.create()
        with self.assertRaises(AppError): self.s.projects(3,self.team,{'raise_status':'success'})
    def test_general_viewer_cannot_write(self):
        pid=self.create()
        with self.assertRaises(AppError): self.s.note(3,pid,'general','Note')
    def test_member_removal_immediately_blocks_reads(self):
        pid=self.create()
        with self.s.tx(): self.s.membership(1,self.team,3,[])
        with self.assertRaises(AppError): self.s.project(3,pid)
    def test_admin_suspend_and_reactivate(self):
        with self.s.tx(): self.s.deactivate(1,2,False)
        with self.assertRaises(AppError): self.s.actor(2)
        with self.s.tx(): self.s.deactivate(1,2,True)
        self.assertTrue(self.s.actor(2)['active'])
    def test_owner_cannot_be_suspended(self):
        with self.assertRaises(AppError): self.s.deactivate(1,1,False)
    def test_invalid_permission_and_missing_read_rejected(self):
        for ps in (['unknown'],['write_raise'],['read_general','write_raise']):
            with self.subTest(ps=ps),self.assertRaises(AppError): self.s.membership(1,self.team,3,ps)
    def test_personal_space_cannot_add_other_member(self):
        private=self.s.one("SELECT id FROM spaces WHERE creator=2 AND kind='personal'")['id']
        with self.assertRaises(AppError): self.s.membership(1,private,3,['read_general'])
    def test_register_never_promotes_or_reactivates(self):
        self.s.deactivate(1,2,False);self.s.register(2,'Another',True)
        self.assertEqual(self.s.one('SELECT active FROM users WHERE id=2')['active'],0)
        self.s.register(999,'Guest',True);self.assertEqual(self.s.actor(999)['role'],'guest')
    def test_source_admin_immutable_after_assignment(self):
        pid=self.create();case=self.s.project(2,pid)['cases'][0]
        self.s.update_case(2,case['id'],case['version'],assignee=3)
        updated=self.s.project(2,pid)['cases'][0];self.assertEqual(updated['source_admin'],2);self.assertEqual(updated['assignee'],3)
    def test_cross_workspace_assignment_denied(self):
        self.s.add_admin(1,4,'Other');pid=self.create();c=self.s.project(2,pid)['cases'][0]
        with self.assertRaises(AppError): self.s.update_case(2,c['id'],c['version'],assignee=4)
    def test_raise_assignment_requires_raise_access(self):
        pid=self.create();c=next(c for c in self.s.project(2,pid)['cases'] if c['purpose']=='raise')
        with self.assertRaises(AppError): self.s.update_case(2,c['id'],c['version'],assignee=3)
    def test_stale_case_version_conflict(self):
        pid=self.create();c=self.s.project(2,pid)['cases'][0];self.s.update_case(2,c['id'],1,status='reviewing')
        with self.assertRaises(AppError) as ctx:self.s.update_case(2,c['id'],1,status='closed')
        self.assertEqual(ctx.exception.status,409)
    def test_route_revocation(self):
        self.svc.route_status(2,self.route['id'],False)
        with self.assertRaises(AppError): self.s.active_route(self.route['token'])
    def test_route_creator_revocation_stops_new_intake(self):
        self.s.membership(1,self.team,2,['read_general','read_raise'])
        with self.assertRaises(AppError): self.s.active_route(self.route['token'])
    def test_financial_route_creator_rechecked_even_if_assignee_owner(self):
        r=self.s.route(2,self.team,'Owner assigned','both',1);self.s.membership(1,self.team,2,['read_general','routes'])
        with self.assertRaises(AppError):self.s.active_route(r['token'])
    def test_financial_routes_hidden_after_financial_access_revoked(self):
        r=self.s.route(2,self.team,'General','general',2);self.s.membership(1,self.team,2,['read_general','routes'])
        self.assertEqual([x['id'] for x in self.svc.routes(2,self.team)],[r['id']])
    def test_route_cannot_assign_financial_to_viewer(self):
        with self.assertRaises(AppError): self.s.route(2,self.team,'Bad','raise',3)
    def test_general_route_cannot_submit_raise(self):
        r=self.s.route(2,self.team,'General','general',2)
        with self.assertRaises(AppError): self.create(route=r)

class FilterTests(Fixture):
    def test_and_across_fields_or_across_categories(self):
        self.create();self.create(uid=102,name='Other',categories=['defi'],stage='live')
        rows=self.s.projects(2,self.team,{'categories':['gaming','defi'],'stage':'beta','network':'testnet','retry':'yes'})
        self.assertEqual(len(rows),1)
    def test_money_requires_currency_even_when_empty(self):
        with self.assertRaises(AppError): self.s.projects(2,self.team,{'min_target':'10'})
    def test_invalid_filter_values_even_when_empty(self):
        for f in ({'status':'bogus'},{'categories':23},{'currency':'USD','min_target':'NaN'},{'currency':'USD','min_target':'20','max_target':'10'},{'unsupported':'x'}):
            with self.subTest(f=f),self.assertRaises(AppError): self.s.projects(2,self.team,f)
    def test_zero_matches_but_unknown_does_not(self):
        self.create();self.create(uid=102,name='Unknown',currency='unknown')
        rows=self.s.projects(2,self.team,{'currency':'USDC','min_raised':'0','max_raised':'0'})
        self.assertEqual(len(rows),1)
    def test_different_currency_never_compared(self):
        self.create();self.create(uid=102,name='SOL project',currency='SOL')
        self.assertEqual(len(self.s.projects(2,self.team,{'currency':'USDC','min_target':'1'})),1)
    def test_case_filters_must_match_same_branch(self):
        pid=self.create();cs=self.s.project(2,pid)['cases'];self.s.update_case(2,cs[0]['id'],1,status='closed')
        self.assertEqual(self.s.projects(2,self.team,{'purpose':'raise','status':'closed'}),[])
    def test_csv_escaping_and_financial_redaction(self):
        self.create(name='=HYPERLINK("danger")');self.s.membership(1,self.team,3,['read_general','export'])
        csv=self.s.csv_export(3,self.team,{})
        self.assertTrue(csv.startswith('\ufeff'));self.assertIn("'=HYPERLINK",csv);self.assertNotIn('target_amount',csv)
    def test_saved_filters_private_to_admin(self):
        self.svc.save_view(2,self.team,'Mine',{'stage':'beta'})
        self.assertEqual(self.svc.views(3,self.team),[])
    def test_repeat_submission_not_duplicate_case(self):
        self.create();self.create();self.assertEqual(self.s.one('SELECT COUNT(*) n FROM projects')['n'],1);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM cases')['n'],2)
    def test_rename_to_existing_project_is_friendly_conflict(self):
        first=self.create();self.create(name='Other');p=self.s.project(2,first);g={**p['general'],'name':'Other'}
        with self.assertRaises(AppError):self.s.save_project(101,self.route['token'],g,p['fundraising'],'both',first,1)
        self.assertEqual(self.s.project(2,first)['general']['name'],'Lumen Games')
    def test_platform_filter_case_insensitive(self):
        self.create();self.assertEqual(len(self.s.projects(2,self.team,{'platform':'metadao'})),1)
    def test_saved_financial_view_hidden_after_revocation(self):
        self.svc.save_view(2,self.team,'Financial',{'raise_status':'planning'})
        self.s.membership(1,self.team,2,['read_general']);self.assertEqual(self.svc.views(2,self.team),[])
    def test_guest_cannot_edit_another_guests_project(self):
        pid=self.create();p=self.s.project(2,pid)
        with self.assertRaises(AppError): self.s.save_project(102,self.route['token'],p['general'],p['fundraising'],'both',pid,1)
    def test_backup_is_consistent(self):
        self.create();backup=self.path.parent/'backup.sqlite3';self.s.backup(backup)
        db=sqlite3.connect(backup);self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],1);db.close()

class AuthTests(Fixture):
    def signed(self,date=None):
        data={'auth_date':str(self.now if date is None else date),'query_id':'Q','user':json.dumps({'id':2,'first_name':'Nima'})}
        key=hmac.new(b'WebAppData',b'123:test',hashlib.sha256).digest()
        data['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
        return urlencode(data)
    def test_telegram_signature_valid(self): self.assertEqual(tg_auth(self.signed(),'123:test',self.now),(2,'Nima'))
    def test_forged_signature_rejected(self):
        with self.assertRaises(AppError):tg_auth(self.signed(),'different',self.now)
    def test_expired_future_and_duplicate_fields_rejected(self):
        for raw in (self.signed(self.now-301),self.signed(self.now+31),self.signed()+'&auth_date=1'):
            with self.subTest(raw=raw[-20:]),self.assertRaises(AppError):tg_auth(raw,'123:test',self.now)
    def test_session_expiration(self):
        token,_=self.s.login(2);self.now+=43201
        with self.assertRaises(AppError): self.s.session(token)
    def test_membership_change_revokes_sessions(self):
        token,_=self.s.login(2);self.s.membership(1,self.team,2,list(PERMISSIONS))
        with self.assertRaises(AppError):self.s.session(token)
    def test_login_link_single_use(self):
        token=self.s.login_link(2);self.assertEqual(self.s.session(self.s.consume_link(token)[0])['user_id'],2)
        with self.assertRaises(AppError):self.s.consume_link(token)
    def test_login_link_expires_and_guest_cannot_login(self):
        token=self.s.login_link(2);self.now+=301
        with self.assertRaises(AppError):self.s.consume_link(token)
        with self.assertRaises(AppError):self.s.login(101)
