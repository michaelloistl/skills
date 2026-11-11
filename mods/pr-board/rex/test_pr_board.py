import json
import os
import tempfile
import unittest

import pr_board as pb

NOW = 1_800_000_000.0


def pr(n, **kw):
    base = {'number': n, 'title': f'PR {n}', 'url': f'https://github.com/o/r/pull/{n}', 'author': 'me',
            'isDraft': False, 'review': '', 'checks': 'pass', 'mergeable': 'MERGEABLE', 'baseRef': 'develop',
            'headRef': f'branch-{n}', 'sliceOf': None, 'issues': []}
    return {**base, **kw}


def model(prs, **kw):
    board = {'repo': 'o/r', 'prs': prs, 'runs': [], 'runErrors': [], 'merged': [], 'fetchedAt': NOW}
    m = {'board': board, 'loading': False, 'error': None, 'branch': '', 'pin': 0, 'mentions': {}, 'expanded': 0,
         'selected': 0, 'following': 'spec-1 · develop', 'order': []}
    board.update(kw.pop('board', {}))
    return {**m, **kw}


def text(lines):
    return '\n'.join(pb.plain(line) for line in lines)


class DataTest(unittest.TestCase):
    def test_checks_of_reads_the_worst_check(self):
        self.assertEqual(pb.checks_of([]), 'none')
        self.assertEqual(pb.checks_of([{'conclusion': 'SUCCESS'}, {'conclusion': 'FAILURE'}]), 'fail')
        self.assertEqual(pb.checks_of([{'conclusion': 'SUCCESS'}, {'status': 'IN_PROGRESS'}]), 'pending')
        self.assertEqual(pb.checks_of([{'conclusion': 'SUCCESS'}, {'state': 'SUCCESS'}]), 'pass')

    def test_issue_refs_takes_closing_refs_and_body_numbers_outside_code(self):
        raw = {'number': 5, 'closingIssuesReferences': [{'number': 1}],
               'body': 'Part of #2, see #5 and a&#3;\n```\n#4\n```'}
        self.assertEqual(pb.issue_refs(raw), [1, 2])

    def test_linear_refs_dedupes_keys(self):
        t = 'https://linear.app/on/issue/FOL-1/a and https://linear.app/on/issue/FOL-1/b'
        self.assertEqual(pb.linear_refs(t), [{'key': 'FOL-1', 'url': 'https://linear.app/on/issue/FOL-1/a'}])

    def test_parse_runs_drops_acked_and_stateless_rows_and_joins_attention(self):
        rows = [
            {'spec': '1', 'state': 'waiting', 'step': 'explore', 'attention': 'ASK', 'question': 'Q1?'},
            {'spec': '2', 'state': 'done', 'acked': True},
            {'spec': '3'},
            {'spec': '4', 'state': 'running', 'step': 'build', 'pr_url': 'https://github.com/o/r/pull/9'},
        ]
        runs = pb.parse_runs('devbox', json.dumps(rows))
        self.assertEqual([r['spec'] for r in runs], [1, 4])
        self.assertEqual(runs[0]['attention'], 'ASK: Q1?')
        self.assertEqual(runs[1]['prNumber'], 9)

    def test_merged_slices_keeps_the_last_day_of_spec_slices_newest_first(self):
        raw = [
            {'number': 1, 'title': 'a', 'url': 'u1', 'mergedAt': '2027-01-15T07:00:00Z', 'baseRefName': 'agent/local-spec-7-x'},
            {'number': 2, 'title': 'b', 'url': 'u2', 'mergedAt': '2027-01-15T07:50:00Z', 'baseRefName': 'agent/local-spec-7-x'},
            {'number': 3, 'title': 'c', 'url': 'u3', 'mergedAt': '2027-01-10T00:00:00Z', 'baseRefName': 'agent/local-spec-7-x'},
            {'number': 4, 'title': 'd', 'url': 'u4', 'mergedAt': '2027-01-15T07:00:00Z', 'baseRefName': 'develop'},
        ]
        now = pb.parse_time('2027-01-15T08:00:00Z')
        self.assertEqual([m['number'] for m in pb.merged_slices(raw, now)], [2, 1])
        self.assertEqual(pb.ago(600), '10m')

    def test_launch_argv_names_the_session_after_the_action(self):
        argv = pb.launch_argv(pr(42), pb.ACTIONS[0], '/repo', '/home/me/.claude-on')
        self.assertEqual(argv[:9], ['rex', 'new', 'fix-ci-42', '-c', '/repo', '--shell', 'zsh', '--', 'env'])
        self.assertEqual(argv[9:14], ['CLAUDE_CONFIG_DIR=/home/me/.claude-on', 'claude', '--worktree', 'fix-ci-42', '-n'])
        self.assertIn('gh pr checkout 42', argv[-1])


