# 本轮界面淘汰

`src/myth/webui/images/paper-study.png` 与来源 sidecar：用户明确要求移除纸构图案，当前标志改为太极 SVG；HTML、静态白名单、包清单与浏览器采集均改用当前标志。原图仅作设计历史留档，不随发布包交付。

## 22:56 续跑的界面替换

- 九张 `docs/assets/atelier-*.png` / `ink-*.png` 旧画面：原太极界面已替换，保留为历史，不作为新画面的验证证据。
- `src/myth/webui/taiji.svg`、`ink-taiji.png` 与来源 JSON、旧 `favicon.svg`：替代入口为原创 `logo.svg`、亮/暗/单色和 16/32 px 版本。HTTP 白名单与打包资源同步；旧入口返回 404。
- 完整新状态截图矩阵尚未验收，交付报告明确记录，不复用旧图宣称新界面已经通过视觉验收。
