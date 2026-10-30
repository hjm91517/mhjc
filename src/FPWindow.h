#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

/// 透明穿透窗口：只有落在 interactiveRect 内的触摸才被接管，
/// 其余区域的触摸会原样下发给宿主 App，不影响其交互。
@interface FPWindow : UIWindow

/// 窗口坐标系下的可交互区域（面板或收起后的气泡）
@property (nonatomic, assign) CGRect interactiveRect;

@end

NS_ASSUME_NONNULL_END
