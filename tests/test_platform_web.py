"""Platform surface tests: product API must expose the same honest Kernel map."""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


class PlatformWebTests(unittest.TestCase):
    def test_workspace_and_web_expose_same_platform_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with MythRuntime(root) as runtime:
                direct=Workspace(runtime).kernel.snapshot()
            web=ConversationWebService(root).platform()
            self.assertEqual(web["version"],direct["version"])
            self.assertEqual(web["executable_capabilities"],direct["executable_capabilities"])
            states={layer["id"]:layer["state"] for layer in web["layers"]}
            self.assertEqual(states["runtime"],"usable")
            self.assertEqual(states["control"],"wired")
            self.assertEqual(states["distributed"],"planned")
            self.assertNotIn("shell.exec",web["executable_capabilities"])


if __name__ == "__main__":
    unittest.main()
