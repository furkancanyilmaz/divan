#import "DivanEmbeddedPythonRuntime.h"

#import "DivanPythonModule.h"
#import <Python/Python.h>

static NSString *const DivanPythonErrorDomain =
    @"com.furkancanyilmaz.divan.python";

@interface DivanEmbeddedPythonRuntime ()
@property(nonatomic, strong) dispatch_queue_t runtimeQueue;
@property(nonatomic, copy, nullable) NSString *endpoint;
@property(nonatomic, assign) BOOL initialized;
@end

@implementation DivanEmbeddedPythonRuntime

+ (instancetype)sharedRuntime {
    static DivanEmbeddedPythonRuntime *runtime;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        runtime = [[self alloc] initPrivate];
    });
    return runtime;
}

- (instancetype)init {
    return [DivanEmbeddedPythonRuntime sharedRuntime];
}

- (instancetype)initPrivate {
    self = [super init];
    if (self) {
        _runtimeQueue = dispatch_queue_create(
            "com.furkancanyilmaz.divan.python-runtime",
            DISPATCH_QUEUE_SERIAL
        );
    }
    return self;
}

static NSError *DivanPythonError(NSInteger code, NSString *message) {
    return [NSError errorWithDomain:DivanPythonErrorDomain
                               code:code
                           userInfo:@{NSLocalizedDescriptionKey: message}];
}

static NSString *DivanPythonExceptionMessage(void) {
    if (!PyErr_Occurred()) {
        return @"Gömülü Python başlatılamadı.";
    }

    PyObject *type = NULL;
    PyObject *value = NULL;
    PyObject *traceback = NULL;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);

    NSString *message = @"Gömülü Python hatası.";
    if (value != NULL) {
        PyObject *description = PyObject_Str(value);
        if (description != NULL) {
            const char *utf8 = PyUnicode_AsUTF8(description);
            if (utf8 != NULL) {
                message = [NSString stringWithUTF8String:utf8];
            }
            Py_DECREF(description);
        }
    }
    Py_XDECREF(type);
    Py_XDECREF(value);
    Py_XDECREF(traceback);
    return message;
}

- (NSError *)initializePythonIfNeeded {
    if (self.initialized) {
        return nil;
    }
    if (!DivanPreparePythonModules()) {
        return DivanPythonError(10, @"iOS Python modülü kaydedilemedi.");
    }

    NSString *resources = NSBundle.mainBundle.resourcePath;
    NSString *pythonHome = [resources stringByAppendingPathComponent:@"python"];
    NSString *appPath = [resources stringByAppendingPathComponent:@"app"];
    NSString *appPackagesPath =
        [resources stringByAppendingPathComponent:@"app_packages"];
    if (![[NSFileManager defaultManager] fileExistsAtPath:pythonHome] ||
        ![[NSFileManager defaultManager] fileExistsAtPath:appPath] ||
        ![[NSFileManager defaultManager] fileExistsAtPath:appPackagesPath]) {
        return DivanPythonError(
            11,
            @"Python çalışma zamanı veya Divan kaynakları uygulama paketinde bulunamadı."
        );
    }

    PyStatus status;
    PyPreConfig preconfig;
    PyConfig config;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    PyConfig_InitIsolatedConfig(&config);
    preconfig.utf8_mode = 1;
    config.buffered_stdio = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 1;

    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) {
        NSString *message = status.err_msg == NULL
            ? @"Python ön hazırlığı başarısız."
            : [NSString stringWithUTF8String:status.err_msg];
        PyConfig_Clear(&config);
        return DivanPythonError(12, message);
    }

    wchar_t *home = Py_DecodeLocale(pythonHome.UTF8String, NULL);
    status = PyConfig_SetString(&config, &config.home, home);
    PyMem_RawFree(home);
    if (PyStatus_Exception(status)) {
        NSString *message = status.err_msg == NULL
            ? @"Python ana klasörü ayarlanamadı."
            : [NSString stringWithUTF8String:status.err_msg];
        PyConfig_Clear(&config);
        return DivanPythonError(13, message);
    }

    status = PyConfig_Read(&config);
    if (PyStatus_Exception(status)) {
        NSString *message = status.err_msg == NULL
            ? @"Python yapılandırması okunamadı."
            : [NSString stringWithUTF8String:status.err_msg];
        PyConfig_Clear(&config);
        return DivanPythonError(14, message);
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        NSString *message = status.err_msg == NULL
            ? @"Python başlatılamadı."
            : [NSString stringWithUTF8String:status.err_msg];
        return DivanPythonError(15, message);
    }

    PyObject *sysPath = PySys_GetObject("path");
    PyObject *pythonPackagesPath =
        PyUnicode_FromString(appPackagesPath.UTF8String);
    PyObject *pythonAppPath = PyUnicode_FromString(appPath.UTF8String);
    if (sysPath == NULL || pythonPackagesPath == NULL ||
        pythonAppPath == NULL ||
        PyList_Insert(sysPath, 0, pythonPackagesPath) != 0 ||
        PyList_Insert(sysPath, 0, pythonAppPath) != 0) {
        Py_XDECREF(pythonPackagesPath);
        Py_XDECREF(pythonAppPath);
        return DivanPythonError(16, DivanPythonExceptionMessage());
    }
    Py_DECREF(pythonPackagesPath);
    Py_DECREF(pythonAppPath);
    if (chdir(appPath.fileSystemRepresentation) != 0) {
        return DivanPythonError(17, @"Divan çalışma klasörü açılamadı.");
    }

    self.initialized = YES;
    return nil;
}

