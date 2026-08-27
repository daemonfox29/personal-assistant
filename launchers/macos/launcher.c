#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int executable(const char *path) {
    return path != NULL && access(path, X_OK) == 0;
}

int main(void) {
    const char *home = getenv("HOME");
    if (home == NULL || home[0] != '/') {
        return 1;
    }

    char project[PATH_MAX];
    char user_uv[PATH_MAX];
    if (snprintf(
            project,
            sizeof(project),
            "%s/Projects/Local-assistant/personal-assistant",
            home
        ) >= (int)sizeof(project)
        || snprintf(user_uv, sizeof(user_uv), "%s/.local/bin/uv", home)
            >= (int)sizeof(user_uv)) {
        return 1;
    }

    const char *uv = executable(user_uv)
        ? user_uv
        : executable("/opt/homebrew/bin/uv")
        ? "/opt/homebrew/bin/uv"
        : executable("/usr/local/bin/uv")
        ? "/usr/local/bin/uv"
        : NULL;
    if (uv == NULL || chdir(project) != 0) {
        return 1;
    }

    execl(uv, uv, "run", "--locked", "personal-assistant-ui", (char *)NULL);
    return 1;
}
