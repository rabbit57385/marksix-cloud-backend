"""B3 contract and invariants on an isolated MarkSix cohort."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from marksix_cloud_backend import main, smart_selection as smart
from marksix_cloud_backend.analysis_engine import build_analysis_foundation
from marksix_cloud_backend.analysis_repository import AnalysisSnapshot
from marksix_cloud_backend.draw_sync import source_revision
from marksix_cloud_backend.tests.test_analysis_foundation import history


class SmartSelectionTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = AnalysisSnapshot.from_records(history())
        self.reads = 0
        def load():
            self.reads += 1
            return self.snapshot
        main.app.dependency_overrides[main.get_analysis_snapshot] = load
        self.client = TestClient(main.app)
        self.addCleanup(main.app.dependency_overrides.clear)
        self.addCleanup(self.client.close)

    def get(self, **params):
        return self.client.get('/api/v1/marksix/smart-selection', params=params)

    def test_every_strategy_count_mode_and_revision(self):
        for mode in (False, True):
            current = build_analysis_foundation(self.snapshot, mode).current
            for strategy in smart.SMART_SELECTION_STRATEGIES:
                for count in range(6, 11):
                    before = self.reads
                    r = self.get(count=count, strategy=strategy, include_special=mode, locked='1,2,1', excluded='49,48')
                    self.assertEqual(r.status_code, 200, r.text)
                    self.assertEqual(self.reads, before + 1)
                    body = r.json(); data = body['data']
                    self.assertEqual(body['source_revision'], source_revision(self.snapshot))
                    self.assertEqual(r.headers['X-MarkSix-Source-Revision'], body['source_revision'])
                    self.assertEqual(data['game'], 'marksix')
                    self.assertEqual(data['strategy'], strategy)
                    self.assertIs(data['include_special'], mode)
                    self.assertEqual(data['expected_probability'], f'{6 + int(mode)}/49')
                    self.assertEqual(data['latest_draw']['draw_no'], self.snapshot.draws[-1].draw)
                    self.assertEqual(len(data['latest_draw']['numbers']), 6)
                    self.assertEqual(data['count'], count)
                    ns = [row['number'] for row in data['numbers']]
                    self.assertEqual(ns[:2], [1,2]); self.assertEqual(len(set(ns)), count)
                    self.assertFalse({48,49}.intersection(ns))
                    for row in data['numbers']:
                        expected = current.numbers[row['number']-1]
                        self.assertEqual(row['v7_score'], expected.score)
                        self.assertEqual(row['grade'], expected.grade)
                        self.assertEqual(row['momentum']['10'], round(expected.r10, 2))

    def test_invalid_requests_and_empty_history(self):
        bad = [{'count':5}, {'count':11}, {'strategy':'unknown'}, {'locked':'0'}, {'excluded':'50'},
               {'locked':'1','excluded':'1'}, {'locked':'1,2,3,4,5,6,7'}, {'excluded':','.join(map(str,range(5,50)))}]
        for params in bad:
            self.assertEqual(self.get(**params).status_code,400, params)
        self.assertEqual(self.get(count='x').status_code,422)
        self.snapshot = AnalysisSnapshot.from_records(history(0))
        self.assertEqual(self.get().status_code,409)

    def test_empty_signal_falls_back_to_v7_and_all_locked_stable(self):
        with patch.object(smart.signals,'get_recovery_momentum',return_value={'numbers':[]}):
            with patch.object(smart.random.SystemRandom,'choices',side_effect=lambda pool, **kw: [pool[0]]):
                got = self.get(strategy='recovery').json()['data']['numbers']
                want = smart.signals.ranked(build_analysis_foundation(self.snapshot).current)[:6]
                self.assertEqual([r['number'] for r in got],[r['number'] for r in want])
        data = self.get(locked='1,2,3,4,5,6').json()['data']
        self.assertEqual([r['number'] for r in data['numbers']],list(range(1,7)))
        self.assertTrue(all(r['strategy_detail']['locked'] for r in data['numbers']))
