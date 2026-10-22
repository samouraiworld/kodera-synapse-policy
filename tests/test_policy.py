import asyncio
from types import SimpleNamespace

import pytest

from kodera_synapse_policy import KoderaPolicy

SERVER = "acme-sa.kodera.io"
AGENT = f"@kodera-agent:{SERVER}"
ALICE = f"@alice:{SERVER}"
BOB = f"@bob:{SERVER}"
CAROL = f"@carol:{SERVER}"
OUTSIDER = "@eve:elsewhere.example"
FORBIDDEN = "M_FORBIDDEN"
ALLOWED = "NOT_SPAM"


class FakeApi:
    def __init__(self, rooms=None):
        self.callbacks = {}
        self.rooms = rooms or {}

    def register_spam_checker_callbacks(self, **callbacks):
        self.callbacks.update(callbacks)

    def is_mine(self, user_id):
        return user_id.endswith(f":{SERVER}")

    async def get_room_state(self, room_id):
        return self.rooms.get(room_id, {})


def run(coro):
    return asyncio.run(coro)


def policy(rooms=None):
    return KoderaPolicy({"agent_user_id": AGENT}, FakeApi(rooms))


def dm_request(**overrides):
    request = {"is_direct": True, "invite": [BOB], "preset": "trusted_private_chat"}
    request.update(overrides)
    return request


def event(kind, sender=ALICE, state=True, **content):
    return SimpleNamespace(type=kind, sender=sender, content=content, is_state=lambda: state)


def state_of(creator, members):
    state = {("m.room.create", ""): SimpleNamespace(sender=creator)}
    for member in members:
        state[("m.room.member", member)] = SimpleNamespace(sender=member)
    return state


def test_registers_every_callback_it_relies_on():
    api = FakeApi()
    KoderaPolicy({"agent_user_id": AGENT}, api)
    assert set(api.callbacks) == {
        "user_may_create_room",
        "user_may_invite",
        "user_may_publish_room",
        "check_event_for_spam",
    }


@pytest.mark.parametrize("config", [{}, {"agent_user_id": "agent"}, {"agent_user_id": 3}, None])
def test_refuses_a_config_without_a_full_agent_id(config):
    with pytest.raises(Exception, match="agent_user_id"):
        KoderaPolicy.parse_config(config)


def test_agent_creates_any_room():
    assert run(policy().user_may_create_room(AGENT, {"preset": "public_chat"})) == ALLOWED


def test_member_creates_a_direct_message():
    assert run(policy().user_may_create_room(ALICE, dm_request())) == ALLOWED


@pytest.mark.parametrize(
    "request_body",
    [
        None,
        {"preset": "private_chat"},
        dm_request(is_direct=False),
        dm_request(invite=[BOB, CAROL]),
        dm_request(invite=[]),
        dm_request(invite=[ALICE]),
        dm_request(invite=[OUTSIDER]),
        dm_request(invite_3pid=[{"medium": "email", "address": "x@example.org"}]),
        dm_request(room_alias_name="general"),
        dm_request(visibility="public"),
        dm_request(preset="public_chat"),
        dm_request(initial_state=[{"type": "m.room.encryption", "content": {}}]),
        dm_request(power_level_content_override={"invite": 0}),
        dm_request(creation_content={"type": "m.space"}),
    ],
)
def test_member_cannot_create_anything_but_a_direct_message(request_body):
    assert run(policy().user_may_create_room(ALICE, request_body)) == FORBIDDEN


def test_member_invites_once_into_their_new_direct_message():
    rooms = {"!dm": state_of(ALICE, [ALICE])}
    assert run(policy(rooms).user_may_invite(ALICE, BOB, "!dm")) == ALLOWED


@pytest.mark.parametrize(
    ("room", "invitee"),
    [
        (state_of(ALICE, [ALICE, BOB]), CAROL),
        (state_of(AGENT, [AGENT, ALICE]), BOB),
        (state_of(BOB, [BOB]), CAROL),
        (state_of(BOB, [ALICE]), CAROL),
        (state_of(AGENT, [ALICE]), BOB),
        (state_of(ALICE, [ALICE]), OUTSIDER),
        ({}, BOB),
    ],
    ids=[
        "second-invite",
        "agent-channel",
        "someone-elses-room",
        "left-by-its-creator",
        "agent-channel-left-to-one-member",
        "outsider",
        "unknown-room",
    ],
)
def test_member_cannot_invite_otherwise(room, invitee):
    assert run(policy({"!r": room}).user_may_invite(ALICE, invitee, "!r")) == FORBIDDEN


def test_agent_invites_into_any_room():
    assert run(policy().user_may_invite(AGENT, BOB, "!channel")) == ALLOWED


@pytest.mark.parametrize("user", [ALICE, AGENT])
def test_nobody_publishes_to_the_directory(user):
    assert run(policy().user_may_publish_room(user, "!r")) == FORBIDDEN


@pytest.mark.parametrize("sender", [ALICE, AGENT])
def test_nobody_turns_on_encryption(sender):
    assert run(policy().check_event_for_spam(event("m.room.encryption", sender))) == FORBIDDEN


@pytest.mark.parametrize(
    "refused",
    [
        event("m.room.join_rules", join_rule="public"),
        event("m.room.join_rules", join_rule="knock"),
        event("m.room.join_rules", join_rule="restricted"),
        event("m.room.history_visibility", history_visibility="world_readable"),
        event("m.room.canonical_alias", alias="#general:acme-sa.kodera.io"),
        event("m.room.aliases"),
        event("m.room.server_acl", allow=["*"]),
        event("m.room.tombstone", replacement_room="!new"),
        event("m.space.child"),
        event("m.space.parent"),
    ],
    ids=lambda e: f"{e.type}:{e.content}",
)
def test_member_cannot_open_a_room(refused):
    assert run(policy().check_event_for_spam(refused)) == FORBIDDEN


@pytest.mark.parametrize(
    "allowed",
    [
        event("m.room.message", state=False, body="hello"),
        event("m.reaction", state=False),
        event("m.room.join_rules", join_rule="invite"),
        event("m.room.history_visibility", history_visibility="shared"),
        event("m.room.name", name="Lunch"),
        event("m.room.power_levels", users={ALICE: 100}),
        event("io.kodera.room.occupancy", sender=AGENT),
        event("m.room.join_rules", sender=AGENT, join_rule="public"),
    ],
    ids=lambda e: f"{e.type}:{e.sender}",
)
def test_ordinary_events_pass(allowed):
    assert run(policy().check_event_for_spam(allowed)) == ALLOWED
