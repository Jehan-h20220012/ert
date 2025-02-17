#include <filesystem>
#include <string>
#include <vector>

#include <stdlib.h>

#include <ert/config/config_path_elm.hpp>

#include <fmt/format.h>

namespace fs = std::filesystem;

config_path_elm_type *config_path_elm_alloc(const fs::path &root_path,
                                            const char *path) {
    auto path_elm = new config_path_elm_type;
    if (path == NULL) {
        path_elm->path = root_path;
    } else {
        path_elm->path = root_path / path;
    }
    path_elm->path = fs::absolute(path_elm->path);
    return path_elm;
}

void config_path_elm_free(config_path_elm_type *path_elm) { delete path_elm; }

void config_path_elm_free__(void *arg) {
    auto path_elm = static_cast<config_path_elm_type *>(arg);
    config_path_elm_free(path_elm);
}

const char *config_path_elm_get_abspath(const config_path_elm_type *path_elm) {
    return path_elm->path.c_str();
}

char *config_path_elm_alloc_path(const config_path_elm_type *path_elm,
                                 const char *input_path) {
    if (input_path[0] == '/')
        return strdup(input_path);
    auto path = (path_elm->path / input_path).lexically_normal();
    return strdup(path.c_str());
}
