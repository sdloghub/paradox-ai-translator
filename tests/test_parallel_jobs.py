"""Isolation and true overlap of Mod tasks without calling a model provider."""
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import workshop_app as app
import test_entry_browser as fixtures


class ParallelJobsTests(unittest.TestCase):
    setUp = fixtures.EntryBrowserTests.setUp

    def wait_done(self):
        deadline = time.monotonic() + 10
        while self.service.busy() and time.monotonic() < deadline:
            threading.Event().wait(.01)
        self.assertFalse(self.service.busy(), self.service.task_statuses())

    def test_two_translations_overlap_and_logs_versions_config_are_isolated(self):
        self.source.write_text('l_english:\n first:0 "Alpha"\n', encoding='utf-8')
        second = self.library / 'steamapps/workshop/content/394360/456/localisation/english/second_l_english.yml'
        second.parent.mkdir(parents=True)
        second.write_text('l_english:\n second:0 "Beta"\n', encoding='utf-8')
        with patch.object(app, 'steam_libraries', return_value=[self.library]):
            self.service.scan(lambda ids: {})
        ready = {uid:threading.Event() for uid in (self.identifier,'394360:456')}
        release = threading.Event()
        self.addCleanup(release.set)
        def action(uid):
            def translator(texts,*args):
                self.service.log('only-' + uid)
                ready[uid].set()
                if not release.wait(5):
                    raise RuntimeError('second translation did not start in parallel')
                self.assertEqual(self.service.config()['provider'], '任务开始配置')
                return [{'text':'中文' + t,'success':True} for t in texts]
            return self.service.translate(uid, translator=translator)
        self.service.save_config({'provider':'任务开始配置'})
        for uid in ready:
            self.service.start('translate', lambda uid=uid:action(uid), uid)
        for event in ready.values():
            self.assertTrue(event.wait(3))
        self.assertTrue(all(self.service.busy(uid) for uid in ready))
        with self.assertRaisesRegex(ValueError, '此 Mod'):
            self.service.start('analyze',lambda:None,self.identifier)
        with self.assertRaises(ValueError):
            with self.service.operation('export',self.identifier):
                pass
        # Shared configuration can change; each active task retains its snapshot.
        self.service.save_config({'provider':'后续任务配置'})
        # Refresh inventory during translation, preserving the live item and its counts.
        old = self.service.get_mod(self.identifier)
        with patch.object(app,'steam_libraries',return_value=[self.library]):
            self.service.start('scan',lambda:self.service.scan(lambda ids:{}))
            deadline=time.monotonic()+3
            while self.service.task_statuses()['__global__']['running'] and time.monotonic()<deadline:
                threading.Event().wait(.01)
        self.assertIs(old,self.service.get_mod(self.identifier))
        release.set()
        self.wait_done()
        jobs=self.service.task_statuses()
        for uid in ready:
            self.assertIsNone(jobs[uid]['error'],jobs[uid])
            self.assertIn('only-'+uid,jobs[uid]['messages'])
            other=next(key for key in ready if key!=uid)
            self.assertNotIn('only-'+other,jobs[uid]['messages'])
            self.assertEqual(self.service.get_mod(uid)['counts']['deployed'],1)
        versions=[j['result']['version_id'] for j in jobs.values() if j['kind']=='translate']
        self.assertEqual(len(set(versions)),2)
        self.assertEqual(self.service.config()['provider'],'后续任务配置')

    def test_failed_mod_does_not_stop_other_task(self):
        gate=threading.Event()
        self.addCleanup(gate.set)
        self.service.start('translate',lambda:gate.wait(3),'mod-one')
        def fail():
            raise ValueError('测试失败')
        self.service.start('analyze',fail,'mod-two')
        deadline=time.monotonic()+2
        while self.service.task_statuses()['mod-two']['running'] and time.monotonic()<deadline:
            threading.Event().wait(.01)
        self.assertEqual(self.service.task_statuses()['mod-two']['error'],'测试失败')
        self.assertTrue(self.service.busy('mod-one'))
        self.assertFalse(self.service.busy('mod-three'))
        gate.set()
        self.wait_done()
