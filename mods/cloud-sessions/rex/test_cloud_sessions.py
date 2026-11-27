import unittest
from datetime import datetime, timezone

import cloud_sessions as c

NOW = 1_800_000_000.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')


def session(id, status, age=60, **extra):
    return {'id': id, 'title': f'Session {id}', 'session_status': status, 'updated_at': iso(NOW - age), **extra}


class RowsTest(unittest.TestCase):
    def test_groups_needs_you_then_working_then_done(self):
        got = c.rows([session('a', 'running'), session('b', 'idle'), session('c', 'requires_action'),
                      session('d', 'failed'), session('e', 'pending'), session('f', 'archived')], NOW)
        self.assertEqual([r['id'] for r in got], ['c', 'd', 'a', 'e', 'b'])
        self.assertEqual([r['group'] for r in got], ['needs'] * 2 + ['working'] * 2 + ['done'])

    def test_most_recent_first_within_a_state(self):
        got = c.rows([session('old', 'running', age=600), session('new', 'running', age=5)], NOW)
        self.assertEqual([r['id'] for r in got], ['new', 'old'])

    def test_hides_stale_idle_and_failed_but_not_a_waiting_approval(self):
        week = 7 * 86400
        got = c.rows([session('i', 'idle', age=week), session('f', 'failed', age=week),
                      session('q', 'requires_action', age=week), session('r', 'running', age=week)], NOW)
        self.assertEqual({r['id'] for r in got}, {'q', 'r'})

    def test_skips_unknown_states(self):
        self.assertEqual(c.rows([session('x', 'mystery')], NOW), [])

    def test_url_and_offline(self):
        [r] = c.rows([session('session_01X', 'running', connection_status='disconnected')], NOW)
        self.assertEqual(r['url'], 'https://claude.ai/code/session_01X')
        self.assertTrue(r['offline'])


class DetailTest(unittest.TestCase):
    def test_names_the_tool_awaiting_approval(self):
        s = session('a', 'requires_action', external_metadata={'pending_action': {'tool_name': 'Bash'}})
        self.assertEqual(c.detail(s), 'Bash wants approval')

    def test_requires_action_without_a_tool(self):
        self.assertEqual(c.detail(session('a', 'requires_action')), 'waiting on you')

    def test_failure_reason(self):
        s = session('a', 'failed', external_metadata={'last_init_error': {'message': 'setup script exited 1'}})
        self.assertEqual(c.detail(s), 'setup script exited 1')

    def test_nothing_for_running(self):
        self.assertEqual(c.detail(session('a', 'running')), '')


class NotifyTest(unittest.TestCase):
    def test_newly_needing_is_new_ids_or_new_states(self):
        before = c.rows([session('a', 'idle'), session('b', 'running')], NOW)
        after = c.rows([session('a', 'idle'), session('b', 'requires_action'), session('n', 'failed')], NOW)
        self.assertEqual({r['id'] for r in c.newly_needing(before, after)}, {'b', 'n'})


class RenderTest(unittest.TestCase):
    def plain(self, lines):
        import re
        return [re.sub(r'\033\[[0-9;?]*[A-Za-z]', '', l) for l in lines]

    def test_keys_follow_row_order_and_empty_groups_say_none(self):
        items = c.rows([session('a', 'running'), session('b', 'requires_action')], NOW)
        out = '\n'.join(self.plain(c.render(items, 80)))
        self.assertIn(' 1 ⚠ Session b', out)
        self.assertIn(' 2 ↻ Session a', out)
        empty = '\n'.join(self.plain(c.render([], 80)))
        self.assertEqual(empty.count('none'), 2)

    def test_lines_fit_the_width(self):
        items = c.rows([session('a', 'requires_action', external_metadata={'pending_action': {'tool_name': 'X' * 200}})], NOW)
        items[0]['title'] = 'T' * 200
        for line in self.plain(c.render(items, 60)):
            self.assertLessEqual(len(line), 60, line)

    def test_shows_the_error_and_keeps_the_list(self):
        items = c.rows([session('a', 'running')], NOW)
        out = '\n'.join(self.plain(c.render(items, 80, errors=['claude: sessions API: HTTP 500'])))
        self.assertIn('HTTP 500', out)
        self.assertIn('Session a', out)


def idle(id, bucket=None, category=None, needs='', **extra):
    return session(id, 'idle', status_bucket=bucket,
                   post_turn_summary={'status_category': category, 'needs_action': needs}, **extra)


