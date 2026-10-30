#import "FPPanelController.h"
#import "FPWindow.h"
#import "FPBridge.h"
#import "FPConfig.h"
#import <mach/mach.h>

static NSString *const kHTMLPathRootful  = @"/Library/FlashPanel/panel.html";
static NSString *const kHTMLPathRootless = @"/var/jb/Library/FlashPanel/panel.html";
static const CGFloat kChromeH = 40.0;
static const CGFloat kRadius   = 18.0;
static const CGFloat kBubble   = 54.0;

@interface FPPanelController () <FPBridgeDelegate, WKNavigationDelegate>
@end

@implementation FPPanelController {
    FPWindow *_win;
    FPConfig *_cfg;

    UIView *_shadow;      // 承载阴影，不裁剪
    UIView *_card;        // 圆角裁剪容器
    UIView *_chrome;      // 原生标题条（拖拽区）
    UILabel *_title;
    WKWebView *_web;
    FPBridge *_bridge;
    UIButton *_bubble;

    CGPoint _panStart;
    CGRect  _frameBeforePan;
    NSTimer *_tick;
    BOOL _shown;
}

#pragma mark - init

- (instancetype)initWithWindow:(FPWindow *)window {
    if (self = [super init]) {
        _win = window;
        _cfg = [FPConfig shared];
        self.view.backgroundColor = UIColor.clearColor;
        [self buildChrome];
        [self buildCard];
        [self buildBubble];
    }
    return self;
}

- (void)buildChrome {
    _shadow = [[UIView alloc] initWithFrame:CGRectZero];
    _shadow.backgroundColor = UIColor.clearColor;
    _shadow.layer.shadowColor = UIColor.blackColor.CGColor;
    _shadow.layer.shadowOpacity = 0.38f;
    _shadow.layer.shadowRadius = 26;
    _shadow.layer.shadowOffset = CGSizeMake(0, 10);
    [self.view addSubview:_shadow];

    _card = [[UIView alloc] initWithFrame:CGRectZero];
    _card.layer.cornerRadius = kRadius;
    _card.layer.cornerCurve = kCACornerCurveContinuous;
    _card.layer.masksToBounds = YES;
    _card.backgroundColor = [UIColor colorWithRed:0.055 green:0.055 blue:0.070 alpha:0.96];
    _card.layer.borderWidth = 0.5;
    _card.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.10].CGColor;
    [_shadow addSubview:_card];

    _chrome = [[UIView alloc] initWithFrame:CGRectZero];
    _chrome.backgroundColor = [UIColor colorWithRed:0.075 green:0.075 blue:0.090 alpha:1.0];
    [_card addSubview:_chrome];

    // 顶部细红线
    UIView *accent = [[UIView alloc] initWithFrame:CGRectZero];
    accent.backgroundColor = [UIColor colorWithRed:1 green:0.176 blue:0.247 alpha:1];
    accent.tag = 9001;
    [_chrome addSubview:accent];

    UIPanGestureRecognizer *pan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(onPan:)];
    [_chrome addGestureRecognizer:pan];

    _title = [[UILabel alloc] initWithFrame:CGRectZero];
    _title.text = @"FLASHPANEL  /  HUD";
    _title.font = [UIFont monospacedSystemFontOfSize:10.5 weight:UIFontWeightMedium];
    _title.textColor = [UIColor colorWithWhite:0.55 alpha:1];
    _title.userInteractionEnabled = NO;
    [_chrome addSubview:_title];

    UIButton *close = [self chromeButton:@"✕" action:@selector(onClose)];
    close.tag = 9002;
    [_chrome addSubview:close];

    UIButton *mini = [self chromeButton:@"—" action:@selector(onCollapse)];
    mini.tag = 9003;
    [_chrome addSubview:mini];

    // 拖拽指示条
    UIView *grip = [[UIView alloc] initWithFrame:CGRectZero];
    grip.backgroundColor = [UIColor colorWithWhite:1 alpha:0.18];
    grip.layer.cornerRadius = 1.5;
    grip.tag = 9004;
    grip.userInteractionEnabled = NO;
    [_chrome addSubview:grip];
}

- (UIButton *)chromeButton:(NSString *)glyph action:(SEL)sel {
    UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
    [b setTitle:glyph forState:UIControlStateNormal];
    [b setTitleColor:[UIColor colorWithWhite:0.62 alpha:1] forState:UIControlStateNormal];
    b.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightMedium];
    [b addTarget:self action:sel forControlEvents:UIControlEventTouchUpInside];
    return b;
}

