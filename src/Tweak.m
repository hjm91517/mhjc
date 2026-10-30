#import <UIKit/UIKit.h>
#import "FPWindow.h"
#import "FPPanelController.h"

/// FlashPanel 启动器：纯 UI 浮层，不 hook 任何宿主类，不做任何业务注入。
/// 宿主通过 NSNotification 控制显隐：
///   [[NSNotificationCenter defaultCenter] postNotificationName:@"FPShowPanel" object:nil];

static FPWindow *gWindow;
static FPPanelController *gPanel;
static BOOL gShown;

static UIWindowScene *FPActiveScene(void) {
    UIWindowScene *fallback = nil;
    for (UIScene *s in UIApplication.sharedApplication.connectedScenes) {
        if (![s isKindOfClass:UIWindowScene.class]) continue;
        if (s.activationState == UISceneActivationStateForegroundActive) return (UIWindowScene *)s;
        if (!fallback) fallback = (UIWindowScene *)s;
    }
    return fallback;
}

static void FPBoot(void) {
    if (gWindow) {
        if (!gShown) { gWindow.hidden = NO; gShown = YES; [gPanel present]; }
        return;
    }
    UIWindowScene *scene = FPActiveScene();
    if (!scene) return;

    gWindow = [[FPWindow alloc] initWithWindowScene:scene];
    gPanel = [[FPPanelController alloc] initWithWindow:gWindow];
    gWindow.rootViewController = gPanel;
    gWindow.hidden = NO;
    gShown = YES;
    [gPanel present];
}

static void FPShow(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        FPBoot();
        if (gWindow) {
            gWindow.hidden = NO;
            gShown = YES;
            [gPanel present];
        }
    });
}

static void FPHide(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        [gPanel dismiss];
        gShown = NO;
    });
}

__attribute__((constructor))
static void FlashPanelInit(void) {
    NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;

    [nc addObserverForName:UIApplicationDidFinishLaunchingNotification
                    object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *n) {
        // 场景可能稍后才就绪，做有限次重试
        __block int tries = 0;
        __block void (^retry)(void);
        retry = ^{
            if (FPActiveScene() || ++tries > 20) { FPBoot(); return; }
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.25 * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), retry);
        };
        retry();
    }];

    [nc addObserverForName:UISceneDidActivateNotification
                    object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *n) { FPBoot(); }];

    [nc addObserverForName:@"FPShowPanel" object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *n) { FPShow(); }];

    [nc addObserverForName:@"FPHidePanel" object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *n) { FPHide(); }];

    // 宿主已在前台时，延迟一拍直接拉起
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.2 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        if (!gWindow && UIApplication.sharedApplication.applicationState == UIApplicationStateActive) {
            FPBoot();
        }
    });
}