class StateTest(unittest.TestCase):
    def test_idle_sessions_sort_by_their_bucket_first(self):
        self.assertEqual(c.state(idle('a', 'working', 'review_ready')), 'waiting')
        self.assertEqual(c.state(idle('a', 'review_ready', 'completed')), 'review')
        self.assertEqual(c.state(idle('a', 'need_input')), 'input')
        self.assertEqual(c.state(idle('a', 'completed', 'completed')), 'done')

    def test_without_a_bucket_the_turn_category_decides(self):
        self.assertEqual(c.state(idle('a', None, 'need_input')), 'input')
        self.assertEqual(c.state(idle('a', None, 'failed')), 'failed')
        self.assertEqual(c.state(idle('a')), 'done')

    def test_a_completed_turn_naming_an_action_needs_you(self):
        self.assertEqual(c.state(idle('a', 'completed', 'completed', needs='Merge PR #5')), 'input')

    def test_running_and_approval_come_from_session_status(self):
        self.assertEqual(c.state(session('a', 'running', status_bucket='completed')), 'running')
        self.assertEqual(c.state(session('a', 'requires_action')), 'approval')
        self.assertIsNone(c.state(session('a', 'archived')))


class CardTest(unittest.TestCase):
    SESSION = idle('s', 'review_ready', 'review_ready', needs='Approve the PR',
                   unread=True, connection_status='disconnected',
                   session_context={'outcomes': [{'git_info': {'repo': 'org/app', 'branches': ['b1']}}]},
                   external_metadata={'current_branches': {'': 'b2'}, 'unpushed_work': True,
                                      'context_usage': {'used_tokens': 250, 'max_tokens': 1000},
                                      'usage': {'cost_usd': 3.456}, 'last_served_model': 'claude-opus-5-5',
                                      'post_turn_summary': {}},
                   )

    def card(self, width=80, hover=False):
        import re
        s = dict(self.SESSION)
        s['post_turn_summary'] = {**s['post_turn_summary'], 'status_detail': 'PR #9 ready',
                                  'recent_action': 'Pushed three commits and opened PR #9. ' * 6}
        [r] = c.rows([s], NOW)
        return [re.sub(r'\033\[[0-9;?]*[A-Za-z]', '', l) for l in c.card(0, r, width, hover, False)]

    def test_card_shows_the_session_at_a_glance(self):
        text = '\n'.join(self.card())
        self.assertIn('◆ Session s', text)
        self.assertIn('ready for review · 1m ●', text)
        self.assertIn('PR #9 ready', text)
        self.assertIn('→ Approve the PR', text)
        self.assertIn('app · b2 ⚑ unpushed', text)
        self.assertIn('ctx 25% · $3.46 · opus-5-5 · offline', text)

    def test_every_card_line_is_the_card_width(self):
        for width in (40, 80):
            for l in self.card(width):
                self.assertEqual(len(l), width, l)

    def test_hover_shows_more_of_the_recent_action(self):
        self.assertGreater(len(self.card(hover=True)), len(self.card()))
        self.assertLessEqual(len(self.card(hover=True)) - len(self.card()), c.HOVER_LINES - 2)


