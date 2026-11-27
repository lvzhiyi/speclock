"""静态核对需求澄清技能与相关工作流入口的约定。"""
from pathlib import Path
import unittest

SKILLS = Path(__file__).resolve().parents[2] / "skills"


class ClarifySkillContractTests(unittest.TestCase):
    def test_clarify_skill_contains_grill_me_and_gate_clauses(self):
        skill_path = SKILLS / "clarify" / "SKILL.md"
        self.assertTrue(skill_path.is_file())
        text = skill_path.read_text(encoding="utf-8")
        self.assertIn("name: clarify", text)
        for clause in (
            "先查事实",
            "决策树",
            "推荐答案",
            "workflow-confirm:",
            "--operation clarify",
            "check_docs.py",
            "待确认",
            "待处理",
            "close",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, text)

    def test_workflow_kickoff_and_breakdown_reference_clarify(self):
        for name in ("workflow", "kickoff", "prd-breakdown"):
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn("clarify", text)


if __name__ == "__main__":
    unittest.main()
