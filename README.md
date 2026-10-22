# kodera-synapse-policy

Status: published under AGPL-3.0-or-later (owner authorised publication on 2026-10-22). Changes land by pull request.

A Synapse module that keeps a Kodera instance's rooms under its control plane's policy (Core ADR-0018).

**The model.** Kodera's control plane decides who is in which channel room, and the tenant agent's administrative account applies it. Synapse's client API is open to any Matrix client a member signs in with, so this module refuses whatever would route around that:

| Callback | Refuses |
|---|---|
| `user_may_create_room` | every room creation, except a direct message between two local users, and except by the agent |
| `user_may_invite` | every invite, except the one a member's new direct message is created with, and except by the agent |
| `user_may_send_3pid_invite`, `user_may_create_room_alias` | invites by e-mail or phone, and room aliases, except by the agent |
| `user_may_publish_room` | publishing any room to the directory |
| `check_event_for_spam` | `m.room.encryption` from anyone. From anyone but the agent: a join rule other than `invite`, a world-readable history, aliases, third-party invites, server ACLs, room upgrades and space links |

**Read-only channels are not this module's job.** Posting is governed by the room's power levels, which the agent sets.

## Configure

Synapse 1.132 or later is required: earlier versions pass no room configuration, so a direct message cannot be told apart and every member-created room is refused.

```yaml
modules:
  - module: kodera_synapse_policy.KoderaPolicy
    config:
      agent_user_id: "@kodera-agent:acme-sa.kodera.io"
```

## Test

```bash
PYTHONPATH=src python3 -m pytest -q
```

```bash
python3 tests/mutate.py
```

```bash
bash tests/integration/run.sh
```

```bash
WITHOUT_MODULE=1 bash tests/integration/run.sh
```

- **Unit tests.** They run the callbacks against a minimal stand-in for Synapse's module API (`tests/conftest.py`).
- **Mutation script.** It proves every rule has a test that fails when the rule is broken, and names the test that must catch it.
- **Integration test.** It runs the module inside the pinned Synapse v1.163.0 in Docker, and drives it over the client API as a third-party client would. This covers the invite inside `/createRoom`, the state a direct-message preset creates, refused e-mail invites and aliases, and the agent's own channel.
- **Negative control.** Run without the module, the same scenario must fail (11 checks fail, exit 1).

## Continuous integration

`ci-ok` is the one required check. It passes only when every job passes:
- **Unit tests and mutations**, with the test dependencies pinned by hash (`requirements-test.txt`).
- **The real-Synapse test**, with the image pinned by digest. The negative control runs first and must fail.
- **The attribution check** on files, commit messages, the branch name, and the pull request title and body. Each check first proves it can fail.

## Licence

AGPL-3.0-or-later, like Synapse ([LICENSE](LICENSE)).
