TWEAK_NAME = FlashPanel

FlashPanel_FILES = src/Tweak.m \
                   src/FPWindow.m \
                   src/FPPanelController.m \
                   src/FPBridge.m \
                   src/FPConfig.m

FlashPanel_FRAMEWORKS = UIKit WebKit QuartzCore
FlashPanel_CFLAGS = -fobjc-arc -Wno-deprecated-declarations
FlashPanel_LDFLAGS = -undefined dynamic_lookup

ARCHS = arm64 arm64e
TARGET = iphone:clang:16.5:14.0

include $(THEOS)/makefiles/common.mk
include $(THEOS_MAKE_PATH)/tweak.mk

after-install::
	install.exec "killall -9 SpringBoard || true"
