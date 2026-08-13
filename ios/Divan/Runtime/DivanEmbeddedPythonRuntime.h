#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

typedef void (^DivanPythonStartCompletion)(
    NSString * _Nullable endpoint,
    NSError * _Nullable error
);

@interface DivanEmbeddedPythonRuntime : NSObject

+ (instancetype)sharedRuntime;

- (void)startWithApplicationSupportPath:(NSString *)supportPath
                                  token:(NSString *)token
                             completion:(DivanPythonStartCompletion)completion;

- (void)stopWithCompletion:(dispatch_block_t)completion;

@end

NS_ASSUME_NONNULL_END
