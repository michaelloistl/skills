# Proving a `needs:rex` slice

A slice labelled `needs:rex` changes how a skill drives the Rex app, which the test suites only reach through fakes. Prove it in the Rex session you run in (`REX_SESSION` is set):

1. Work in a throwaway repo with a dummy spec, never this one: the commands you run open tabs and post to GitHub.
2. Walk every acceptance criterion of the slice as the operator would, with the real `rex` CLI.
3. Where real Rex output differs from what a fake in the tests returns, fix the fake in the same slice and say so under `Deviations:`.
4. Close every tab and session you opened.

Report under `Proof:` one line per criterion: what you ran and what Rex showed. A criterion you could not walk goes under `Unverified:` with why.
