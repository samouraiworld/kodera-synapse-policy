"""Prove the tests can fail: each mutation of the policy must be caught by its named test.

Run: python3 tests/mutate.py   (exit 0 only when every mutant is killed by the expected test)
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "kodera_synapse_policy" / "__init__.py"

# (description, original text, mutated text, test that must fail)
MUTANTS = [
    ("agent may not create", "if user_id == self._agent:\n            return NOT_SPAM", "if False:\n            return NOT_SPAM", "test_agent_creates_any_room"),
    ("any is_direct accepted", 'config.get("is_direct") is not True', "False", "test_member_cannot_create_anything_but_a_direct_message"),
    ("two invitees accepted", "len(invite) != 1", "len(invite) < 1", "test_member_cannot_create_anything_but_a_direct_message"),
    ("remote invitee accepted", "or not self._api.is_mine(invitee):\n            return False", ":\n            return False", "test_member_cannot_create_anything_but_a_direct_message"),
    ("initial state accepted", "and not config.get(\"initial_state\")", "", "test_member_cannot_create_anything_but_a_direct_message"),
    ("spaces accepted", 'and creation.get("type") is None', "", "test_member_cannot_create_anything_but_a_direct_message"),
    ("second invite accepted", "or others or", "or", "test_member_cannot_invite_otherwise"),
    ("other's room accepted", "create.sender != inviter or", "", "test_member_cannot_invite_otherwise"),
    ("directory open", "async def user_may_publish_room(self, user_id: str, room_id: str) -> Any:\n        return Codes.FORBIDDEN", "async def user_may_publish_room(self, user_id: str, room_id: str) -> Any:\n        return NOT_SPAM", "test_nobody_publishes_to_the_directory"),
    ("agent may encrypt", 'if event.type == "m.room.encryption":\n            return Codes.FORBIDDEN\n        if event.sender == self._agent:\n            return NOT_SPAM', 'if event.sender == self._agent:\n            return NOT_SPAM\n        if event.type == "m.room.encryption":\n            return Codes.FORBIDDEN', "test_nobody_turns_on_encryption"),
    ("join rule open", 'content.get("join_rule") != "invite"', "False", "test_member_cannot_open_a_room"),
    ("world readable open", '== "world_readable"', '== "never"', "test_member_cannot_open_a_room"),
    ("aliases open", "event.type in LOCKED_STATE\n            or", "", "test_member_cannot_open_a_room"),
    ("agent locked out", "if event.sender == self._agent:\n            return NOT_SPAM\n        content", "content", "test_ordinary_events_pass"),
]


def main() -> int:
    original = SOURCE.read_text()
    survivors = []
    for name, before, after, owner in MUTANTS:
        if original.count(before) != 1:
            print(f"BROKEN MUTANT {name!r}: its text occurs {original.count(before)} times")
            return 2
        with tempfile.TemporaryDirectory() as tmp:
            package = pathlib.Path(tmp) / "src" / "kodera_synapse_policy"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(original.replace(before, after))
            shutil.copytree(ROOT / "tests", pathlib.Path(tmp) / "tests")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_policy.py"],
                cwd=tmp,
                env={"PYTHONPATH": str(pathlib.Path(tmp) / "src"), "PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
            )
        failed = [line for line in result.stdout.splitlines() if line.startswith("FAILED")]
        caught = result.returncode == 1 and any(f"::{owner}" in line for line in failed)
        print(f"{'killed ' if caught else 'SURVIVED'} {name} (expected {owner})")
        if not caught:
            survivors.append(name)
    print(f"{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} mutants killed by their named test")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
