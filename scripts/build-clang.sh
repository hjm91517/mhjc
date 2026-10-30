#!/usr/bin/env bash
# 不依赖 Theos 的快速构建（仅 macOS + Xcode）。
# 产物: build/FlashPanel.dylib
set -euo pipefail

SDK=$(xcrun --sdk iphoneos --show-sdk-path)
OUT=build
MIN=14.0

mkdir -p "$OUT"

SRCS=(src/Tweak.m src/FPWindow.m src/FPPanelController.m src/FPBridge.m src/FPConfig.m)

xcrun --sdk iphoneos clang \
  -arch arm64 -arch arm64e \
  -miphoneos-version-min=$MIN \
  -isysroot "$SDK" \
  -dynamiclib \
  -fobjc-arc -fmodules \
  -O2 \
  -I src \
  -framework UIKit -framework WebKit -framework QuartzCore \
  -undefined dynamic_lookup \
  -install_name @executable_path/Frameworks/FlashPanel.dylib \
  -o "$OUT/FlashPanel.dylib" \
  "${SRCS[@]}"

# 未签名的 dylib 在越狱设备上通常可直接加载；如遇签名问题可用 ldid 伪签
if command -v ldid >/dev/null 2>&1; then
  ldid -S "$OUT/FlashPanel.dylib"
  echo "ldid: 已伪签名"
fi

echo "built: $OUT/FlashPanel.dylib"
xcrun --sdk iphoneos size "$OUT/FlashPanel.dylib" 2>/dev/null || true
