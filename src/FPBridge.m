#import "FPBridge.h"
#import <UIKit/UIKit.h>

@implementation FPBridge

- (void)attachToController:(WKUserContentController *)ucc {
    [ucc addScriptMessageHandler:self name:@"fp"];
}

- (void)userContentController:(WKUserContentController *)ucc
      didReceiveScriptMessage:(WKScriptMessage *)message {
    if (![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *body = message.body;
    NSString *cmd = body[@"cmd"];
    if (![cmd isKindOfClass:NSString.class]) return;

    if ([cmd isEqualToString:@"collapse"]) {
        [self.delegate bridgeDidRequestCollapse:self];
    } else if ([cmd isEqualToString:@"close"]) {
        [self.delegate bridgeDidRequestClose:self];
    } else if ([cmd isEqualToString:@"value"]) {
        NSString *key = body[@"key"];
        if (key.length) [self.delegate bridge:self setValue:body[@"value"] forKey:key];
    } else if ([cmd isEqualToString:@"log"]) {
        NSLog(@"[FlashPanel] %@", body[@"msg"] ?: @"");
    } else if ([cmd isEqualToString:@"haptic"]) {
        UIImpactFeedbackGenerator *g =
            [[UIImpactFeedbackGenerator alloc] initWithStyle:UIImpactFeedbackStyleLight];
        [g impactOccurred];
    }
}

- (void)evalFunction:(NSString *)fn payload:(nullable id)payload {
    if (!self.webView) return;
    NSString *json = @"null";
    if (payload) {
        NSData *d = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
        if (d) json = [[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding];
    }
    NSString *js = [NSString stringWithFormat:
        @"(function(){try{var f=window.FP&&window.FP.%@;if(typeof f==='function')f(%@);}catch(e){}})();",
        fn, json];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.webView evaluateJavaScript:js completionHandler:nil];
    });
}

@end
