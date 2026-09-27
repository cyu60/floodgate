# Show the connection, not just the memory

“Everyone gets a second brain that remembers their people, projects, and
promises. Their agent follows those connections to understand what matters
right now. Floodgate uses that context to protect their attention.”

Open the memory demo at `http://127.0.0.1:8792`. It uses fictional profiles and
real GBrain storage. The screen shows evidence for an agent, not a generated
answer or a model score.

**1. Find someone who can unblock me — 30 seconds.**

Choose Alice and “Find the right person.” Her task is to ship the Atlas demo.
Follow **Atlas → teammate Bob → collaborator Maya → Quiet Harbor**. The guide
does not mention Atlas; the relationship path explains why it is useful.
Select Maya to see the saved sources behind her connections.

**2. Remember what I promised — 30 seconds.**

Choose “Keep a promise.” Follow **Friday handoff → promise to Bob → works without
a network → Pocket Vault**. A simple list of favorite websites misses the reason
this implementation guide matters today.

**3. The same page means something different to someone else — 20 seconds.**

Choose “Same page. Different person.” and switch between Alice and Bob. Bob is preparing the
Cedar pitch, so his brain returns presentation context. Alice's technical notes
stay in her own brain. Knowing someone is not permission to read their memories.

For the browser-gate portion, stop the memory demo server, then run the gate
with Alice's brain and the `models/floodgate-personal-v1.json` model card using
the [setup command](GBRAIN_INTEGRATION_PLAN.md). In the v0.2 extension, choose **Dashboard → Model →
River open Jev (gate server)**, set an Atlas task, and visit a relevant page.
Inspect `http://127.0.0.1:8790/memory` for the graph evidence available to the gate.
An override records a correction for that task and page. The graph provides
evidence; a lower River score is something to measure, not a guaranteed result.
The extension's own saved labels can also affect its next decision immediately;
that behavior is separate from retraining the River model.

Leave the browser's optional **GBrain memory** context provider off for this
walkthrough. The Python gate already reads Alice's local graph over stdio;
the browser provider connects separately to a hosted HTTP MCP workspace.

A relational database could represent these relationships with tables and joins.
Our demonstration is about following several connections, preserving the source
of each claim, and giving agents useful context as those connections change.
It is not a database speed comparison.

See [setup and commands](GBRAIN_INTEGRATION_PLAN.md). Friend-to-friend sharing
and real user sign-in are future work; this demo has two local sample identities.
