# Floodgate: how we address the concerns

Own Your Intelligence Hackathon, YC HQ, Sep 27. Submissions open 4:00 PM and close 5:00 PM sharp.
Repo: https://github.com/cyu60/floodgate

Please comment directly on any section. Decisions we need are at the bottom.

## 0. The story (what we tell the judges)

### The one line
**General AI doesn't know where your work ends. Floodgate is a model of your own judgment, trained on River, living in your GBrain.**

### The story in five beats

1. **The person.** A builder sits down to research something for a hackathon. Their work *is* the internet: docs, YouTube explainers, papers, threads. Every blocker ever made fails them, because the same site is work one minute and a rabbit hole the next.
2. **The villain is outside intelligence.** Blockers judge by domain. AI judges by a general model trained on everyone else's idea of "productive". We tested the best decision model on the market, TypeSafe's Jev, on this exact person. It says TypeSafe's own documentation is **75% a distraction** for someone researching TypeSafe. It is not stupid. It just isn't *them*.
3. **The insight.** The only judge that can know where your work ends is one trained on *you*. Open-Jev showed how to turn any open model into a calibrated decision engine: read the model's own "Yes versus No", train it until the number is honest. River lets anyone train that on their own data, without a GPU.
4. **What we built today.** Floodgate. We rebuilt Open-Jev on River and trained it in 20 steps: **70% to 86%** accuracy on held-out decisions, **75% to 88%** on task types it never saw. It sits in your browser, asks "is this page a distraction from what I'm doing right now?" on every page, and locks the ones that are. GBrain tells it what you're doing right now, and stores every decision. When it gets you wrong, you click once, and that correction becomes training data for *your* model.
5. **Why it matters: you own your judgment.** The model is a `river://` checkpoint you own. Share it with your team, keep it private, take it to any agent connected to your GBrain. Floodgate is the first node of a "System 1 of you": the fast, calibrated gut-check that any of your agents can ask. *Is this worth my attention?*

### The 30-second version (for the hallway / the judges' first question)
"Every blocker and every AI judges your attention with someone else's rules. Even Jev, the best decision model out there, calls TypeSafe's docs a distraction for someone researching TypeSafe. Floodgate is a model of *your* judgment: we rebuilt Open-Jev on River, trained it in 20 steps from 70% to 86%, and it guards your browser using what your GBrain knows you're doing. Every time you correct it, it learns you. And you own it."

