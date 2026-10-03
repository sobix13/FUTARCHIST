import json
import tempfile
import unittest
from pathlib import Path
from ownership.core import Store, PERMISSIONS
from ownership.bot import Bot
from ownership.forms import split_answers
from ownership.service import Service
from ownership.simulator import FakeTelegram, message_update, callback_update
from ownership.telegram import Engine

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.sqlite3';self.now=1_790_000_000
        self.s=Store(self.path,1,clock=lambda:self.now,gated=False)
        self.api=FakeTelegram();self.bot=Bot(self.s,'OwnershipDemoBot','https://intake.example')
        self.engine=Engine(self.s,self.bot,self.api,False);self.svc=Service(self.s,'OwnershipDemoBot');self.update_id=0
        with self.s.tx():
            self.s.add_admin(1,2,'Nima');self.s.add_admin(1,3,'Sara');self.team=self.s.team(1,'Internal team')
            self.s.membership(1,self.team,2,list(PERMISSIONS));self.s.membership(1,self.team,3,['read_general'])
            for uid in (101,102,103): self.s.register(uid,'Guest '+str(uid),True)
            self.route=self.s.route(2,self.team,'Team intake','both',2)

    def tearDown(self): self.s.close();self.temp.cleanup()

    def create(self,uid=101,route=None,purpose='both',**changes):
        answers={'name':'Lumen Games','categories':['gaming'],'motivation':'A better game','stage':'beta','network':'testnet','website':'https://example.com','socials':'@lumen_team','raise_status':'unsuccessful','retry':'yes','platform':'MetaDAO','currency':'USDC','target_amount':'500000','raised_amount':'0','metadao':'yes'}
        answers.update(changes);g,f=split_answers(purpose,answers,'Guest '+str(uid))
        with self.s.tx():
            token=(route or self.route)['token']
            if self.s.gated:self.s.activate(uid,token)
            return self.s.save_project(uid,token,g,f,purpose)

    def update(self,text,uid=101,chat=None,group=False):
        self.update_id+=1;u=message_update(self.update_id,uid,text,chat,group)
        self.engine.ingest([u]);self.engine.drain();return u

    def callback(self,data,uid=101,message_id=1):
        self.update_id+=1;u=callback_update(self.update_id,uid,data,message_id)
        self.engine.ingest([u]);self.engine.drain();return u

    def action(self,action,uid=101):
        with self.s.tx(): nonce=self.bot.flow(uid)['nonce']
        return self.callback('f:'+nonce+':'+action,uid)

    def flow(self,uid=101):
        with self.s.tx(): return self.bot.flow(uid)

    def optin(self,uid=101):
        with self.s.tx(): self.s.db.execute('UPDATE users SET invites=1 WHERE id=?',(uid,))
