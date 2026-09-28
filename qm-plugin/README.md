# Floodgate for QM

Add Floodgate to your [QM](https://github.com/yc-software/qm) workspace so any agent can answer **"Should I send this article to this person?"** with your own River-trained model, plus on-task and draft checks.

Agents get it as a skill. In chat you say "use the floodgate skill…", and the agent runs `python3 skills/floodgate/floodgate.py …` and reports calibrated probabilities with the model's name.

```
$ python3 skills/floodgate/floodgate.py send --article "SemIf: Jev-style decisions in the browser" --person "Aditya: ML engineer building the Floodgate extension"
Floodgate: SEND
  0.92  relevant
  0.78  new_to_them
  0.89  timely
  0.91  appropriate
  model: floodgate-personal-v1
```

## What you need

- A QM deployment directory (the one `qm init` created, with `qm.config.jsonc` and `sandbox/`).
- Node 24 for the `qm` CLI.
- A Floodgate model endpoint (`/v1/systemone`) and its token. See step 1.

## 1. Get a model endpoint

**Your own model (recommended).** Train it on River with your labels (see the [main README](../README.md)), then serve it:

```bash
cd floodgate
export RIVER_API_KEY=rv_...
export FLOODGATE_TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
python -m floodgate.open_jev.server --run models/<your-model-card>.json --port 8791
ngrok http 8791        # QM agents run in the cloud, so they need a public URL
```

Keep the token private: anyone holding it spends your River credits.

**Someone else's model.** Ask them for their endpoint URL and token, sent privately.

## 2. Copy the skill into your QM

```bash
cp -r floodgate/qm-plugin/sandbox/skills/floodgate  <your-qm-deploy>/sandbox/skills/
```

## 3. Point it at your endpoint

Pick one.

**Recommended: environment, so the token stays out of git.** In `qm.config.jsonc`, add to the `sandbox` block:

```jsonc
"sandbox": { ..., "env": { "FLOODGATE_URL": "https://<your-endpoint>" }, "secretEnv": ["FLOODGATE_TOKEN"] }
```

Then put `FLOODGATE_TOKEN=<token>` in the deployment's `.env` and run `npx qm secrets push`.

**Quick: config file.** Fill in `sandbox/skills/floodgate/config.json`. Only do this in a private repo:

```json
{ "url": "https://<your-endpoint>", "token": "<token>", "expect_model": "floodgate-personal-v1" }
```

Set `expect_model` to your checkpoint's name so `status` can catch the wrong model being served. Environment variables win over the config file. We verified the config-file path end to end on our QM; the client also reads `FLOODGATE_URL`, `FLOODGATE_TOKEN` and `FLY_RESIDENT_ENV_FLOODGATE_TOKEN`.

## 4. Validate and deploy

```bash
cd <your-qm-deploy>
npx qm check          # should list: skills: ... floodgate ...
npx qm up             # ships the skill to every agent computer
npx qm conformance    # confirms the live deployment matches
```

## 5. Check it in QM

Start a chat and send:

> Run `python3 skills/floodgate/floodgate.py status` and show me the output.

You want four OK lines:

```
OK    reachable https://<your-endpoint>
OK    token     accepted
OK    model     floodgate-personal-v1
OK    sanity    celebrity gossip -> DON'T SEND (expected DON'T SEND)
Floodgate is ready.
```

Then try a real one:

> Use the floodgate skill (send) to decide whether I should send this article to Aditya. First run the floodgate status check. Article: SemIf: run Jev-style typed decisions fully in the browser with WebGPU, no server (https://github.com/TheoLeeCJ/SemIf-OpenJev). Person: Aditya, ML engineer on my hackathon team, building the Floodgate Chrome extension, which currently needs my laptop as a server. My reason: it could let the extension run the model without my laptop. Report SEND / HOLD / DON'T SEND with each probability and the model used, and if SEND, draft a one-line note to Aditya saying why it's relevant to him.

## Commands

| Command | Answers |
|---|---|
| `send --article "…" --person "…" [--why "…"]` | Should I send this article to this person? SEND / HOLD / DON'T SEND, with relevant, new_to_them, timely and appropriate |
| `status` | Are we using the right things? Checks the server, token, model name and a known answer |
| `ask "<text>" "<yes/no question>"` | Any yes/no check, such as "Does this draft stay on the goal?" |
| `choice "<text>" "<question>" "<opt1>" "<opt2>" …` | Pick one option, with a probability for each |
| `distraction "<page>" --task "<task>"` | Is this page a distraction from the task? |

The `send` verdict is decided in code: relevant or appropriate below 0.4 is DON'T SEND, all four at 0.6 or above is SEND, anything else is HOLD.

## Why a skill and not a QM tool

QM tools need their program baked into the agent image with `qm sandbox publish`, but skills ship with every `qm up`. An earlier version shipped Floodgate as a tool, and agents found the skill but no program. The client is now a stdlib-only Python file inside the skill, so `qm up` is all it takes.

## Optional: the Floodgate card in QM's web UI

Our QM shows a Floodgate card on every empty chat with one-click prompts. The source is on branch [`floodgate-card`](https://github.com/edumame/mm-qm/tree/floodgate-card) of `edumame/mm-qm`, built on QM v0.1.5. To use it, build `deploy/web-ui/Dockerfile` from that branch (for example `fly deploy -a <prefix>-web-ui --dockerfile deploy/web-ui/Dockerfile --remote-only`) and pin the resulting digest under `imageOverrides["web-ui"]` in `qm.config.jsonc`, so later `qm up` runs keep it. Match the branch to your QM version first.

## Tests

```bash
cd floodgate/qm-plugin
python3 -m unittest tests/test_floodgate_skill.py          # 22 offline tests against a mock server
LIVE=1 python3 -m unittest tests/test_floodgate_skill.py   # plus 3 live tests, using your filled-in config.json
```
