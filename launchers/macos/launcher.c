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
    char entry_point[PATH_MAX];
    if (snprintf(
            project,
            sizeof(project),
            "%s/Projects/Local-assistant/personal-assistant",
            home
        ) >= (int)sizeof(project)
        || snprintf(
            entry_point,
            sizeof(entry_point),
            "%s/.venv/bin/personal-assistant-ui",
            project
        ) >= (int)sizeof(entry_point)) {
        return 1;
    }

    if (!executable(entry_point) || chdir(project) != 0) {
        return 1;
    }

    /*
     * Keep the LaunchServices-registered process and the Qt window in the same
     * PID. `uv run` otherwise stays registered while Qt opens in child Python,
     * preventing macOS accessibility clients from resolving the app reliably.
     */
    execl(entry_point, entry_point, (char *)NULL);
    return 1;
}
