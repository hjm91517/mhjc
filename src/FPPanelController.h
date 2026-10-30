#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>

NS_ASSUME_NONNULL_BEGIN

@class FPWindow;

/// 悬浮面板控制器：原生窗壳（拖拽 / 折叠 / 关闭）+ WKWebView 内容层。
@interface FPPanelController : UIViewController

- (instancetype)initWithWindow:(FPWindow *)window;

- (void)present;
- (void)dismiss;

/// 宿主可主动推送真实指标；不调用时使用内置演示数据。
- (void)updateMetrics:(NSDictionary *)metrics;
- (void)pushEvent:(NSDictionary *)event;

@end

NS_ASSUME_NONNULL_END
