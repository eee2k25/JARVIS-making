"""Unit tests: state machine contract + offline brain planning."""

from __future__ import annotations

import unittest

from jarvis.config import Settings
from jarvis.exceptions import InvalidTransitionError
from jarvis.state_machine import AgentState as S
from jarvis.state_machine import StateMachine


class TestStateMachine(unittest.TestCase):
    def test_happy_path_lifecycle(self):
        sm = StateMachine()
        sm.new_run()
        sm.transition(S.BOOTING)
        sm.transition(S.IDLE)
        sm.transition(S.PERCEIVING)
        sm.transition(S.REASONING)
        sm.transition(S.ACTING)
        sm.transition(S.VERIFYING)
        sm.transition(S.IDLE)
        sm.transition(S.SHUTTING_DOWN)
        sm.transition(S.TERMINATED)
        self.assertTrue(sm.terminal)
        self.assertEqual(len(sm.history), 9)

    def test_illegal_transition_rejected(self):
        sm = StateMachine()
        with self.assertRaises(InvalidTransitionError):
            sm.transition(S.ACTING)  # OFF -> ACTING is illegal
        self.assertIs(sm.state, S.OFF)  # state unchanged

    def test_error_recovery_loop(self):
        sm = StateMachine()
        sm.transition(S.BOOTING)
        sm.transition(S.IDLE)
        sm.transition(S.PERCEIVING)
        sm.transition(S.ERROR)
        sm.transition(S.RECOVERING)
        sm.transition(S.PERCEIVING)  # retry re-enters perception
        self.assertIs(sm.state, S.PERCEIVING)

    def test_terminated_is_absorbing(self):
        sm = StateMachine()
        sm.transition(S.BOOTING)
        sm.transition(S.SHUTTING_DOWN)
        sm.transition(S.TERMINATED)
        with self.assertRaises(InvalidTransitionError):
            sm.transition(S.IDLE)

    def test_listeners_fire_and_survive_exceptions(self):
        sm = StateMachine()
        seen = []

        def boom(t):
            raise RuntimeError("listener bug must not break the machine")

        sm.add_listener(seen.append)
        sm.add_listener(boom)
        sm.transition(S.BOOTING, note="with listeners")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].note, "with listeners")

    def test_backoff_grows(self):
        self.assertLessEqual(StateMachine.backoff(0, jitter=False),
                             StateMachine.backoff(3, jitter=False) / 4)


class TestOfflineBrain(unittest.TestCase):
    def test_plan_is_valid_and_minimal(self):
        from jarvis.cognition.llm import OfflineBrain

        brain = OfflineBrain()
        plan = brain.decide(
            {"url": "http://fixture.local/", "stats": {"links": 4, "forms": 1},
             "forms": [{"method": "get", "fields": []}]},
            mission="recon the control panel",
        )
        self.assertTrue(plan.actions)
        for action in plan.actions:
            action.validate()  # must not raise
        self.assertEqual(plan.brain, "offline-heuristic")

    def test_settings_defaults_safe(self):
        s = Settings.load()
        self.assertGreaterEqual(s.max_retries, 0)
        self.assertGreater(s.http_timeout, 0)


if __name__ == "__main__":
    unittest.main()
