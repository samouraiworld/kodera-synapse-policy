"""Keep a Kodera instance's rooms under the control plane's policy.

Kodera's control plane decides who is in which channel room and the tenant agent's
administrative account applies it (ADR-0018). Synapse's client API is open to any Matrix
client a member signs in with, so this module refuses what would route around that:

- room creation, except a direct message between two local users, and except by the agent;
- invites, except the one a member's direct message is created with, and except by the agent;
- invites by e-mail or phone (third-party identifiers) and room aliases, except by the agent;
- publishing any room to the directory;
- end-to-end encryption in any room;
- turning a room public: a join rule other than ``invite``, a world-readable history,
  aliases, server ACLs, room upgrades and space links, unless the agent sends them.

Posting in a read-only channel is not this module's: the agent sets the room's power levels.
"""

from __future__ import annotations

from typing import Any

from synapse.module_api import NOT_SPAM, ModuleApi
from synapse.module_api.errors import Codes, ConfigError

DM_PRESETS = frozenset({"private_chat", "trusted_private_chat"})
# State a member may never send, whatever its content.
LOCKED_STATE = frozenset(
    {
        "m.room.aliases",
        "m.room.canonical_alias",
        "m.room.server_acl",
        "m.room.third_party_invite",
        "m.room.tombstone",
        "m.space.child",
        "m.space.parent",
    }
)


class KoderaPolicy:
    def __init__(self, config: dict[str, Any], api: ModuleApi) -> None:
        self._agent = config["agent_user_id"]
        self._api = api
        api.register_spam_checker_callbacks(
            user_may_create_room=self.user_may_create_room,
            user_may_invite=self.user_may_invite,
            user_may_send_3pid_invite=self.user_may_send_3pid_invite,
            user_may_create_room_alias=self.user_may_create_room_alias,
            user_may_publish_room=self.user_may_publish_room,
            check_event_for_spam=self.check_event_for_spam,
        )

    @staticmethod
    def parse_config(config: dict[str, Any]) -> dict[str, Any]:
        agent = config.get("agent_user_id") if isinstance(config, dict) else None
        if not isinstance(agent, str) or not agent.startswith("@") or ":" not in agent:
            raise ConfigError("agent_user_id must be a full Matrix user ID, such as @agent:example.org")
        return {"agent_user_id": agent}

    async def user_may_create_room(
        self, user_id: str, room_config: dict[str, Any] | None = None
    ) -> Any:
        if user_id == self._agent:
            return NOT_SPAM
        # Synapse before 1.132 passes no room_config: nothing tells a direct message apart.
        if room_config is None or not self._is_direct_message(user_id, room_config):
            return Codes.FORBIDDEN
        return NOT_SPAM

    def _is_direct_message(self, creator: str, config: dict[str, Any]) -> bool:
        invite = config.get("invite")
        if config.get("is_direct") is not True or not isinstance(invite, list) or len(invite) != 1:
            return False
        invitee = invite[0]
        if not isinstance(invitee, str) or invitee == creator or not self._api.is_mine(invitee):
            return False
        creation = config.get("creation_content") or {}
        return (
            not config.get("invite_3pid")
            and not config.get("room_alias_name")
            and not config.get("initial_state")
            and not config.get("power_level_content_override")
            and config.get("visibility", "private") == "private"
            and config.get("preset", "trusted_private_chat") in DM_PRESETS
            and isinstance(creation, dict)
            and creation.get("type") is None
        )

    async def user_may_invite(self, inviter: str, invitee: str, room_id: str) -> Any:
        if inviter == self._agent:
            return NOT_SPAM
        # A member invites once: into the direct message they just created, where nobody else
        # has ever had a membership.
        state = await self._api.get_room_state(room_id)
        create = state.get(("m.room.create", ""))
        others = {key for (kind, key) in state if kind == "m.room.member"} - {inviter}
        if create is None or create.sender != inviter or others or not self._api.is_mine(invitee):
            return Codes.FORBIDDEN
        return NOT_SPAM

    async def user_may_send_3pid_invite(
        self, inviter: str, medium: str, address: str, room_id: str
    ) -> Any:
        return NOT_SPAM if inviter == self._agent else Codes.FORBIDDEN

    async def user_may_create_room_alias(self, user_id: str, room_alias: Any) -> Any:
        return NOT_SPAM if user_id == self._agent else Codes.FORBIDDEN

    async def user_may_publish_room(self, user_id: str, room_id: str) -> Any:
        return Codes.FORBIDDEN

    async def check_event_for_spam(self, event: Any) -> Any:
        if not event.is_state():
            return NOT_SPAM
        if event.type == "m.room.encryption":
            return Codes.FORBIDDEN
        if event.sender == self._agent:
            return NOT_SPAM
        content = event.content
        if (
            event.type in LOCKED_STATE
            or (event.type == "m.room.join_rules" and content.get("join_rule") != "invite")
            or (
                event.type == "m.room.history_visibility"
                and content.get("history_visibility") == "world_readable"
            )
        ):
            return Codes.FORBIDDEN
        return NOT_SPAM
