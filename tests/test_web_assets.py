"""静态资源用真实 HTTP 和包内字节验证，不以存在文件代替路由可达。"""
from http.server import ThreadingHTTPServer
from pathlib import PurePosixPath
import re
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from myth.web import ASSET_DIR, make_handler
from myth.web_assets import PUBLIC_ASSETS


class WebAssetTests(unittest.TestCase):
    """静态端点不需要业务服务；None 代表此处不可偷偷创建 Run。"""

    def setUp(self):
        """每例占用独立 loopback 端口，不启动模型或调度。"""
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(None))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        """关闭监听与线程，不留影响后续用例的端口。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_every_declared_asset_serves_exact_packaged_bytes(self):
        """新 Logo 与其他所有声明资源一样必须端到端可达。"""
        for logo in ('/logo.svg', '/logo-dark.svg', '/logo-mono.svg', '/logo-16.svg', '/logo-32.svg', '/favicon.svg'):
            self.assertIn(logo, PUBLIC_ASSETS)
        for url, (filename, content_type) in PUBLIC_ASSETS.items():
            with self.subTest(url=url):
                with urlopen(self.base + url, timeout=3) as response:
                    body = response.read()
                    self.assertEqual(body, (ASSET_DIR / filename).read_bytes())
                    self.assertTrue(body)
                    self.assertEqual(response.headers['Content-Type'], content_type)
                    self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_html_asset_references_are_closed_and_packaged(self):
        """HTML 不能引用漏入清单的本地文件，也不能借 CDN 掩盖离线缺口。"""
        html = (ASSET_DIR / 'index.html').read_text(encoding='utf-8')
        for tag in re.findall(r'<(?:script|link|img)\b[^>]*>', html):
            for attribute, value in re.findall(r'\b(src|href)="([^"]+)"', tag):
                self.assertIn(value, PUBLIC_ASSETS, (attribute, value))
        for filename, _ in PUBLIC_ASSETS.values():
            self.assertFalse(PurePosixPath(filename).is_absolute())
            self.assertNotIn('..', PurePosixPath(filename).parts)
            self.assertTrue((ASSET_DIR / filename).is_file())
        with self.assertRaises(TypeError):
            PUBLIC_ASSETS['/private'] = ('secret', 'text/plain')

    def test_unknown_traversal_and_license_paths_are_not_public(self):
        """端点仍为封闭白名单，不变成字体或项目文件的通用服务器。"""
        for url in ('/logo.svg/extra', '/myth-mark.svg', '/ink-taiji.png', '/taiji.svg', '/web.py', '/fonts/unknown.woff2',
                    '/fonts/%2e%2e/web.py', '/%2e%2e/web.py', '/fonts/OFL-NotoSansSC.txt'):
            with self.subTest(url=url), self.assertRaises(HTTPError) as error:
                urlopen(self.base + url, timeout=3)
            self.assertEqual(error.exception.code, 404)

    def test_asset_dispatch_preserves_same_origin_checks(self):
        """登记 Logo 不能放宽 Host/Origin 入站合同。"""
        req = Request(self.base + '/logo.svg', headers={'Origin': 'https://untrusted.invalid'})
        with self.assertRaises(HTTPError) as error:
            urlopen(req, timeout=3)
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
