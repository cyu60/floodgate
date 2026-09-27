# GBrain: a second brain for each person

Integration on branch `tri`. Uses a local GBrain store for each demo person.

Each person gets a private second brain in GBrain that remembers their goals,
preferences, projects, and connections to friends. Their agents use those
memories to understand them. Sharing chosen memories with friends is the next step.
Floodgate uses that context to judge whether a page helps with the person's
current task.

For example, Alice tells her agent, “Bob and I are building Floodgate.” Her brain
connects Alice, Bob, and the project, and remembers where that information came
from. Bob has his own brain. Knowing Bob does not give Alice's agent access to
his private memories.

The first demo uses two made-up people and follows connections across several
steps: project → teammate → collaborator → resource, or milestone → promise →
constraint → resource. See the [90-second presentation script](HACKATHON_DEMO.md).

Install [official GBrain](https://github.com/garrytan/gbrain) with Bun, then run:

```sh
python3 -m floodgate.memory_demo seed
python3 -m floodgate.memory_demo verify
python3 -m floodgate.memory_demo serve
```

Open `http://127.0.0.1:8792`. If GBrain is not on PATH, put
`--gbrain-command /absolute/path/to/gbrain` before `seed`, `verify`, or `serve`.
The demo needs no model key. It saves fictional data under
`~/.local/share/floodgate/demo-brains`; `verify` starts fresh brain processes to
check persistence and relationship retrieval. Stop the demo server before
running another command against those same stores.
Tested with GBrain `0.59.0.0` (commit `e78f1c3`).

To connect Alice's brain to the real browser gate, install the project's Python
dependencies and configure a River key as described in the README, then run:

```sh
python3 -m floodgate.gate_server --run models/open-jev-river-v1.json \
  --brain-home ~/.local/share/floodgate/demo-brains/alice --user-id alice \
  --task "Ship the Atlas offline demo"
```

Memory is optional. The gate retrieves related evidence, saves explicit task/page
corrections, and clears stale scores when context changes. If memory fails, the
River gate continues and reports that memory is unavailable. Overrides are
saved as events; they do not automatically retrain the model.

The implementation is split into `gbrain.py` (connection), `memory.py` (owned
graph), `memory_demo.py` (presentation), and `gate_server.py` (decisions).
Run `python3 -m unittest discover -s tests -v` for the automated checks.
To include the real GBrain integration test in a separate temporary store:

```sh
FLOODGATE_GBRAIN_COMMAND="$(command -v gbrain)" python3 -m unittest discover -s tests -v
```

The server chooses which brain an agent can access. A name or user ID in a
request is not permission, and the computer's operator can access the local
stores. Page details and relevant memories go to River during scoring; this
local GBrain demo does not use a cloud memory or embedding provider.

Sharing selected memories between friends comes after this demo. Friendship
alone never grants access. The current gate has no user accounts, so real users
will need sign-in and access checks before this becomes a shared service.

Implementation references: [GBrain setup](https://github.com/garrytan/gbrain),
[memory API](https://github.com/garrytan/gbrain/blob/master/docs/protocol/MEMORY_VERBS_v1.md),
[graph links](https://github.com/garrytan/gbrain/blob/master/src/core/ops/links.ts).
