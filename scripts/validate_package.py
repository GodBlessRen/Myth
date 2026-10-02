"""Check an installed wheel, its HTTP assets and schedule API in an isolated root.

Usage: python scripts/validate_package.py --package-dir .runtime/wheel-installed
No model call, OAuth login or source-file execution is performed.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib import request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--package-dir",type=Path,required=True)
    args=parser.parse_args()
    package_dir=args.package_dir.resolve()
    sys.path.insert(0,str(package_dir))
    import myth
    from myth.web import AgentWebService,make_handler
    from myth.runtime import MythRuntime
    from myth.workspace import Workspace
    if not Path(myth.__file__).resolve().is_relative_to(package_dir):
        raise RuntimeError("import did not use the installed package")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        with MythRuntime(root) as runtime:
            Workspace(runtime).repository.save_settings({"provider":"ollama","model":"package-check"})
        service=AgentWebService(root)
        server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(service))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f"http://127.0.0.1:{server.server_port}"
        def call(path,value=None):
            body=json.dumps(value).encode() if value is not None else None
            with request.urlopen(request.Request(base+path,data=body,headers={"Content-Type":"application/json"}),timeout=5) as response:
                return json.load(response)
        try:
            for asset in ("/","/app.css","/app.js","/inspector.js","/goals.js"):
                with request.urlopen(base+asset,timeout=5) as response:
                    if response.status!=200 or not response.read():raise RuntimeError(f"missing packaged asset: {asset}")
            session=call("/api/workspace/sessions",{"title":"Installed package check"})
            goal=call("/api/workspace/goals",{"title":"Installed Goal"})
            schedule=call(f"/api/workspace/goals/{goal['goal_id']}/schedules",{
                "request_id":"package-smoke","session_id":session["id"],"prompt":"Future work",
                "due_at":"2030-01-01T00:00:00Z",
            })
            paused=call(f"/api/workspace/schedules/{schedule['schedule_id']}/enabled",{"enabled":False})
            if paused["enabled"]:raise RuntimeError("timer was not paused")
            if len(call("/api/workspace/schedules")["schedules"])!=1:raise RuntimeError("schedule was not persisted")
            print(json.dumps({"status":"PASS","version":myth.__version__,"import_path":str(myth.__file__),
                              "checks":["installed import","HTTP assets","Goal/session","schedule persistence/pause"]},indent=2))
        finally:
            service.workspace.stop_scheduler()
            server.shutdown();server.server_close();thread.join(3)


if __name__=="__main__":main()
