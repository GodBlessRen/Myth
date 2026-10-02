"""真实本地 HTTP 合同：入口去重、交付下载、跨站拒绝和完成前禁止下载。"""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib import error, request
from myth.agent_runtime import AgentRuntime
from myth.providers.scripted import ScriptedPatchProvider
from myth.runtime import MythRuntime
from myth.web import AgentWebService, make_handler


class WebContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.service=AgentWebService(self.root)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(self.service))
        self.url=f"http://127.0.0.1:{self.server.server_port}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        deadline=time.monotonic()+5
        while self.service._active and time.monotonic()<deadline:threading.Event().wait(.01)
        self.tmp.cleanup()

    def call(self,path,payload=None,headers=None):
        body=json.dumps(payload).encode() if payload is not None else None
        return request.urlopen(request.Request(self.url+path,data=body,headers={"Content-Type":"application/json",**(headers or {})}),timeout=5)

    def settled(self,rid):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status=self.service.status(rid)
            if not status["driver_active"]:return status
            threading.Event().wait(.01)
        self.fail("local worker did not finish")

    def test_http_demo_downloads_exact_verified_bytes(self):
        with self.call("/api/demo",{}) as response:rid=json.load(response)["run_id"]
        status=self.settled(rid)
        self.assertEqual(status["agent"]["status"],"SUCCEEDED")
        with self.call(f"/api/runs/{rid}/artifacts/0") as response:
            data=response.read()
            self.assertIn("attachment",response.headers["Content-Disposition"])
        source=Path(status["acceptance"]["files"][0]["path"])
        self.assertEqual(data,source.read_bytes().replace(b"foo",b"bar"))
        self.assertIn(b"\r\n",data)
        # 下载来自验收固定的不可变对象，受管展示副本后来变化也不会污染交付。
        (self.root/".runtime"/"workspaces"/rid/source.name).write_text("tampered")
        with self.call(f"/api/runs/{rid}/artifacts/0") as response:self.assertEqual(response.read(),data)

    def test_same_request_returns_same_run_and_does_not_restart(self):
        source=self.root/"data.txt";source.write_text("foo")
        payload={"request_id":"same","goal":"replace","provider":"scripted","model":"test","files":[str(source)],
                 "acceptance":[{"path":str(source),"old_text":"foo","new_text":"bar","expected_count":1}]}
        with self.call("/api/runs",payload) as response:rid=json.load(response)["run_id"]
        self.settled(rid)
        with self.call("/api/runs",payload) as response:self.assertEqual(json.load(response)["run_id"],rid)
        self.assertEqual(len(self.service.list_runs()),1)
        self.assertEqual(len(self.service.status(rid)["model"]["model_invocations"]),3)

    def test_cross_origin_and_rebound_host_are_rejected(self):
        for path,payload,headers in [("/api/demo",{}, {"Origin":"https://evil.invalid"}),
                                     ("/api/demo",{}, {"Content-Type":"text/plain"}),
                                     ("/api/runs",None,{"Host":f"evil.invalid:{self.server.server_port}"})]:
            with self.assertRaises(error.HTTPError) as raised:self.call(path,payload,headers)
            self.assertIn(raised.exception.code,(400,403))
        self.assertEqual(self.service.list_runs(),[])

    def test_no_download_before_pass(self):
        source=self.root/"data.txt";source.write_text("foo")
        with MythRuntime(self.root) as runtime:
            rid=AgentRuntime(runtime).create_run(goal="replace",provider=ScriptedPatchProvider(),model="test",allowed_files=(source,))
        with self.assertRaises(error.HTTPError) as raised:self.call(f"/api/runs/{rid}/artifacts/0")
        self.assertEqual(raised.exception.code,403)

    def test_invalid_step_limit_is_rejected_before_creating_run(self):
        source=self.root/"data.txt";source.write_text("foo")
        with self.assertRaises(error.HTTPError) as raised:
            self.call("/api/runs",{"goal":"replace","provider":"scripted","model":"test","files":[str(source)],"max_steps":0})
        self.assertEqual(raised.exception.code,400)
        self.assertEqual(self.service.list_runs(),[])