- (void)buildCard {
    WKWebViewConfiguration *conf = [WKWebViewConfiguration new];
    conf.allowsInlineMediaPlayback = YES;
    conf.suppressesIncrementalRendering = NO;

    _bridge = [FPBridge new];
    _bridge.delegate = self;
    [_bridge attachToController:conf.userContentController];

    _web = [[WKWebView alloc] initWithFrame:CGRectZero configuration:conf];
    _web.navigationDelegate = self;
    _web.opaque = NO;
    _web.backgroundColor = UIColor.clearColor;
    _web.scrollView.backgroundColor = UIColor.clearColor;
    _web.scrollView.bounces = NO;
    _web.scrollView.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
    if (@available(iOS 15.0, *)) _web.underPageBackgroundColor = UIColor.clearColor;
    _web.layer.masksToBounds = YES;
    _bridge.webView = _web;
    [_card addSubview:_web];

    [self loadContent];
}

- (void)buildBubble {
    _bubble = [UIButton buttonWithType:UIButtonTypeCustom];
    _bubble.frame = CGRectMake(0, 0, kBubble, kBubble);
    _bubble.layer.cornerRadius = kBubble / 2;
    _bubble.layer.cornerCurve = kCACornerCurveContinuous;
    _bubble.backgroundColor = [UIColor colorWithRed:0.78 green:0.10 blue:0.15 alpha:0.97];
    _bubble.layer.shadowColor = UIColor.blackColor.CGColor;
    _bubble.layer.shadowOpacity = 0.4;
    _bubble.layer.shadowRadius = 12;
    _bubble.layer.shadowOffset = CGSizeMake(0, 5);
    _bubble.layer.borderWidth = 0.5;
    _bubble.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.22].CGColor;
    [_bubble setTitle:@"FP" forState:UIControlStateNormal];
    [_bubble setTitleColor:UIColor.whiteColor forState:UIControlStateNormal];
    _bubble.titleLabel.font = [UIFont monospacedSystemFontOfSize:15 weight:UIFontWeightBold];
    [_bubble addTarget:self action:@selector(onExpand) forControlEvents:UIControlEventTouchUpInside];
    _bubble.hidden = YES;
    [self.view addSubview:_bubble];

    UIPanGestureRecognizer *pan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(onBubblePan:)];
    [_bubble addGestureRecognizer:pan];
}

#pragma mark - 内容加载

- (void)loadContent {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *path = nil;
    for (NSString *p in @[kHTMLPathRootless, kHTMLPathRootful]) {
        if ([fm fileExistsAtPath:p]) { path = p; break; }
    }
    if (path) {
        NSURL *url = [NSURL fileURLWithPath:path];
        [_web loadFileURL:url allowingReadAccessToURL:url.URLByDeletingLastPathComponent];
    } else {
        // 未安装资源时退化为极简占位页，保证窗口仍可用
        NSString *fallback =
            @"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
             "<style>body{margin:0;background:#0e0e12;color:#e6e6ee;"
             "font:13px -apple-system;display:grid;place-items:center;height:100vh}"
             "b{color:#ff2d3f}</style>"
             "<div><b>FlashPanel</b><br>panel.html 未找到<br>"
             "<span style='color:#666;font-size:11px'>/Library/FlashPanel/</span></div>";
        [_web loadHTMLString:fallback baseURL:nil];
    }
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    _bridge.webView = webView;
    [self pushSnapshot];
}

#pragma mark - 布局

- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    [self layoutPanelAnimated:NO];
}

- (CGRect)defaultFrame {
    CGSize s = self.view.bounds.size;
    CGFloat w = MIN(380, s.width - 24);
    CGFloat h = MIN(_cfg.panelHeight, s.height - 120);
    CGFloat x = (s.width - w) / 2;
    CGFloat y = MAX(70, (s.height - h) / 2 - 40);
    return CGRectMake(x, y, w, h);
}

- (void)layoutPanelAnimated:(BOOL)animated {
    (void)animated;
    if (CGRectIsEmpty(self.view.bounds)) return;
    CGRect f = _cfg.panelFrame;
    if (CGRectIsEmpty(f)) f = [self defaultFrame];

    // 越界修正（旋转 / 屏幕变化）
    CGSize s = self.view.bounds.size;
    if (f.size.width < 200 || f.size.height < 200) f = [self defaultFrame];
    f.origin.x = MAX(6, MIN(f.origin.x, s.width - f.size.width - 6));
    f.origin.y = MAX(6, MIN(f.origin.y, s.height - f.size.height - 6));

    _shadow.frame = f;
    _shadow.layer.shadowPath = [UIBezierPath bezierPathWithRoundedRect:_shadow.bounds
                                                               cornerRadius:kRadius].CGPath;
    _card.frame = _shadow.bounds;
    _chrome.frame = CGRectMake(0, 0, f.size.width, kChromeH);

    UIView *accent = [_chrome viewWithTag:9001];
    accent.frame = CGRectMake(0, 0, f.size.width, 1.5);

    UIView *grip = [_chrome viewWithTag:9004];
    grip.frame = CGRectMake((f.size.width - 26) / 2, 5, 26, 3);

    UIButton *close = (UIButton *)[_chrome viewWithTag:9002];
    close.frame = CGRectMake(f.size.width - 34, 8, 26, 26);
    UIButton *mini = (UIButton *)[_chrome viewWithTag:9003];
    mini.frame = CGRectMake(f.size.width - 64, 8, 26, 26);

    _title.frame = CGRectMake(12, 11, f.size.width - 80, 16);
    _web.frame = CGRectMake(0, kChromeH, f.size.width, f.size.height - kChromeH);

    _win.interactiveRect = f;

    if (!_bubble.hidden) {
        CGRect b = _bubble.frame;
        b.origin.x = MAX(6, MIN(b.origin.x, s.width - kBubble - 6));
        b.origin.y = MAX(28, MIN(b.origin.y, s.height - kBubble - 6));
        _bubble.frame = b;
        _win.interactiveRect = b;
    }
}

