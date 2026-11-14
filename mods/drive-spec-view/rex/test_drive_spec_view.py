import json
import os
import tempfile
import unittest

import drive_spec_view as v

NOW = 1_800_000_000.0


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def tool_line(name, inp):
    return json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': name, 'input': inp}]}})


PLAN = {'spec': 7, 'title': 'Export', 'slices': [
    {'number': 8, 'title': 'First', 'state': 'closed', 'blockers': [], 'labels': [], 'pr': None},
    {'number': 9, 'title': 'Second', 'state': 'todo', 'blockers': [8], 'labels': ['agent:in-progress'], 'pr': None},
    {'number': 10, 'title': 'Third', 'state': 'todo', 'blockers': [9], 'labels': [], 'pr': None},
    {'number': 11, 'title': 'Fourth', 'state': 'todo', 'blockers': [], 'labels': ['agent:blocked'], 'pr': None},
]}


class LogTest(unittest.TestCase):
    def test_last_action_is_the_last_tool_call(self):
        lines = [tool_line('Read', {'file_path': '/r/.claude/worktrees/issue-9/app/x.rb'}),
                 json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result'}]}}),
                 tool_line('Bash', {'command': 'bin/rails test', 'description': 'Run the tests'}),
                 'not json']
        self.assertEqual(v.last_action(lines), ('tool', 'Bash Run the tests'))
        self.assertEqual(v.last_action(lines[:1]), ('tool', 'Read app/x.rb'))

    def test_last_action_reads_a_result_as_finished(self):
        lines = [tool_line('Edit', {'file_path': 'a'}), json.dumps({'type': 'result', 'is_error': False})]
        self.assertEqual(v.last_action(lines), ('done', 'finished'))

    def test_last_action_falls_back_to_text_and_none(self):
        text = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Looking\n at it'}]}})
        self.assertEqual(v.last_action([text]), ('text', 'Looking at it'))
        self.assertIsNone(v.last_action([]))


class SliceTest(unittest.TestCase):
    def setUp(self):
        self.notes = tempfile.mkdtemp()
        with open(os.path.join(self.notes, 'landed.jsonl'), 'w') as f:
            f.write(json.dumps({'slice': 8, 'pr': 12, 'at': iso(NOW - 300)}) + '\n')

    def io(self, lines, quiet=0):
        return {'read_lines': lambda _: lines, 'mtime': lambda _: NOW - quiet}

    def test_board_joins_plan_agents_and_landings(self):
        status = {'agents': {'9': {'role': 'implementer', 'log': '/l', 'started_at': iso(NOW - 120)}}}
        rows = v.board_slices(PLAN, status, self.notes, NOW, **self.io([tool_line('Grep', {'pattern': 'x'})]))
        by = {s['number']: s for s in rows}
        self.assertEqual([s['number'] for s in rows], [8, 9, 10, 11])
        self.assertEqual((by[8]['state'], by[8]['landed_at']), ('landed', NOW - 300))
        self.assertEqual(by[9]['state'], 'building')
        self.assertEqual((by[9]['agent']['elapsed'], by[9]['agent']['action']), (120, ('tool', 'Grep x')))
        self.assertEqual((by[10]['state'], by[10]['waiting_on']), ('todo', [9]))
        self.assertEqual(by[11]['state'], 'halted')

    def test_queue_entries_and_mergers(self):
        status = {'agents': {'9': {'role': 'implementer', 'report': 'ok'}, '10': {'role': 'merger'},
                             '11': {'role': 'integrate', 'pr': 3, 'report': None}}}
        by = {s['number']: s['state'] for s in v.board_slices(PLAN, status, None, NOW, **self.io([]))}
        self.assertEqual((by[9], by[10], by[11]), ('queued', 'merging', 'queued'))

    def test_without_a_plan_the_agents_alone_show(self):
        status = {'agents': {'9': {'role': 'implementer'}}}
        rows = v.board_slices(None, status, None, NOW, **self.io([]))
        self.assertEqual([(s['number'], s['state']) for s in rows], [(9, 'building')])


class PickTest(unittest.TestCase):
    RUNS = {5: {'pane': 'block:a', 'mux': 'rex', 'state': 'done'}, 6: {'pane': 'block:b', 'state': 'running'},
            7: {'pane': 'block:c', 'mux': 'herdr', 'state': 'halted'}}

    def test_the_followed_pane_names_the_run(self):
        self.assertEqual(v.pick_run(self.RUNS, 'block:a', []), (5, 'pane'))
        self.assertEqual(v.pick_run(self.RUNS, 'block:c', []), (6, 'only active run'))

    def test_dispatch_match_then_the_only_active_run(self):
        self.assertEqual(v.pick_run(self.RUNS, 'block:z', [{'spec': '7', 'pane': 'block:z'}]), (7, 'pane'))
        self.assertEqual(v.pick_run(self.RUNS, None, []), (6, 'only active run'))
        two = {**self.RUNS, 8: {'state': 'waiting'}}
        self.assertEqual(v.pick_run(two, 'block:z', []), (None, None))

    def test_picker_leaves_out_acked_and_fileless_rows_and_puts_waiting_first(self):
        rows = [{'spec': '1', 'state': 'running'}, {'spec': '2', 'state': 'done', 'acked': True},
                {'spec': '3', 'state': None}, {'spec': '4', 'state': 'waiting'}]
        self.assertEqual([r['spec'] for r in v.picker_rows(rows, {})], [4, 1])
        self.assertEqual([r['spec'] for r in v.picker_rows([], self.RUNS)], [7, 6, 5])


