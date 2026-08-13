#import "DivanPythonModule.h"

#import <Python/Python.h>
#import <Security/Security.h>

static NSString *const DivanKeychainService =
    @"com.furkancanyilmaz.divan.provider-credentials";

static NSDictionary *DivanKeychainQuery(NSString *account) {
    return @{
        (__bridge id)kSecClass: (__bridge id)kSecClassGenericPassword,
        (__bridge id)kSecAttrService: DivanKeychainService,
        (__bridge id)kSecAttrAccount: account,
    };
}

static PyObject *DivanKeychainGet(PyObject *self, PyObject *args) {
    const char *rawKey = NULL;
    if (!PyArg_ParseTuple(args, "s:keychain_get", &rawKey)) {
        return NULL;
    }

    NSString *key = [NSString stringWithUTF8String:rawKey ?: ""];
    if (key.length == 0 || key.length > 256) {
        PyErr_SetString(PyExc_ValueError, "invalid Keychain key");
        return NULL;
    }

    NSMutableDictionary *query = [DivanKeychainQuery(key) mutableCopy];
    query[(__bridge id)kSecReturnData] = @YES;
    query[(__bridge id)kSecMatchLimit] = (__bridge id)kSecMatchLimitOne;

    CFTypeRef result = NULL;
    OSStatus status = SecItemCopyMatching(
        (__bridge CFDictionaryRef)query,
        &result
    );
    if (status == errSecItemNotFound) {
        return PyUnicode_FromString("");
    }
    if (status != errSecSuccess || result == NULL) {
        if (result != NULL) {
            CFRelease(result);
        }
        PyErr_Format(PyExc_RuntimeError,
                     "Keychain read failed (%d)",
                     (int)status);
        return NULL;
    }

    NSData *data = CFBridgingRelease(result);
    NSString *value = [[NSString alloc] initWithData:data
                                            encoding:NSUTF8StringEncoding];
    if (value == nil) {
        PyErr_SetString(PyExc_ValueError, "Keychain value is not UTF-8");
        return NULL;
    }
    return PyUnicode_FromString(value.UTF8String ?: "");
}

static PyObject *DivanKeychainPut(PyObject *self, PyObject *args) {
    const char *rawKey = NULL;
    const char *rawValue = NULL;
    if (!PyArg_ParseTuple(args, "ss:keychain_put", &rawKey, &rawValue)) {
        return NULL;
    }

    NSString *key = [NSString stringWithUTF8String:rawKey ?: ""];
    NSString *value = [NSString stringWithUTF8String:rawValue ?: ""];
    if (key.length == 0 || key.length > 256 || value.length > 8192) {
        PyErr_SetString(PyExc_ValueError, "invalid Keychain value");
        return NULL;
    }

    NSDictionary *query = DivanKeychainQuery(key);
    OSStatus status;
    if (value.length == 0) {
        status = SecItemDelete((__bridge CFDictionaryRef)query);
        if (status == errSecItemNotFound) {
            status = errSecSuccess;
        }
    } else {
        NSData *data = [value dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *attributes = @{
            (__bridge id)kSecValueData: data,
            (__bridge id)kSecAttrAccessible:
                (__bridge id)kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        };
        status = SecItemUpdate((__bridge CFDictionaryRef)query,
                               (__bridge CFDictionaryRef)attributes);
        if (status == errSecItemNotFound) {
            NSMutableDictionary *item = [query mutableCopy];
            [item addEntriesFromDictionary:attributes];
            status = SecItemAdd((__bridge CFDictionaryRef)item, NULL);
        }
    }

    if (status != errSecSuccess) {
        PyErr_Format(PyExc_RuntimeError,
                     "Keychain write failed (%d)",
                     (int)status);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyMethodDef DivanIOSMethods[] = {
    {"keychain_get", DivanKeychainGet, METH_VARARGS,
     "Read one provider credential from iOS Keychain."},
    {"keychain_put", DivanKeychainPut, METH_VARARGS,
     "Write one provider credential to iOS Keychain."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef DivanIOSModule = {
    PyModuleDef_HEAD_INIT,
    "_divan_ios",
    "Narrow native services used by the embedded Divan server.",
    -1,
    DivanIOSMethods,
};

PyMODINIT_FUNC PyInit__divan_ios(void) {
    return PyModule_Create(&DivanIOSModule);
}

BOOL DivanPreparePythonModules(void) {
    return PyImport_AppendInittab("_divan_ios", &PyInit__divan_ios) == 0;
}
