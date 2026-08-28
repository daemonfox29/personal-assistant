#include <CommonCrypto/CommonDigest.h>
#include <Security/Security.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define RECOVERY_ACCOUNT "primary-memory-key"
#define MAX_RECOVERY_SECRET_BYTES 1024
#define TEST_RECOVERY_FD_ENV "PERSONAL_ASSISTANT_TEST_ONLY_RECOVERY_FD"
#define TEST_USER_PRESENCE_ENV "PERSONAL_ASSISTANT_TEST_ONLY_SKIP_MACOS_USER_PRESENCE"

static void clear_memory(void *value, size_t length) {
    volatile unsigned char *bytes = value;
    while (length-- > 0) {
        *bytes++ = 0;
    }
}

static int executable(const char *path) {
    return path != NULL && access(path, X_OK) == 0;
}

static int data_directory(char output[PATH_MAX]) {
    const char *configured = getenv("PERSONAL_ASSISTANT_DATA_DIR");
    const char *home = getenv("HOME");
    char candidate[PATH_MAX];
    char resolved[PATH_MAX];

    if (configured != NULL && configured[0] == '/') {
        if (snprintf(candidate, sizeof(candidate), "%s", configured) >= (int)sizeof(candidate)) {
            return -1;
        }
    } else if (
        home == NULL || home[0] != '/'
        || snprintf(candidate, sizeof(candidate), "%s/.personal-assistant", home)
            >= (int)sizeof(candidate)
    ) {
        return -1;
    }
    if (realpath(candidate, resolved) != NULL) {
        if (snprintf(output, PATH_MAX, "%s", resolved) >= PATH_MAX) {
            return -1;
        }
        return 0;
    }
    if (snprintf(output, PATH_MAX, "%s", candidate) >= PATH_MAX) {
        return -1;
    }
    return 0;
}

static int keychain_service(const char *prefix, char output[128]) {
    char directory[PATH_MAX];
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    size_t offset;
    size_t index;

    if (data_directory(directory) != 0) {
        return -1;
    }
    CC_SHA256(directory, (CC_LONG)strlen(directory), digest);
    offset = (size_t)snprintf(output, 128, "%s", prefix);
    if (offset >= 128) {
        return -1;
    }
    for (index = 0; index < 12; index++) {
        if (snprintf(output + offset, 128 - offset, "%02x", digest[index]) != 2) {
            return -1;
        }
        offset += 2;
    }
    return 0;
}

static int write_all(int descriptor, const void *value, size_t length) {
    const unsigned char *cursor = value;
    while (length > 0) {
        ssize_t written = write(descriptor, cursor, length);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        cursor += written;
        length -= (size_t)written;
    }
    return 0;
}

/* Return 1 for a credential, 0 when the isolated item is absent, or -1 on error. */
static int read_testing_credential(int descriptor) {
    char service[128];
    UInt32 length = 0;
    void *contents = NULL;
    OSStatus status;
    int result = -1;

    if (keychain_service("personal-assistant.testing-autounlock.", service) != 0) {
        return -1;
    }
    status = SecKeychainFindGenericPassword(
        NULL, (UInt32)strlen(service), service,
        (UInt32)strlen(RECOVERY_ACCOUNT), RECOVERY_ACCOUNT,
        &length, &contents, NULL
    );
    if (status == errSecItemNotFound) {
        return 0;
    }
    if (status != errSecSuccess || contents == NULL || length == 0
        || length > MAX_RECOVERY_SECRET_BYTES || memchr(contents, '\0', length) != NULL) {
        goto finish;
    }
    if (write_all(descriptor, contents, length) == 0) {
        result = 1;
    }

finish:
    if (contents != NULL) {
        clear_memory(contents, length);
        SecKeychainItemFreeContent(NULL, contents);
    }
    return result;
}

static int verify_testing_credential(void) {
    int descriptors[2];
    int result;
    if (pipe(descriptors) != 0) {
        return -1;
    }
    result = read_testing_credential(descriptors[1]);
    close(descriptors[0]);
    close(descriptors[1]);
    return result == 1 ? 0 : -1;
}

static int print_keychain_service(const char *prefix) {
    char service[128];
    if (keychain_service(prefix, service) != 0) {
        return 1;
    }
    return puts(service) < 0 ? 1 : 0;
}

int main(int argc, char *argv[]) {
    const char *home = getenv("HOME");
    char project[PATH_MAX];
    char entry_point[PATH_MAX];
    int descriptors[2];
    int credential_result;
    char descriptor_text[32];

    if (argc == 2 && strcmp(argv[1], "--print-testing-service") == 0) {
        return print_keychain_service("personal-assistant.testing-autounlock.");
    }
    if (argc == 2 && strcmp(argv[1], "--print-production-service") == 0) {
        return print_keychain_service("personal-assistant.memory-autounlock.");
    }
    if (argc == 2 && strcmp(argv[1], "--verify-testing-credential") == 0) {
        return verify_testing_credential() == 0 ? 0 : 1;
    }
    if (argc != 1 || home == NULL || home[0] != '/') {
        return 1;
    }
    if (snprintf(project, sizeof(project), "%s/Projects/Local-assistant/personal-assistant", home)
            >= (int)sizeof(project)
        || snprintf(entry_point, sizeof(entry_point), "%s/.venv/bin/personal-assistant-ui", project)
            >= (int)sizeof(entry_point)
        || !executable(entry_point) || chdir(project) != 0 || pipe(descriptors) != 0) {
        return 1;
    }
    credential_result = read_testing_credential(descriptors[1]);
    close(descriptors[1]);
    if (credential_result < 0
        || fcntl(descriptors[0], F_SETFD, 0) != 0
        || snprintf(descriptor_text, sizeof(descriptor_text), "%d", descriptors[0])
            >= (int)sizeof(descriptor_text)
        || setenv(TEST_USER_PRESENCE_ENV, "1", 1) != 0
        || setenv(TEST_RECOVERY_FD_ENV, descriptor_text, 1) != 0) {
        close(descriptors[0]);
        return 1;
    }

    /* Keep the LaunchServices process and Qt window in one PID for UI automation. */
    execl(entry_point, entry_point, (char *)NULL);
    close(descriptors[0]);
    return 1;
}
