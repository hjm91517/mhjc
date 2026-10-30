#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

NS_ASSUME_NONNULL_BEGIN

/// 轻量配置持久化：面板位置、折叠状态、尺寸、业务键值。
@interface FPConfig : NSObject

+ (instancetype)shared;

@property (nonatomic, assign) CGRect panelFrame;
@property (nonatomic, assign) BOOL collapsed;
@property (nonatomic, assign) CGFloat panelHeight;   // 默认 520
@property (nonatomic, strong, readonly) NSMutableDictionary *values;

- (void)save;
- (void)resetPosition;

@end

NS_ASSUME_NONNULL_END
