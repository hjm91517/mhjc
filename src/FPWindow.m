#import "FPWindow.h"

@implementation FPWindow

- (instancetype)initWithWindowScene:(UIWindowScene *)scene {
    if (self = [super initWithWindowScene:scene]) {
        self.backgroundColor = UIColor.clearColor;
        self.windowLevel = UIWindowLevelAlert + 10;
        self.rootViewController = [UIViewController new];
        self.rootViewController.view.backgroundColor = UIColor.clearColor;
        self.hidden = NO;
        // 不允许成为 key window，避免抢走宿主 App 的键盘焦点
        self.accessibilityViewIsModal = NO;
    }
    return self;
}

- (BOOL)canBecomeKeyWindow { return NO; }

- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    if (self.hidden || self.alpha < 0.01) return nil;
    if (!CGRectIsEmpty(self.interactiveRect) && CGRectContainsPoint(self.interactiveRect, point)) {
        return [super hitTest:point withEvent:event];
    }
    return nil;
}

@end
