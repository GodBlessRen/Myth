from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib import request, error

from myth.runtime import MythRuntime
from myth.web import AgentWebService, make_handler
from myth.workspace import Workspace
from test_workspace import ChatProvider


class ScheduleWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.service=AgentWebService(self.root)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(self.service))
        self.base=f"http://127.0.0.1:{self.server.server_port}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        with MythRuntime(self.root) as runtime:
            w=Workspace(runtime);w.repository.save_settings({"provider":"ollama","model":"test"})
            self.sid=w.repository.create_session()["id"]
            self.goal=w.personal.create_goal("HTTP wakeup")
        self.provider=ChatProvider()
        self.service.workspace.connection=lambda settings:{"ready":True,"details":{"models":["test"]}}
        self.service.workspace.provider=lambda settings:self.provider

    def tearDown(self):
        self.service.workspace.stop_scheduler()
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        deadline=time.monotonic()+5
        while self.service.workspace.active and time.monotonic()<deadline:time.sleep(.01)
        self.tmp.cleanup()

    def call(self,path,payload=None,headers=None):
        body=json.dumps(payload).encode() if payload is not None else None
        with request.urlopen(request.Request(self.base+path,data=body,headers={"Content-Type":"application/json",**(headers or {})}),timeout=5) as response:
            return json.load(response)

    def test_schedule_post_retry_and_background_completion_are_visible(self):
        value={"request_id":"http-timer","session_id":self.sid,"prompt":"Useful scheduled work",
               "due_at":datetime.now(timezone.utc).isoformat()}
        path=f"/api/workspace/goals/{self.goal['goal_id']}/schedules"
        schedule=self.call(path,value)
        self.assertEqual(self.call(path,value)["schedule_id"],schedule["schedule_id"])
        self.service.workspace.start_scheduler()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            item=self.call("/api/workspace/schedules")["schedules"][0]
            if item["wakeups"] and item["wakeups"][0]["status"]=="COMPLETED":break
            time.sleep(.03)
        self.assertEqual(item["wakeups"][0]["status"],"COMPLETED")
        self.assertFalse(item["enabled"])
        session=self.call(f"/api/workspace/sessions/{self.sid}")
        turn=session["turns"][0]
        self.assertEqual(turn["snapshot"]["goal"]["goal_id"],self.goal["goal_id"])
        self.assertIn("GoalWakeupAdmitted",[e["kind"] for e in turn["events"]])
        self.assertEqual(len(self.provider.calls),1)

    def test_pause_schedule_and_goal_endpoints(self):
        value={"session_id":self.sid,"prompt":"later work","due_at":"2030-01-01T00:00:00Z"}
        schedule=self.call(f"/api/workspace/goals/{self.goal['goal_id']}/schedules",value)
        paused=self.call(f"/api/workspace/schedules/{schedule['schedule_id']}/enabled",{"enabled":False})
        self.assertFalse(paused["enabled"])
        goal=self.call(f"/api/workspace/goals/{self.goal['goal_id']}/state",{"state":"PAUSED"})
        self.assertEqual(goal["state"],"PAUSED")
        self.assertEqual(len(self.call(f"/api/workspace/goals/{goal['goal_id']}/schedules")["schedules"]),1)

    def test_cross_origin_cannot_create_schedule_and_goals_asset_is_served(self):
        with self.assertRaises(error.HTTPError) as caught:
            self.call(f"/api/workspace/goals/{self.goal['goal_id']}/schedules",
                      {"session_id":self.sid,"prompt":"work","due_at":"2030-01-01T00:00:00Z"},
                      {"Origin":"https://untrusted.example"})
        self.assertIn(caught.exception.code,(400,403))
        self.assertEqual(self.call("/api/workspace/schedules")["schedules"],[])
        with request.urlopen(self.base+"/goals.js",timeout=5) as response:
            self.assertIn("javascript",response.headers["Content-Type"])
            self.assertIn(b"renderGoals",response.read())
        html=(Path(__file__).resolve().parents[1]/"src/myth/webui/index.html").read_text(encoding="utf-8")
        for identity in ("inspectorToggle","inspectorClose","goalsPage","scheduleDialog"):
            self.assertIn(identity,html)


if __name__=="__main__":unittest.main()
