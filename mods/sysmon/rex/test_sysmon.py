import unittest

import sysmon as sm

STAT_A = 'cpu  100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0\ncpu1 50 0 50 400 0 0 0 0\n'
STAT_B = 'cpu  200 0 200 1400 100 0 0 100\ncpu0 150 0 50 400 0 0 0 0\ncpu1 50 0 150 1000 100 0 0 100\n'
MEMINFO = 'MemTotal:  1000000 kB\nMemAvailable: 400000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n'


class SourcesTest(unittest.TestCase):
    def test_cpu_sample_reads_busy_steal_and_iowait_between_two_stats(self):
        s = sm.cpu_sample(sm.parse_stat(STAT_A), sm.parse_stat(STAT_B), MEMINFO, '0.5 0.4 0.3 1/2 3')
        self.assertEqual((s['cpu'], s['cores'], s['load']), (30, [100, 22], '0.5 0.4 0.3'))
        self.assertEqual((round(s['steal']), round(s['iowait'])), (10, 10))
        self.assertEqual((s['memUsed'], s['memTotal']), (600000, 1000000))

    def test_parse_pressure_reads_some_avg10(self):
        self.assertEqual(sm.parse_pressure('some avg10=12.50 avg60=1.00\nfull avg10=3.00'), 12.5)
        self.assertIsNone(sm.parse_pressure(None))

    def test_group_key_names_a_worktree_else_the_project(self):
        self.assertEqual(sm.group_key('/h/Development/on/on-vantage/.claude/worktrees/spec-1/app', '/h'), 'spec-1')
        self.assertEqual(sm.group_key('/h/Development/on/on-vantage/app', '/h'), 'on-vantage')
        self.assertEqual(sm.group_key('/tmp', '/h'), 'other')

    def test_group_load_adds_cpu_since_the_last_scan(self):
        procs = [{'pid': 1, 'comm': 'ruby', 'ticks': 300, 'rss': 10, 'cwd': '/h/Development/on/a'},
                 {'pid': 2, 'comm': 'node', 'ticks': 50, 'rss': 5, 'cwd': '/h/Development/on/a'}]
        g = sm.group_load(procs, {1: 100}, 2, '/h', hz=100)
        self.assertEqual(g, [{'name': 'a', 'cpu': 100.0, 'rss': 15, 'procs': 2}])

    def test_parse_scan_stat_handles_spaces_in_the_command(self):
        line = '42 (Web Content) S ' + ' '.join(['0'] * 10) + ' 7 3 ' + ' '.join(['0'] * 8) + ' 2'
        p = sm.parse_scan_stat(42, line, '/x')
        self.assertEqual((p['comm'], p['ticks'], p['rss']), ('Web Content', 10, 2 * sm.PAGE))

    def test_count_deltas_compare_with_an_hour_ago(self):
        history = [{'t': 0, 'counts': {'ruby': 2}}, {'t': 3000, 'counts': {'ruby': 5}}]
        self.assertEqual(sm.count_deltas({'ruby': 4}, history, 3700),
                         [{'name': 'ruby', 'count': 4, 'delta': 2, 'minutes': 62}])

    def test_parse_ss_and_psql(self):
        ss = 'LISTEN 0 4096 0.0.0.0:3000 0.0.0.0:* users:(("ruby",pid=9,fd=5))\nLISTEN 0 128 [::]:22 [::]:*\n'
        self.assertEqual(sm.parse_ss(ss), [{'port': 22, 'proc': '', 'pid': None}, {'port': 3000, 'proc': 'ruby', 'pid': 9}])
        self.assertEqual(sm.parse_psql('app\t3\n(background)\t5\n100\n'),
                         {'used': 8, 'max': 100, 'byDb': [('app', 3), ('(background)', 5)]})

    def test_summarize_tests_splits_medians_by_load(self):
        runs = '\n'.join([
            '{"cwd": "/h/Development/on/a", "duration_s": 10, "busy_groups": 1, "exit_code": 0, "command": "t"}',
            '{"cwd": "/h/Development/on/a", "duration_s": 30, "busy_groups": 3, "exit_code": 1, "command": "t"}',
            'oops',
        ])
        t = sm.summarize_tests(runs, '/h')
        self.assertEqual(t['medians'], [{'project': 'a', 'alone': 10, 'aloneN': 1, 'loaded': 30, 'loadedN': 1}])
        self.assertEqual(t['last'][0]['duration_s'], 30)


class RenderTest(unittest.TestCase):
    STATE = {
        'host': 'devbox', 'uptime': 90000, 'now': 0,
        'sample': {'cpu': 90, 'cores': [80, 20], 'steal': 0.0, 'iowait': 1.0, 'memUsed': 500000, 'memTotal': 1000000,
                   'swapUsed': 0, 'swapTotal': 0, 'load': '1 2 3'},
        'history': [10, 90], 'pressure': {'cpu': 30.0, 'memory': None, 'io': 1.0},
        'disk': {'used': 1073741824, 'total': 2147483648},
        'groups': [{'name': 'spec-1', 'cpu': 150.0, 'rss': 1073741824, 'procs': 3}],
        'procs': [{'name': 'ruby', 'count': 4, 'delta': 2, 'minutes': 62}],
        'ports': [{'port': 3000, 'proc': 'ruby', 'pid': 9, 'cwd': '/h/x', 'clashWith': '/h/y'},
                  {'port': 22, 'proc': '', 'pid': None, 'cwd': '', 'clashWith': None}],
        'postgres': 'n/a', 'docker': None, 'tests': None,
    }

    def test_render_draws_a_card_for_each_section_with_data(self):
        lines = sm.render(self.STATE, 80, '/h')
        text = '\n'.join(sm.plain(line) for line in lines)
        for want in ['◉ devbox · 2 cores · up 1d 1h', ' CPU 90% ', ' MEM 50% ', ' DISK 50% ', ' LOAD 1 ',
                     '╭─ CPU ', '╭─ Memory · Disk ', 'pressure  cpu 30.0%  io 1.0%', '1.0/2.0G', 'load 1 2 3',
                     '╭─ Load by worktree ', 'spec-1', '150%', 'ruby 4 +2', 'changes vs 1h ago',
                     ' 3000 ruby       ~/x', '⚠ was ~/y', 'other 22', 'not reachable']:
            self.assertIn(want, text)
        self.assertNotIn('mem ', text.split('pressure')[1].split('\n')[0])
        self.assertTrue(all(len(sm.plain(line)) == 80 for line in lines))

    def test_bars_take_the_tone_of_their_share(self):
        cpu = sm.meter(90, 10)
        self.assertEqual([(seg.text, seg.fg) for seg in cpu], [('━━━━━━━━━', 'red'), ('━', 'track')])
        self.assertEqual(sm.meter(10, 10)[0].fg, 'green')

    def test_render_waits_for_the_first_sample(self):
        lines = sm.render({'sample': None, 'host': 'devbox'}, 60)
        self.assertIn('Sampling…', sm.plain(lines[-1]))


if __name__ == '__main__':
    unittest.main()
