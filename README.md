# FlashPanel

可复用的 iOS 悬浮 HUD 框架。原生窗壳负责拖拽、吸附、折叠、穿透；内容层是一个 `WKWebView`，改 UI 只需改 HTML，不用重编译。

**定位**：给自己的 App 加调试 / 监控浮层，或做 UI 层技术验证。**不含任何游戏逻辑、内存读写、进程注入或授权绕过代码**。

---

## 目录

```
dylib-project/
├── Makefile                     # Theos 构建
├── control                      # deb 元信息
├── FlashPanel.plist             # 注入过滤器（Bundles 白名单）
├── src/
│   ├── Tweak.m                  # 构造器：找 scene → 建窗口 → present
│   ├── FPWindow.h/.m            # 透明穿透 UIWindow（hitTest 局部接管）
│   ├── FPPanelController.h/.m   # 窗壳 + 拖拽/吸附/折叠 + WKWebView 宿主
│   ├── FPBridge.h/.m            # JS ⇄ Native 消息桥
│   └── FPConfig.h/.m            # 位置/折叠/键值持久化
├── layout/Library/FlashPanel/
│   └── panel.html               # 内容层（可热改，无需重编译）
├── scripts/build-clang.sh       # 不走 Theos 的快速构建
└── .github/workflows/build.yml  # CI：rootful + rootless 双包
```

## 构建

### 方式一：Theos（推荐）

```bash
export THEOS=~/theos
make package FINALPACKAGE=1
# 产物: packages/com.example.flashpanel_1.0.0_iphoneos-arm64.deb
```

无根越狱（Dopamine / palera1n rootless）：

```bash
make package FINALPACKAGE=1 THEOS_PACKAGE_SCHEME=rootless
```

### 方式二：clang 直编（只要 dylib，不打包）

```bash
chmod +x scripts/build-clang.sh && ./scripts/build-clang.sh
# 产物: build/FlashPanel.dylib
```

### 方式三：GitHub Actions

推 tag 或手动 `workflow_dispatch`，产出 `FlashPanel-rootful` / `FlashPanel-rootless` 两个 artifact；打 `v*` tag 时自动挂到 Release。

## 安装与注入

1. 安装 deb：`dpkg -i packages/*.deb`，或 Filza 直接装。
2. 改写 `FlashPanel.plist` 里的 `Bundles`，填**你自己的** App bundle id：

```xml
<key>Bundles</key>
<array><string>com.yourcompany.yourapp</string></array>
```

3. 重装包，或 `killall -9 SpringBoard`。

非越狱设备可用 TrollFools / Sideloadly 之类工具把 dylib 注入自签 IPA，注意 `panel.html` 需一并放进 App 沙盒（改 `loadContent` 里的候选路径即可）。

## 运行时行为

| 项 | 实现 |
|---|---|
| 窗口层级 | `UIWindowLevelAlert + 10`，不抢 key window |
| 穿透 | `hitTest` 只接管 `interactiveRect` 内的触摸，其余下发给宿主 |
| 拖拽 | 原生标题条 Pan，松手贴边并持久化位置 |
| 折叠 | 弹簧动画缩为 54pt 气泡，可拖动、点击展开 |
| 内容 | `loadFileURL` 读 `/Library/FlashPanel/panel.html`，缺失时退化占位页 |
| 持久化 | `NSUserDefaults` suite `com.flashpanel.config` |

## JS ⇄ Native 协议

JS 侧发消息：

```js
window.webkit.messageHandlers.fp.postMessage({ cmd: 'collapse' });
window.webkit.messageHandlers.fp.postMessage({ cmd: 'value', key: 'threshold.0', value: 6.0 });
window.webkit.messageHandlers.fp.postMessage({ cmd: 'haptic' });
```

| cmd | 作用 |
|---|---|
| `ready` | 页面就绪 |
| `collapse` | 折叠为气泡 |
| `close` | 关闭面板 |
| `value` | 写入 `key/value`，落到配置文件 |
| `haptic` | 轻触反馈 |
| `log` | 转发到 `NSLog` |

Native → JS（页面需实现 `window.FP`）：

```js
window.FP = {
  push(d) { /* {fps, cpu, mem, uptime, ts} */ },
  event(e) { /* {t:'c'|'w'|'o'|'i', title, desc} */ },
  theme(color) { /* 覆盖主色 */ }
};
```

## 宿主集成

```objc
// 显隐
[[NSNotificationCenter defaultCenter] postNotificationName:@"FPShowPanel" object:nil];
[[NSNotificationCenter defaultCenter] postNotificationName:@"FPHidePanel" object:nil];

// 推真实指标（拿到 FPPanelController 实例后）
[panel updateMetrics:@{@"fps": @(59.4), @"cpu": @(23.1), @"mem": @(184.0)}];
[panel pushEvent:@{@"t": @"c", @"title": @"帧率骤降", @"desc": @"持续 3s 低于 30fps"}];
```

## 改 UI

直接编辑 `layout/Library/FlashPanel/panel.html`，重装包或推送到设备即可生效——**不需要重编译 dylib**。深色/浅色、主题色、模块增删都在这一层。

`panel.html` 里预留了三处扩展点：`RULES` 数组（规则列表）、`DEMO` 数组（空态演示事件）、`window.FP` 对象（接收宿主数据）。

## 已知限制

- 只做了 `arm64 / arm64e`，iOS 14+；更老的 armv7 需自行加 arch。
- `WKWebView` 常驻会占 30–60MB，面板关闭后进程仍在——需要极致省内存的场景建议关面板时 `[_web loadHTMLString:@"" baseURL:nil]` 释放内容。
- rootless 的路径前缀已做双路径探测（`/var/jb/Library` 优先），自定义路径时留意。
- 未做横屏 SafeArea 适配，横屏需要自行调整 `defaultFrame`。

## 边界

这个工程只解决「如何在任意 App 上叠一层可交互、可穿透、可折叠、可热更的 HUD」。它不读写宿主进程内存、不 hook 宿主方法、不联网、不携带任何业务判定逻辑。若你要做的是游戏内辅助或授权绕过，这个框架帮不上，也不应当那么用。