### The two-minute spoken script (word for word, for the video)
> **[Screen: Jev result, TypeSafe docs = 0.75]**
> "This is Jev, the fastest decision model on the market. I'm researching TypeSafe for this hackathon, and Jev thinks TypeSafe's own docs are a 75% distraction. It isn't wrong about the world. It's wrong about *me*."
>
> **[Screen: README results table]**
> "That's the problem with outside intelligence: it judges you with everyone else's rules. So we built Floodgate, a model of your own judgment. We took Open-Jev, an open recreation of Jev, and rebuilt it on River. Twenty training steps later it went from 70% to 86% on decisions it had never seen."
>
> **[Screen: browser + extension, GBrain task visible]**
> "Here's how it lives. GBrain knows what I'm doing right now: researching Jev. I open a Fireship video about Jev. Through. I drift into a satellite-launch explainer. Interesting, informative, and not my task. Blocked."
>
> **[Screen: click 'this is on task' on a wrong call; show the new training row + GBrain memory]**
> "When it gets me wrong, one click. That correction goes into my GBrain and becomes training data for my next River run. It learns where *my* work ends."
>
> **[Screen: model card / river:// checkpoint]**
> "And the model is mine: a checkpoint I can keep private, share with my team, or plug into any agent on my GBrain."
>
> **[Screen: title card]**
> "Floodgate is the first node of a System 1 of you, a fast, calibrated gut-check your agents can ask. General AI doesn't know where your work ends. Your own model does. Own your intelligence."

### Project description (for the submission form)
Floodgate is a model of your own judgment. It guards your browser by asking one question on every page: is this a distraction from what you're doing right now? General models, including TypeSafe's Jev, judge with outside intelligence: Jev rated TypeSafe's own docs 75% distracting for someone researching TypeSafe. We rebuilt Open-Jev (the open recreation of Jev) on River, porting its typed decision API and calibration, and trained our own model in 20 River steps: held-out accuracy rose from 69.7% to 86.2%, and from 75.4% to 87.7% on unseen task types. A Chrome extension and local gate call the model on every navigation, GBrain supplies your current task and stores every decision, and each one-click correction becomes a training row for your next River run. The result is a calibrated, shareable `river://` model you own: the first node of a "System 1 of you" that any agent can query.

### What makes the story land (checklist)
- [ ] Open on the Jev miss. It is concrete, surprising, and measured.
- [ ] Say "your own judgment" at least twice. That is the theme, in our words.
- [ ] Show one number (70% to 86%), not a table.
- [ ] Show the override becoming data. That is the "it learns *you*" moment.
- [ ] Name both hosts' tools doing what they're best at: River trains, GBrain remembers.
- [ ] End on ownership and the vision, not on productivity.
- [ ] Optional personal hook (Chinat to decide): one honest sentence about his own browser/phone habit as the reason this exists.

## 1. Where we are

- **Built and working:** an open Jev (Open-Jev design) trained on River in 20 steps. Held-out accuracy 69.7% to 86.2%, unseen task types 75.4% to 87.7%. Served with the same API as Jev. Chrome extension + local gate that locks a page when it is a distraction from your stated task, and logs every "this is on task" override as a new training row.
- **Measured against real Jev:** for someone researching TypeSafe, Jev says TypeSafe's own docs are 75% a distraction. General models do not know your task boundaries.
- **Not built yet:** anything using GBrain.

## 2. The concerns we heard, and a proposed answer to each

### A. "The rules are to build something with G-Brain" (organizer, opening remarks)
- **Risk:** highest. If it is required, we could be disqualified from the main prizes.
- **Proposed answer:** ask an organizer now. Either way, integrate GBrain, because it also answers concerns C and D:
  - GBrain provides **what you are supposed to be doing right now** (your current task, from your memory / calendar / daily plan) instead of typing it into a popup.
  - Every gate decision and every override is **written to GBrain as memory**, so your judgment accumulates in your own brain, and any agent connected to GBrain can use it.
- **Open question:** hosted gbrain.io (minutes to set up, needs an account) or self-hosted (they said ~2 hours). Proposal: hosted.

### B. "It's too simple" / "so it's a binary?"
- **Proposed answer:** the yes/no is the atom, not the product. The product is **a calibrated model of your own judgment** that any agent can query. Three ways to show depth in the demo:
  1. The same engine answers choice and score questions too ("which of my projects is this page for?", "how deep is this page, 0 to 3?").
  2. The model gets better from your overrides: show one override turning into a training row.
  3. Real numbers: +16.5 points accuracy after 20 River steps, and Jev getting the TypeSafe docs wrong.

### C. "How is this 'own your own intelligence'? This is from outside sources."
- **Proposed answer:** flip it. Jev and every general model judge with **outside** intelligence: the same weights for everyone. Floodgate learns **your** judgment from **your** history and overrides, trains it on River, and keeps it in **your** GBrain. You own the model (a `river://` checkpoint) and can share it. That is exactly the theme.

### D. "Why can't you just use GBrain or Memorable for that? What is the solution?"
- **Proposed answer:** GBrain and Memorable **remember**. They do not **judge**. Floodgate is the judgment layer: a small trained model that turns your memory into a calibrated decision in one call. River trains it, GBrain feeds it context and stores what it learns.

### E. "The story is not clear. I don't see the path to victory." / "It's all about storytelling."
- **Proposed answer:** one sentence and one moment.
  - **Sentence:** "General AI doesn't know where your work ends. Floodgate is a model of your own judgment, trained on River, living in your GBrain."
  - **Moment:** a researcher studying Jev opens TypeSafe's docs. Jev: 75% distraction. Floodgate lets it through. Then they drift to an informative but unrelated video: blocked. One override, and it learns.

### F. "Judges don't like productivity pitches."
- **Proposed answer:** don't pitch productivity. Pitch **ownership of judgment**: the model is yours, portable, shareable, private. Productivity is just the first use case.

### G. The orchestrator idea (a group of personal models + an orchestrator agent)
- **Proposed answer:** keep it as the vision slide, not today's build. Floodgate is the first node: "System 1 of you". Next nodes: which project am I on, is this email worth answering, is this meeting worth taking. An agent on GBrain asks the right node.

## 3. Options

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **1. Floodgate + GBrain (recommended)** | Keep everything built; add GBrain for current task + decision/override memory; reframe story as "own your judgment" | Uses both hosts' tools; answers every concern; demo is ready | Needs GBrain setup in the next ~45 min |
| 2. Floodgate as-is | Submit what works, River side quest only | Zero new risk | May break the GBrain rule; weaker on "too simple" and "outside sources" |
| 3. Pivot to the orchestrator | Multiple personal models + an agent | Bigger vision | Not buildable and demoable in 70 minutes |

## 4. Two-minute demo script (draft)

1. **0:00 to 0:15. Hook.** "Jev is the fastest decision model on the market. Watch it get my afternoon wrong." Show Jev: TypeSafe docs = 75% distraction while researching TypeSafe.
2. **0:15 to 0:40. Idea.** "General AI judges with outside intelligence. Floodgate is a model of your own judgment. We rebuilt Open-Jev on River and trained it in 20 steps: 70% to 86%."
3. **0:40 to 1:20. Live.** GBrain says my task is "research Jev". Fireship video on Jev: allowed. Informative satellite explainer: blocked. I click "this is on task" on something it got wrong: it becomes a training row and a GBrain memory.
4. **1:20 to 1:45. Ownership.** "The model is a river:// checkpoint I own. I can share it with my team, or keep it private. My browsing never leaves my machine except to train my own model."
5. **1:45 to 2:00. Vision.** "Floodgate is the first node: System 1 of you. Any agent in your GBrain can ask it: is this worth my attention?"

## 5. Submission checklist (window 4:00 to 5:00 PM)

- [x] GitHub URL: https://github.com/cyu60/floodgate
- [ ] 1 to 2 minute video (genesis, what it does, problem it solves)
- [ ] Team name: **Floodgate** (confirm)
- [ ] Emails of all members
- [ ] Project description (draft from the PRD)
- [ ] Side quests: **River AI**, **GBrain** (and any others we qualify for)
- [ ] Double-check every link opens logged out

## 6. Decisions we need now

1. **Is GBrain required?** Who asks the organizer: ____
2. **Option 1, 2 or 3?** Proposal: Option 1.
3. **Hosted GBrain signup:** whose account: ____
4. **Who records the video, and on whose laptop:** ____ (target done by 3:45)
5. **Final story sentence:** keep the one in 2E, or edit here: ____
6. **Team name:** Floodgate, or: ____

## 7. Owners (proposal)

- Chinat: story, demo script, video voice-over
- GBrain integration: ____
- Extension + live demo run: ____
- Submission form and links: ____
