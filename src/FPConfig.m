#import "FPConfig.h"
#import <UIKit/UIKit.h>

static NSString *const kSuite = @"com.flashpanel.config";
static NSString *const kFrame = @"panel.frame";
static NSString *const kCollapsed = @"panel.collapsed";
static NSString *const kHeight = @"panel.height";
static NSString *const kValues = @"panel.values";

@implementation FPConfig {
    NSUserDefaults *_d;
}

+ (instancetype)shared {
    static FPConfig *s;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ s = [FPConfig new]; });
    return s;
}

- (instancetype)init {
    if (self = [super init]) {
        _d = [[NSUserDefaults alloc] initWithSuiteName:kSuite];
        _panelHeight = [_d doubleForKey:kHeight] ?: 520;
        if (_panelHeight < 320) _panelHeight = 520;
        _collapsed = [_d boolForKey:kCollapsed];
        NSString *fs = [_d stringForKey:kFrame];
        _panelFrame = fs ? CGRectFromString(fs) : CGRectZero;
        NSDictionary *v = [_d dictionaryForKey:kValues];
        _values = v ? [v mutableCopy] : [NSMutableDictionary dictionary];
    }
    return self;
}

- (void)setPanelFrame:(CGRect)f {
    _panelFrame = f;
    [_d setObject:NSStringFromCGRect(f) forKey:kFrame];
}

- (void)setPanelHeight:(CGFloat)h {
    _panelHeight = h;
    [_d setDouble:h forKey:kHeight];
}

- (void)setCollapsed:(BOOL)c {
    _collapsed = c;
    [_d setBool:c forKey:kCollapsed];
}

- (void)save {
    [_d setObject:[_values copy] forKey:kValues];
    [_d synchronize];
}

- (void)resetPosition {
    _panelFrame = CGRectZero;
    [_d removeObjectForKey:kFrame];
    [_d synchronize];
}

@end