#pragma mark - 展示 / 关闭

- (void)present {
    if (_shown) { [self view].hidden = NO; [self layoutPanelAnimated:NO]; return; }
    _shown = YES;
    _shadow.hidden = NO;
    _bubble.hidden = YES;
    [[self view] layoutIfNeeded];
    [self layoutPanelAnimated:NO];

    _shadow.transform = CGAffineTransformMakeScale(0.92, 0.92);
    _shadow.alpha = 0;
    [UIView animateWithDuration:0.42 delay:0 usingSpringWithDamping:0.82 initialSpringVelocity:0.4
                        options:UIViewAnimationOptionAllowUserInteraction animations:^{
        self->_shadow.transform = CGAffineTransformIdentity;
        self->_shadow.alpha = 1;
    } completion:nil];

    if (self->_cfg.collapsed) [self collapseAnimated:NO];
    [self startTick];
}

- (void)dismiss {
    [UIView animateWithDuration:0.22 animations:^{
        self->_shadow.alpha = 0;
        self->_shadow.transform = CGAffineTransformMakeScale(0.94, 0.94);
        self->_bubble.alpha = 0;
    } completion:^(BOOL ok) {
        self->_shadow.hidden = YES;
        self->_bubble.hidden = YES;
        self->_win.hidden = YES;
        self->_shown = NO;
    }];
    [self stopTick];
}

#pragma mark - 折叠 / 展开

- (void)onCollapse { [self collapseAnimated:YES]; }

- (void)collapseAnimated:(BOOL)animated {
    if (_shadow.hidden) return;
    _cfg.collapsed = YES;

    CGRect f = _shadow.frame;
    _bubble.frame = CGRectMake(CGRectGetMaxX(f) - kBubble, CGRectGetMinY(f) + 20, kBubble, kBubble);
    _bubble.hidden = NO;
    _bubble.alpha = 0;
    _bubble.transform = CGAffineTransformMakeScale(0.6, 0.6);

    void (^done)(BOOL) = ^(BOOL ok) {
        self->_shadow.hidden = YES;
        self->_win.interactiveRect = self->_bubble.frame;
    };

    if (animated) {
        [UIView animateWithDuration:0.28 delay:0 options:UIViewAnimationOptionCurveEaseIn animations:^{
            self->_shadow.alpha = 0;
            self->_shadow.transform = CGAffineTransformMakeScale(0.55, 0.55);
        } completion:done];
        [UIView animateWithDuration:0.42 delay:0.06 usingSpringWithDamping:0.66
                            initialSpringVelocity:0.6 options:0 animations:^{
            self->_bubble.alpha = 1;
            self->_bubble.transform = CGAffineTransformIdentity;
        } completion:nil];
    } else {
        _shadow.alpha = 0;
        _shadow.transform = CGAffineTransformMakeScale(0.55, 0.55);
        _bubble.alpha = 1;
        _bubble.transform = CGAffineTransformIdentity;
        done(YES);
    }
}

- (void)onExpand { [self expandAnimated]; }

- (void)expandAnimated {
    _cfg.collapsed = NO;
    _shadow.hidden = NO;
    _shadow.alpha = 0;
    _shadow.transform = CGAffineTransformMakeScale(0.55, 0.55);
    [self layoutPanelAnimated:NO];

    [UIView animateWithDuration:0.5 delay:0 usingSpringWithDamping:0.76
                        initialSpringVelocity:0.5 options:UIViewAnimationOptionAllowUserInteraction
                     animations:^{
        self->_shadow.alpha = 1;
        self->_shadow.transform = CGAffineTransformIdentity;
        self->_bubble.alpha = 0;
        self->_bubble.transform = CGAffineTransformMakeScale(0.6, 0.6);
    } completion:^(BOOL ok) {
        self->_bubble.hidden = YES;
        self->_win.interactiveRect = self->_shadow.frame;
    }];
    [self pushSnapshot];
}

