#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Registers the small built-in module used by Python to reach iOS Keychain.
/// This must be called before the first Py_Initialize* invocation.
FOUNDATION_EXPORT BOOL DivanPreparePythonModules(void);

NS_ASSUME_NONNULL_END
