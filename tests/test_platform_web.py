"""Architecture surface tests: product API exposes the same honest component map."""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


class PlatformWebTests(unittest.TestCase):
    def test_workspace_and_web_expose_same_composable_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with MythRuntime(root) as runtime:
                direct=Workspace(runtime).components.snapshot()
            web=ConversationWebService(root).platform()

            self.assertEqual(web["version"],direct["version"])
            self.assertEqual(web["shape"],"core-domains-strategies-adapters")
            self.assertEqual(web["executable_capabilities"],direct["executable_capabilities"])

            domains={item["id"]:item["maturity"] for item in web["domains"]}
            self.assertEqual(domains["control"],"usable")
            self.assertEqual(domains["personal"],"connected")
            adapters={item["id"]:item["maturity"] for item in web["adapters"]}
            self.assertEqual(adapters["a2a"],"planned")
            self.assertNotIn("shell.exec",web["executable_capabilities"])


if __name__ == "__main__":
    unittest.main()