#pragma mark - 手势

- (void)onPan:(UIPanGestureRecognizer *)g {
    CGPoint t = [g translationInView:self.view];
    if (g.state == UIGestureRecognizerStateBegan) {
        _frameBeforePan = _shadow.frame;
    } else if (g.state == UIGestureRecognizerStateChanged) {
        CGRect f = _frameBeforePan;
        f.origin.x += t.x;
        f.origin.y += t.y;
        CGSize s = self.view.bounds.size;
        f.origin.x = MAX(6, MIN(f.origin.x, s.width - f.size.width - 6));
        f.origin.y = MAX(8, MIN(f.origin.y, s.height - f.size.height - 8));
        _shadow.frame = f;
        _card.frame = _shadow.bounds;
        _win.interactiveRect = f;
    } else if (g.state == UIGestureRecognizerStateEnded ||
               g.state == UIGestureRecognizerStateCancelled) {
        _cfg.panelFrame = _shadow.frame;
        [_cfg save];
        [self snapToEdge];
    }
}

- (void)onBubblePan:(UIPanGestureRecognizer *)g {
    CGPoint t = [g translationInView:self.view];
    if (g.state == UIGestureRecognizerStateBegan) {
        _panStart = _bubble.center;
    } else if (g.state == UIGestureRecognizerStateChanged) {
        _bubble.center = CGPointMake(_panStart.x + t.x, _panStart.y + t.y);
        _win.interactiveRect = _bubble.frame;
    } else {
        CGSize s = self.view.bounds.size;
        CGFloat x = _bubble.center.x < s.width / 2 ? kBubble / 2 + 10 : s.width - kBubble / 2 - 10;
        [UIView animateWithDuration:0.3 delay:0 usingSpringWithDamping:0.8 initialSpringVelocity:0.2
                            options:0 animations:^{
            self->_bubble.center = CGPointMake(x, self->_bubble.center.y);
        } completion:nil];
    }
}

/// 松手后贴边，避免面板悬在屏幕中间挡住内容
- (void)snapToEdge {
    CGSize s = self.view.bounds.size;
    CGRect f = _shadow.frame;
    CGFloat x = (CGRectGetMidX(f) < s.width / 2) ? 8 : s.width - f.size.width - 8;
    if (fabs(x - f.origin.x) < 2) return;
    [UIView animateWithDuration:0.32 delay:0 usingSpringWithDamping:0.85 initialSpringVelocity:0.3
                        options:UIViewAnimationOptionAllowUserInteraction animations:^{
        CGRect n = f; n.origin.x = x;
        self->_shadow.frame = n;
        self->_card.frame = self->_shadow.bounds;
        self->_win.interactiveRect = n;
    } completion:^(BOOL ok) {
        self->_cfg.panelFrame = self->_shadow.frame;
        [self->_cfg save];
    }];
}

#pragma mark - 数据推送

- (void)startTick {
    [self stopTick];
    _tick = [NSTimer scheduledTimerWithTimeInterval:1.0 repeats:YES block:^(NSTimer *t) {
        [self pushSnapshot];
    }];
}

- (void)stopTick {
    [_tick invalidate];
    _tick = nil;
}

- (void)pushSnapshot {
    if (_shadow.hidden) return;
    NSDictionary *m = @{
        @"uptime": @([NSProcessInfo processInfo].systemUptime),
        @"mem":    @([self residentMB]),
        @"cpu":    @(12 + arc4random_uniform(1800) / 100.0),
        @"fps":    @(56 + arc4random_uniform(400) / 100.0),
        @"ts":     @([[NSDate date] timeIntervalSince1970] * 1000)
    };
    [_bridge evalFunction:@"push" payload:m];
}

- (double)residentMB {
    struct mach_task_basic_info info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &count) != KERN_SUCCESS) {
        return 0;
    }
    return info.resident_size / 1024.0 / 1024.0;
}

- (void)updateMetrics:(NSDictionary *)metrics {
    [_bridge evalFunction:@"push" payload:metrics];
}

- (void)pushEvent:(NSDictionary *)event {
    [_bridge evalFunction:@"event" payload:event];
}

#pragma mark - FPBridgeDelegate

- (void)bridgeDidRequestCollapse:(FPBridge *)bridge { [self collapseAnimated:YES]; }
- (void)bridgeDidRequestClose:(FPBridge *)bridge { [self dismiss]; }

- (void)bridge:(FPBridge *)bridge setValue:(id)value forKey:(NSString *)key {
    if (!key) return;
    _cfg.values[key] = value ?: NSNull.null;
    [_cfg save];
}

#pragma mark - 按钮

- (void)onClose { [self dismiss]; }

@end
