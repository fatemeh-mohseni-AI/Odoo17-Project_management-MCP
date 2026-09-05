from __future__ import annotations

import asyncio
import unittest

from mcp import Client

from odoo_project_mcp.server import mcp


class ServerContractTests(unittest.TestCase):
    def test_tools_are_listed_with_safe_annotations_and_schemas(self) -> None:
        async def inspect() -> None:
            async with Client(mcp) as client:
                page = await client.list_tools()
                tools = {tool.name: tool for tool in page.tools}

                self.assertEqual(len(tools), 32)
                self.assertIn("get_project_board", tools)
                self.assertIn("create_subtask", tools)
                self.assertIn("create_timesheet", tools)
                self.assertNotIn("execute_kw", tools)

                self.assertTrue(tools["list_tasks"].annotations.read_only_hint)
                self.assertFalse(tools["create_task"].annotations.destructive_hint)
                self.assertTrue(tools["delete_task"].annotations.destructive_hint)
                self.assertTrue(tools["delete_timesheet"].annotations.destructive_hint)

                create_schema = tools["create_task"].input_schema
                self.assertEqual(set(create_schema["required"]), {"project_id", "name"})
                delete_schema = tools["delete_task"].input_schema
                self.assertEqual(set(delete_schema["required"]), {"task_id", "confirmation"})
                list_schema = tools["list_tasks"].input_schema
                self.assertIn("stage_name", list_schema["properties"])
                self.assertEqual(list_schema["properties"]["limit"]["default"], 25)

        asyncio.run(inspect())


if __name__ == "__main__":
    unittest.main()