class SessionPrTest(unittest.TestCase):
    def test_pin_beats_mentions_beat_branch(self):
        prs = [pr(1, headRef='feat'), pr(2), pr(3)]
        self.assertEqual(pb.session_pr_of(prs, 3, {2: 4}, 'feat'), (prs[2], 'pinned'))
        self.assertEqual(pb.session_pr_of(prs, 0, {2: 4, 1: 1}, 'feat'), (prs[1], 'most referenced'))
        self.assertEqual(pb.session_pr_of(prs, 0, {99: 4}, 'feat'), (prs[0], 'branch'))
        self.assertEqual(pb.session_pr_of(prs, 0, {}, 'other'), (None, None))

    def test_transcript_texts_reads_prompts_and_tool_inputs_not_reminders_or_replies(self):
        lines = [json.dumps(e) for e in [
            {'type': 'user', 'message': {'content': 'look at PR 3648'}},
            {'type': 'user', 'message': {'content': '<system-reminder>#1 #1</system-reminder>'}},
            {'type': 'user', 'isMeta': True, 'message': {'content': [{'type': 'text', 'text': '#2'}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '#3'},
                                                          {'type': 'tool_use', 'input': {'command': 'gh pr view 3648'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': '#4'}]}},
        ]] + ['not json']
        self.assertEqual(pb.count_mentions(pb.transcript_texts(lines)), {3648: 2})

    def test_block_place_prefers_the_foreground_programs_folder(self):
        process = {'foreground': {'pid': 7, 'argv0': 'claude', 'cwd': '/repo/.claude/worktrees/x'}}
        self.assertEqual(pb.block_place(process, None), ('/repo/.claude/worktrees/x', 7))
        shell = {'foreground': {'pid': 8, 'argv0': '-zsh'}}
        self.assertEqual(pb.block_place(shell, {'pwd': 'file://host/Users/me/repo'}), ('/Users/me/repo', None))

    def test_claude_session_and_hosts_come_from_the_config_dir_that_has_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            on, plain_dir = os.path.join(tmp, '.claude-on'), os.path.join(tmp, '.claude')
            os.makedirs(os.path.join(plain_dir, 'sessions'))
            os.makedirs(on)
            with open(os.path.join(plain_dir, 'sessions', '7.json'), 'w') as f:
                json.dump({'sessionId': 'abc', 'name': 'spec-1'}, f)
            with open(os.path.join(on, 'settings.json'), 'w') as f:
                json.dump({'pluginConfigs': {'pr-board': {'options': {'driveSpecHosts': 'local'}}}}, f)
            self.assertEqual(pb.claude_session(7, [on, plain_dir]), {'configDir': plain_dir, 'id': 'abc', 'name': 'spec-1'})
            saved = pb.CONFIG_DIRS
            pb.CONFIG_DIRS = [on, plain_dir]
            try:
                self.assertEqual(pb.configured_hosts(plain_dir), ['local'])
            finally:
                pb.CONFIG_DIRS = saved


class DrawTest(unittest.TestCase):
    def test_fit_shrinks_the_flex_segment_and_fills_to_width(self):
        line = pb.fit([pb.Seg('#1 '), pb.Seg('a long title', flex=True), pb.Seg('', fill=True), pb.Seg(' ⋯')], 12)
        self.assertEqual(pb.plain(line), '#1 a long… ⋯')
        self.assertEqual(pb.cw(pb.plain(pb.fit([pb.Seg('ab')], 6))), 6)

    def test_the_session_pr_comes_first_marked_with_why(self):
        m = model([pr(1), pr(2)], mentions={2: 3})
        lines, spans, head = pb.render(m, 70)
        out = text(lines)
        self.assertLess(out.index('#2 PR 2'), out.index('#1 PR 1'))
        self.assertIn('◉ this session  most referenced branch-2', out)
        self.assertEqual(m['order'], [2, 1])
        self.assertEqual(head, 4)
        self.assertTrue(all(pb.cw(pb.plain(line)) == 70 for line in lines))

    def test_a_branch_with_no_pr_gets_its_own_card(self):
        self.assertIn('◉ this session  feat', text(pb.render(model([pr(1)], branch='feat'), 60)[0]))

    def test_actions_issues_runs_and_merged_slices_show_on_the_card(self):
        issue = {'number': 9, 'title': 'The issue', 'state': 'OPEN', 'url': 'https://github.com/o/r/issues/9',
                 'linear': [{'key': 'FOL-1', 'url': 'https://linear.app/on/issue/FOL-1/x'}]}
        run = {'spec': 7, 'host': 'devbox', 'state': 'running', 'step': 'build', 'summary': 'landed 1/2; building #8',
               'prNumber': 1, 'attention': None}
        merged = [{'spec': 7, 'number': 8, 'title': 's', 'url': 'u8', 'mergedAt': NOW - 3600}]
        m = model([pr(1, checks='fail', issues=[issue])], expanded=1, selected=1,
                  board={'runs': [run], 'merged': merged})
        lines, spans, _ = pb.render(m, 80)
        out = text(lines)
        for want in ['✗ CI', 'f  Fix CI', 'c  Resolve conflicts', '◉ Pin to this session', '#9  FOL-1  The issue',
                     'spec #7', '▰▱ 1/2 building #8', '@devbox', '⤷ merged #8 1h', '1 failing']:
            self.assertIn(want, out)
        top, bottom = spans[1]
        self.assertTrue(pb.plain(lines[top]).startswith('╔') and pb.plain(lines[bottom]).startswith('╚'))
        row = next(line for line in lines if 'FOL-1' in pb.plain(line))
        col = pb.plain(row).index('FOL-1')
        self.assertEqual(pb.hit_at(row, col), ('open', 'https://linear.app/on/issue/FOL-1/x'))
        actions = next(line for line in lines if 'Fix CI' in pb.plain(line))
        self.assertEqual(pb.hit_at(actions, pb.plain(actions).index('Fix CI')), ('action', 'fix-ci', 1))

    def test_a_run_without_a_listed_pr_shows_under_no_pr_yet(self):
        run = {'spec': 5, 'host': 'local', 'state': 'waiting', 'step': 'explore', 'summary': '', 'prNumber': None,
               'attention': 'ASK: Q1?'}
        out = text(pb.render(model([], board={'runs': [run]}), 60)[0])
        self.assertIn('drive-spec · no PR yet', out)
        self.assertIn('▲ ASK: Q1?', out)


class InputTest(unittest.TestCase):
    def test_parse_input_reads_keys_arrows_and_mouse_presses(self):
        data = 'j\x1b[A\r \x1b[<0;10;3M\x1b[<0;10;3m\x1b[<65;1;1M\x1b[1;5Cq'
        self.assertEqual(pb.parse_input(data), [
            ('key', 'j'), ('key', 'up'), ('key', 'enter'), ('key', 'space'),
            ('mouse', 0, 9, 2), ('mouse', 65, 0, 0), ('key', 'q'),
        ])


if __name__ == '__main__':
    unittest.main()
