from __future__ import annotations

import unittest
from unittest import mock

from packages.infrastructure.task_complexity import COMPLEXITY_MODELS
from packages.infrastructure.task_complexity import TaskComplexity
from packages.infrastructure.task_complexity import model_for_complexity
from packages.infrastructure.task_complexity import resolve_task_model


class TaskComplexityTests(unittest.TestCase):
    def test_each_level_maps_to_its_model(self) -> None:
        self.assertEqual(model_for_complexity(TaskComplexity.IMPORTANT), "gpt-5.5")
        self.assertEqual(model_for_complexity(TaskComplexity.MEDIUM), "gpt-5.4-mini")
        self.assertEqual(model_for_complexity(TaskComplexity.SMALL), "gpt-5.4-nano")

    def test_every_level_has_a_model(self) -> None:
        for level in TaskComplexity:
            self.assertIn(level, COMPLEXITY_MODELS)
            self.assertTrue(COMPLEXITY_MODELS[level])

    def test_level_accepts_its_string_value(self) -> None:
        self.assertEqual(model_for_complexity("medium"), "gpt-5.4-mini")

    def test_unreadable_level_falls_back_to_the_strongest_model(self) -> None:
        self.assertEqual(model_for_complexity("nonsense"), "gpt-5.5")
        self.assertEqual(model_for_complexity(None), "gpt-5.5")

    def test_environment_override_wins_over_the_level(self) -> None:
        with mock.patch.dict("os.environ", {"TASK_MODEL": "gpt-5.4"}, clear=False):
            self.assertEqual(
                resolve_task_model(TaskComplexity.SMALL, "TASK_MODEL"),
                "gpt-5.4",
            )

    def test_first_set_override_wins(self) -> None:
        env = {"SECOND_CHOICE": "gpt-5.4"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                resolve_task_model(TaskComplexity.SMALL, "FIRST_CHOICE", "SECOND_CHOICE"),
                "gpt-5.4",
            )

    def test_blank_override_is_ignored(self) -> None:
        with mock.patch.dict("os.environ", {"TASK_MODEL": "   "}, clear=False):
            self.assertEqual(
                resolve_task_model(TaskComplexity.MEDIUM, "TASK_MODEL"),
                "gpt-5.4-mini",
            )

    def test_level_falls_back_when_no_override_is_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                resolve_task_model(TaskComplexity.MEDIUM, "TASK_MODEL"),
                "gpt-5.4-mini",
            )


class DeclaredTaskComplexityTests(unittest.TestCase):
    """Every task that calls an LLM must declare how demanding it is."""

    def test_all_llm_tasks_declare_a_complexity(self) -> None:
        from packages.infrastructure import whatsapp_reengagement
        from packages.infrastructure.portal_auth import server
        from packages.tools.scheduled_monitor import monitor

        declared = {
            "scheduled monitor": monitor.MONITOR_COMPLEXITY,
            "whatsapp re-engagement": whatsapp_reengagement.REENGAGEMENT_COMPLEXITY,
            "contact intake agent": server.CONTACT_AGENT_COMPLEXITY,
            "agent proposal revision": server.AGENT_PROPOSAL_REVISION_COMPLEXITY,
            "conversational portal agent": server.AGENT_TURN_COMPLEXITY,
        }
        for task_name, level in declared.items():
            with self.subTest(task=task_name):
                self.assertIsInstance(level, TaskComplexity)

    def test_tool_defaults_match_their_declared_complexity(self) -> None:
        from packages.infrastructure import whatsapp_reengagement
        from packages.tools.scheduled_monitor import monitor

        self.assertEqual(
            monitor.DEFAULT_MONITOR_MODEL,
            model_for_complexity(monitor.MONITOR_COMPLEXITY),
        )
        self.assertEqual(
            whatsapp_reengagement.DEFAULT_REENGAGEMENT_MODEL,
            model_for_complexity(whatsapp_reengagement.REENGAGEMENT_COMPLEXITY),
        )


if __name__ == "__main__":
    unittest.main()
