#import <Foundation/Foundation.h>
#import <WebKit/WebKit.h>

NS_ASSUME_NONNULL_BEGIN

@class FPBridge;

@protocol FPBridgeDelegate <NSObject>
- (void)bridgeDidRequestCollapse:(FPBridge *)bridge;
- (void)bridgeDidRequestClose:(FPBridge *)bridge;
- (void)bridge:(FPBridge *)bridge setValue:(nullable id)value forKey:(NSString *)key;
@end

/// JS ⇄ Native 单向消息桥。JS 侧：window.webkit.messageHandlers.fp.postMessage({cmd:...})
@interface FPBridge : NSObject <WKScriptMessageHandler>

@property (nonatomic, weak) id<FPBridgeDelegate> delegate;
@property (nonatomic, weak) WKWebView *webView;

- (void)attachToController:(WKUserContentController *)ucc;

/// 调用页面内的 window.FP.<fn>(payload)
- (void)evalFunction:(NSString *)fn payload:(nullable id)payload;

@end

NS_ASSUME_NONNULL_END