- (void)startWithApplicationSupportPath:(NSString *)supportPath
                                  token:(NSString *)token
                             completion:(DivanPythonStartCompletion)completion {
    dispatch_async(self.runtimeQueue, ^{
        if (self.endpoint.length > 0) {
            NSString *endpoint = self.endpoint;
            dispatch_async(dispatch_get_main_queue(), ^{
                completion(endpoint, nil);
            });
            return;
        }

        BOOL alreadyInitialized = self.initialized;
        PyGILState_STATE gilState = PyGILState_UNLOCKED;
        if (alreadyInitialized) {
            gilState = PyGILState_Ensure();
        }

        NSError *initializationError = [self initializePythonIfNeeded];
        if (initializationError != nil) {
            if (alreadyInitialized) {
                PyGILState_Release(gilState);
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                completion(nil, initializationError);
            });
            return;
        }

        PyObject *entry = PyImport_ImportModule("ios_entry");
        PyObject *result = NULL;
        if (entry != NULL) {
            result = PyObject_CallMethod(
                entry,
                "start_server",
                "ss",
                supportPath.UTF8String,
                token.UTF8String
            );
        }

        NSError *error = nil;
        NSString *endpoint = nil;
        if (result == NULL) {
            error = DivanPythonError(20, DivanPythonExceptionMessage());
        } else {
            const char *raw = PyUnicode_AsUTF8(result);
            NSString *value = raw == NULL
                ? nil
                : [NSString stringWithUTF8String:raw];
            NSArray<NSString *> *parts = [value componentsSeparatedByString:@"|"];
            NSInteger port = parts.count > 0 ? parts[0].integerValue : 0;
            if (port <= 0 || port > 65535) {
                error = DivanPythonError(21, @"Python geçersiz bir yerel port döndürdü.");
            } else {
                endpoint = [NSString stringWithFormat:
                    @"http://127.0.0.1:%ld/?_divan_session=%@",
                    (long)port,
                    token
                ];
                self.endpoint = endpoint;
            }
        }
        Py_XDECREF(result);
        Py_XDECREF(entry);

        if (alreadyInitialized) {
            PyGILState_Release(gilState);
        } else {
            // The HTTP server owns Python worker threads from this point on.
            // Release the interpreter lock while keeping the runtime alive.
            PyEval_SaveThread();
        }

        dispatch_async(dispatch_get_main_queue(), ^{
            completion(endpoint, error);
        });
    });
}

- (void)stopWithCompletion:(dispatch_block_t)completion {
    dispatch_async(self.runtimeQueue, ^{
        if (self.initialized) {
            PyGILState_STATE gilState = PyGILState_Ensure();
            PyObject *entry = PyImport_ImportModule("ios_entry");
            if (entry != NULL) {
                PyObject *result = PyObject_CallMethod(entry, "stop_server", NULL);
                Py_XDECREF(result);
                Py_DECREF(entry);
            } else {
                PyErr_Clear();
            }
            PyGILState_Release(gilState);
        }
        self.endpoint = nil;
        dispatch_async(dispatch_get_main_queue(), completion);
    });
}

@end