class RenderTest(unittest.TestCase):
    def model(self, **kw):
        status = {'state': 'running', 'step': 'build', 'summary': 'landed 1/4; building #9', 'next': 'build #9',
                  'updated_at': iso(NOW - 30), 'repo': 'git@github.com:o/r.git', 'base': 'main',
                  'branch': 'agent/local-spec-7-x', 'pr_url': 'https://github.com/o/r/pull/12'}
        status.update(kw.pop('status', {}))
        agent = {'role': 'implementer', 'elapsed': 120, 'quiet': 10, 'action': ('tool', 'Edit app/x.rb'),
                 'queued': False, 'restarts': 0, 'resumed': False, 'log': '/l'}
        slices = [{'number': 8, 'title': 'First', 'state': 'landed', 'agent': None, 'blockers': [], 'waiting_on': [],
                   'pr': None, 'landed_at': NOW - 300},
                  {'number': 9, 'title': 'Second', 'state': 'building', 'agent': agent, 'blockers': [8],
                   'waiting_on': [], 'pr': None, 'landed_at': None},
                  {'number': 10, 'title': 'Third', 'state': 'todo', 'agent': None, 'blockers': [9],
                   'waiting_on': [9], 'pr': None, 'landed_at': None}]
        m = {'spec': 7, 'status': status, 'plan': PLAN, 'slices': slices, 'picker': [], 'picking': False,
             'selected': 9, 'following': 'r · the run in the followed pane', 'loading': False, 'error': None,
             'now': NOW}
        m.update(kw)
        return m

    def text(self, m, width=90):
        lines, spans, head = v.render(m, width)
        for line in lines:
            self.assertEqual(v.cw(v.plain(line)), width, v.plain(line))
        return '\n'.join(v.plain(l) for l in lines), spans

    def test_run_view_shows_steps_progress_and_slices(self):
        out, spans = self.text(self.model(), 120)
        self.assertIn('spec #7 Export', out)
        self.assertIn('explore › build › review', out)
        self.assertIn(' running  landed 1/4; building #9', out)
        self.assertIn('30s ago', out)
        self.assertIn('▰▱▱ 1/3 landed PR #12 main ← agent/local-spec-7-x', out)
        self.assertIn('⤷ implementer 2m · Edit app/x.rb', out)
        self.assertIn('#10 Third', out)
        self.assertIn('after #9', out)
        top, bottom = spans[9]
        self.assertEqual(bottom - top, 1)

    def test_narrow_view_numbers_the_steps(self):
        out, _ = self.text(self.model(), 50)
        self.assertIn('5 › build › 7', out)

    def test_a_blocking_question_is_boxed_and_a_stall_flagged(self):
        m = self.model(status={'state': 'waiting', 'question': 'Ship the EU pack first? Options a or b.',
                               'question_blocking': True, 'updated_at': iso(NOW - 3600)})
        out, _ = self.text(m)
        self.assertIn('▲ waiting on you', out)
        self.assertIn('Ship the EU pack first?', out)
        stalled = self.model(status={'updated_at': iso(NOW - 3600)})
        lines, _, _ = v.render(stalled, 90)
        age = next(s for l in lines for s in l if s.text == ' 1h00m ago')
        self.assertEqual(age.fg, 'error')

    def test_a_quiet_agent_is_flagged(self):
        m = self.model()
        m['slices'][1]['agent']['quiet'] = 600
        out, _ = self.text(m)
        self.assertIn('⚠ quiet 10m', out)

    def test_clicks_open_the_issue_and_select_the_slice(self):
        lines, spans, _ = v.render(self.model(), 90)
        row = lines[spans[10][0]]
        col = v.plain(row).index('#10')
        self.assertEqual(v.hit_at(row, col), ('open', 'https://github.com/o/r/issues/10'))
        self.assertEqual(v.hit_at(row, col + 6), ('select', 10))

    def test_picker_lists_runs(self):
        m = self.model(picking=True, picker=[{'spec': 7, 'state': 'running', 'step': 'build', 'summary': 's',
                                              'attention': None}], selected=7)
        out, spans = self.text(m)
        self.assertIn('spec #7  running · build  s', out)
        self.assertEqual(v.hit_at(v.render(m, 90)[0][spans[7][0]], 0), ('choose', 7))


class HelpersTest(unittest.TestCase):
    def test_github_url_reads_ssh_and_https_remotes(self):
        self.assertEqual(v.github_url('git@github.com:o/r.git'), 'https://github.com/o/r')
        self.assertEqual(v.github_url('https://github.com/o/r'), 'https://github.com/o/r')
        self.assertIsNone(v.github_url(None))

    def test_status_files_by_spec(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, 'drive-spec', 'status'))
        for name in ('spec-3.json', '.spec-3.lock', 'spec-x.json'):
            open(os.path.join(d, 'drive-spec', 'status', name), 'w').close()
        self.assertEqual(list(v.status_files(d)), [3])

    def test_tail_splits_below_this_pane(self):
        self.assertEqual(v.tail_argv('/l', 'block:me')[:4], ['rex', 'split', '-b', 'block:me'])
        self.assertEqual(v.tail_argv('/l', None)[-1], '/l')


if __name__ == '__main__':
    unittest.main()
