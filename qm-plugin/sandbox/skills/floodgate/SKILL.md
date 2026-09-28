---
name: floodgate
description: Decide whether Chinat should send an article or link to a specific person, using his own River-trained decision model (calibrated probabilities, not prose). Use whenever asked "should I send this article to X?", before sharing or forwarding a link, or to check whether a draft or page is on task.
---

# floodgate: should I send this article to this person?

Floodgate is a small decision model trained on River on Chinat's own judgments (an open Jev: typed questions in, calibrated probabilities out). Its core job: **should I send this article to this person?** Every link sent costs the other person's attention and a little relationship capital.

Run the client that ships with this skill, from the workspace (stdlib only; endpoint and token come from `skills/floodgate/config.json`, or FLOODGATE_URL / FLOODGATE_TOKEN if set). There is no `floodgate` binary on PATH.

## First: prove we're using the right things
Run `python3 skills/floodgate/floodgate.py status` once per conversation before relying on Floodgate. It checks that the server is reachable, the token is accepted, the model being served is Chinat's personal model (`floodgate-personal-v1`, not the base or public one), and that a known-bad article comes back DON'T SEND. Every `send` answer also prints `model: …` so the source is visible.
If any line says FAIL or WRONG MODEL: never substitute your own judgment for Floodgate's verdict. Say exactly which check failed and that the Floodgate check was skipped; you may add a clearly labelled "my own read" separately.

## Should I send this article? (main use)
1. Get the article: title plus a one- or two-line summary (fetch the URL if needed).
2. Get the person: who they are, what they work on and care about right now, how Chinat knows them. Pull it from memory (the fund-memory skill, past threads) before asking.
3. Run:
   `python3 skills/floodgate/floodgate.py send --article "<title: summary (url)>" --person "<name: role, current focus, relationship>" --why "<Chinat's reason, if given>"`
4. It asks four atomic questions in one call and prints SEND / HOLD / DON'T SEND with each probability:
   - relevant: matches what they care about or work on
   - new_to_them: likely not already seen
   - timely: useful to them right now
   - appropriate: fits the relationship (not salesy, personal, or off-tone)
   Rule (in code): relevant or appropriate < 0.4 means DON'T SEND; all four >= 0.6 means SEND; otherwise HOLD.
5. Report the verdict with the numbers. If SEND, offer a one-line note saying why it's relevant to *them*. If HOLD, say which signal is weak and what would change it.

## Other checks
- Draft on goal: `python3 skills/floodgate/floodgate.py ask "<the draft>" "Does this message stay on the goal: <goal>?"`
- Page on task: `python3 skills/floodgate/floodgate.py distraction "<url or title>" --task "<what we're doing>"`
- Pick one: `python3 skills/floodgate/floodgate.py choice "<context>" "<question>" "<option 1>" "<option 2>"`

## How to read it
- Probabilities are calibrated: 0.8 means right about 80% of the time. Treat 0.4 to 0.6 as unsure and say so.
- One atomic question per concern. Keep math, dates and counting in code.
- The model is tuned on Chinat's own judgments; person context quality drives the answer, so gather it first.
- If the client says it cannot reach the server, continue without it and say the check was skipped.