class AccountTest(unittest.TestCase):
    def test_default_folder_also_tries_the_plain_keychain_item(self):
        a = c.account('/h/.claude', home='/h')
        self.assertEqual(a['label'], 'claude')
        self.assertTrue(a['services'][0].startswith('Claude Code-credentials-'))
        self.assertEqual(a['services'][1], 'Claude Code-credentials')

    def fetch(self, tokens, accepted):
        import urllib.error
        def get(token, org):
            if token not in accepted:
                raise urllib.error.HTTPError('u', 401, 'no', {}, None)
            return [session(token, 'running')]
        acct = {'dir': '/h/.claude', 'services': ['x']}
        c_org, c.org_uuid = c.org_uuid, lambda a: 'o'
        try:
            return c.fetch(acct, tokens=lambda a: tokens, get=get)
        finally:
            c.org_uuid = c_org

    def test_fetch_falls_back_to_the_next_token_on_401(self):
        self.assertEqual(self.fetch(['stale', 'fresh'], {'fresh'})[0]['id'], 'fresh')

    def test_fetch_says_to_sign_in_when_every_token_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'CLAUDE_CONFIG_DIR=/h/.claude claude once'):
            self.fetch(['stale'], set())

    def test_fetch_without_a_keychain_item(self):
        with self.assertRaisesRegex(RuntimeError, 'no sign-in'):
            self.fetch([], set())

    def test_other_folders_use_the_hashed_item_only(self):
        import hashlib
        a = c.account('/h/.claude-on', home='/h')
        self.assertEqual(a['label'], 'claude-on')
        self.assertEqual(a['services'], ['Claude Code-credentials-' + hashlib.sha256(b'/h/.claude-on').hexdigest()[:8]])

    def test_default_accounts_are_the_signed_in_folders(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as home:
            for name, signed in (('.claude', True), ('.claude-on', True), ('.claude-old', False)):
                os.mkdir(os.path.join(home, name))
                with open(os.path.join(home, name, '.claude.json'), 'w') as f:
                    json.dump({'oauthAccount': {'organizationUuid': 'o'}} if signed else {}, f)
            self.assertEqual([a['label'] for a in c.default_accounts(home)], ['claude', 'claude-on'])

    def test_fetch_all_merges_tags_and_reports_each_failure(self):
        def fetch(acct):
            if acct['label'] == 'broken':
                raise RuntimeError('HTTP 403')
            return {'claude': [session('a', 'running')], 'claude-on': [session('b', 'requires_action'), session('a', 'running')]}[acct['label']]
        accts = [{'label': 'claude'}, {'label': 'claude-on'}, {'label': 'broken'}]
        items, errors = c.fetch_all(accts, NOW, 2, fetch=fetch)
        self.assertEqual([(r['id'], r['account']) for r in items], [('b', 'claude-on'), ('a', 'claude')])
        self.assertEqual(errors, ['broken: HTTP 403'])

    def test_rows_name_their_account_only_with_several(self):
        import re
        one = [{**r, 'account': 'claude'} for r in c.rows([session('a', 'running')], NOW)]
        two = one + [{**r, 'account': 'claude-on'} for r in c.rows([session('b', 'running')], NOW)]
        strip = lambda ls: re.sub(r'\033\[[0-9;?]*[A-Za-z]', '', '\n'.join(ls))
        self.assertNotIn('│ claude ', strip(c.render(one, 80)))
        self.assertIn('│ claude-on ', strip(c.render(two, 80)))


class ClickTest(unittest.TestCase):
    def test_hits_map_every_line_of_a_card_to_its_session(self):
        items = c.rows([session('a', 'running'),
                        session('b', 'requires_action', external_metadata={'pending_action': {'tool_name': 'Bash'}})], NOW)
        hits = []
        lines = c.render(items, 80, hits=hits)
        self.assertEqual(len(hits), len(lines))
        by_item = {}
        for i, l in zip(hits, lines):
            by_item.setdefault(i, []).append(l)
        self.assertEqual(set(by_item) - {None}, {0, 1})
        self.assertIn('╭', by_item[0][0])
        self.assertIn('╰', by_item[0][-1])
        self.assertTrue(any('Bash wants approval' in l for l in by_item[0]))
        self.assertTrue(all('Session' not in l for l in by_item[None]))

    def test_parse_input_reads_left_presses_and_keys(self):
        data = '\033[<0;12;5M\033[<0;12;5m' + 'r' + '\033[<2;3;4M' + '\033[<64;1;1M'
        self.assertEqual(c.parse_input(data), [('click', 5), ('key', 'r')])

    def test_parse_input_reads_motion_without_a_button(self):
        self.assertEqual(c.parse_input('\033[<35;4;7M\033[<32;4;7M'), [('move', 7)])

    def test_hovered_row_underlines_its_title_only(self):
        items = c.rows([session('a', 'running'), session('b', 'running', age=120)], NOW)
        lines = c.render(items, 80, hover=1)
        [a_line] = [l for l in lines if 'Session a' in l]
        [b_line] = [l for l in lines if 'Session b' in l]
        self.assertNotIn('\033[4m', a_line)
        self.assertIn('\033[4mSession b\033[0m', b_line)

    def test_underline_keeps_the_columns(self):
        items = c.rows([session('a', 'running')], NOW)
        plain = lambda ls: [__import__('re').sub(r'\033\[[0-9;?]*[A-Za-z]', '', l) for l in ls]
        self.assertEqual(plain(c.render(items, 80, hover=0)), plain(c.render(items, 80)))

    def approval_rows(self, **action):
        return c.rows([session('a', 'requires_action', external_metadata={'pending_action': {'tool_name': 'Bash', **action}})], NOW)

    def test_hover_shows_the_pending_approval_and_maps_it_to_its_session(self):
        items = self.approval_rows(action_description='Push the branch', input={'command': 'git push origin main', 'description': 'x'})
        quiet = '\n'.join(c.render(items, 80))
        self.assertNotIn('git push', quiet)
        hits = []
        lines = c.render(items, 80, hits=hits, hover=0)
        shown = [l for l, h in zip(lines, hits) if h == 0]
        self.assertTrue(any('Push the branch' in l for l in shown))
        self.assertTrue(any('git push origin main' in l for l in shown))

    def test_approval_falls_back_to_the_input_as_json(self):
        items = self.approval_rows(input={'weird': [1, 2]})
        self.assertEqual(items[0]['approval'], ['{"weird":[1,2]}'])

    def test_approval_uses_the_display_name(self):
        items = self.approval_rows(display_tool_name='Edit file')
        self.assertEqual(items[0]['headline'], 'Edit file wants approval')

    def test_hovered_approval_is_wrapped_and_capped(self):
        items = self.approval_rows(input={'command': 'x' * 1000})
        plain = lambda ls: [__import__('re').sub(r'\033\[[0-9;?]*[A-Za-z]', '', l) for l in ls]
        lines = plain(c.render(items, 60, hover=0))
        body = [l for l in lines if '│ │ ' in l]
        self.assertEqual(len(body), c.HOVER_LINES)
        self.assertIn('…', body[-1])
        for l in lines:
            self.assertLessEqual(len(l), 60, l)

    def test_parse_input_drops_other_escapes(self):
        self.assertEqual(c.parse_input('q\033[A'), [('key', 'q')])


if __name__ == '__main__':
    unittest.main()
