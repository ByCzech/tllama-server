cmake_minimum_required(VERSION 3.21)
project(tllama-server VERSION 0.1.0 LANGUAGES C CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "The initial runtime installation layout supports Linux only")
endif()

include(GNUInstallDirs)
include(cmake/NativeSource.cmake)

option(TLLAMA_BUILD_SERVER "Build and install the server and common runtime" ON)
set(TLLAMA_INSTALL_LIBDIR "lib/tllama/server" CACHE STRING "Relative private runtime directory")
set(TLLAMA_BACKEND_INSTALL_DIR "${TLLAMA_INSTALL_LIBDIR}" CACHE STRING "Relative backend installation directory")
set(TLLAMA_BACKEND_RPATH "" CACHE STRING "Additional SDK runtime directories for backend modules")

foreach(dir_var CMAKE_INSTALL_BINDIR TLLAMA_INSTALL_LIBDIR TLLAMA_BACKEND_INSTALL_DIR)
    if("${${dir_var}}" STREQUAL "" OR IS_ABSOLUTE "${${dir_var}}" OR
       "${${dir_var}}" MATCHES "(^|/)\\.\\.(/|$)")
        message(FATAL_ERROR "${dir_var} must be a nonempty relative path without '..'")
    endif()
endforeach()

set(native_source "${CMAKE_CURRENT_SOURCE_DIR}/vendor/llama.cpp")
if(NOT EXISTS "${native_source}/CMakeLists.txt")
    message(FATAL_ERROR "Missing native sources; run git submodule update --init --recursive")
endif()

# Source archives carry the same metadata and do not need Git at build time.
if(EXISTS "${native_source}/.git")
    find_package(Git QUIET)
    if(Git_FOUND)
        execute_process(
            COMMAND "${GIT_EXECUTABLE}" rev-parse HEAD
            WORKING_DIRECTORY "${native_source}"
            RESULT_VARIABLE revision_result
            OUTPUT_VARIABLE actual_revision
            OUTPUT_STRIP_TRAILING_WHITESPACE)
        if(NOT revision_result EQUAL 0 OR NOT actual_revision STREQUAL TLLAMA_LLAMA_REVISION)
            message(FATAL_ERROR "Native checkout differs from cmake/NativeSource.cmake; update the gitlink and metadata together")
        endif()
    endif()
endif()
string(SUBSTRING "${TLLAMA_LLAMA_REVISION}" 0 10 LLAMA_BUILD_COMMIT)
set(LLAMA_BUILD_NUMBER "${TLLAMA_LLAMA_BUILD_NUMBER}")
if(NOT EXISTS "${native_source}/.git")
    # Do not let ggml identify an enclosing, unrelated Git repository as its source.
    set(GIT_EXE "")
    set(GGML_BUILD_COMMIT "${LLAMA_BUILD_COMMIT}")
    set(GGML_GIT_DIRTY 0)
endif()

# Every build uses private shared libraries and loadable backend modules.
set(BUILD_SHARED_LIBS ON CACHE BOOL "Build shared libraries" FORCE)
set(GGML_BACKEND_DL ON CACHE BOOL "Build loadable backends" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "Avoid build-host CPU assumptions" FORCE)
if(DEFINED GGML_CPU AND NOT GGML_CPU)
    set(GGML_CPU_ALL_VARIANTS OFF CACHE BOOL "Build portable CPU variants" FORCE)
else()
    set(GGML_CPU_ALL_VARIANTS ON CACHE BOOL "Build portable CPU variants")
endif()
set(GGML_BACKEND_DIR "" CACHE PATH "Discover plugins beside the executable" FORCE)
set(LLAMA_USE_SYSTEM_GGML OFF CACHE BOOL "Use the pinned ggml source" FORCE)

set(LLAMA_BUILD_COMMON "${TLLAMA_BUILD_SERVER}" CACHE BOOL "Build server common code" FORCE)
set(LLAMA_BUILD_TOOLS "${TLLAMA_BUILD_SERVER}" CACHE BOOL "Configure server targets" FORCE)
set(LLAMA_BUILD_SERVER "${TLLAMA_BUILD_SERVER}" CACHE BOOL "Configure the server" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "Skip the unified app" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "Skip upstream tests" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "Skip examples" FORCE)
set(LLAMA_BUILD_UI OFF CACHE BOOL "Do not run npm" FORCE)
set(LLAMA_USE_PREBUILT_UI OFF CACHE BOOL "Do not download UI assets" FORCE)
set(LLAMA_LLGUIDANCE OFF CACHE BOOL "Do not fetch LLGuidance sources" FORCE)
set(LLAMA_BUILD_BORINGSSL OFF CACHE BOOL "Do not fetch BoringSSL sources" FORCE)
set(LLAMA_BUILD_LIBRESSL OFF CACHE BOOL "Do not fetch LibreSSL sources" FORCE)
set(LLAMA_TOOLS_INSTALL OFF CACHE BOOL "Use the private runtime install rules" FORCE)
set(LLAMA_TESTS_INSTALL OFF CACHE BOOL "Do not install upstream tests" FORCE)

set(CMAKE_BUILD_RPATH_USE_ORIGIN ON)
set(CMAKE_INSTALL_RPATH "$ORIGIN")
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH OFF)

set(LLAMA_OPENSSL ON CACHE BOOL "Enable HTTPS support")
if(TLLAMA_BUILD_SERVER AND LLAMA_OPENSSL)
    # Fail early instead of letting upstream silently build without HTTPS.
    find_package(OpenSSL REQUIRED)
endif()

# Upstream caches this list; rebuild it when backend options change.
unset(GGML_AVAILABLE_BACKENDS CACHE)
# Exclude upstream's default build and install rules. Only the dependencies of
# our runtime target are built; CLI, converters and development files are skipped.
add_subdirectory(vendor/llama.cpp native EXCLUDE_FROM_ALL)

set(runtime_targets)
if(TLLAMA_BUILD_SERVER)
    set(core_libraries ggml-base ggml llama llama-common mtmd llama-server-impl)
    foreach(target IN LISTS core_libraries)
        if(NOT TARGET "${target}")
            message(FATAL_ERROR "Required runtime target is missing: ${target}")
        endif()
        # This distribution contains runtime libraries, not development headers.
        set_target_properties("${target}" PROPERTIES PUBLIC_HEADER "" PRIVATE_HEADER "")
    endforeach()
    set_target_properties(llama-server PROPERTIES OUTPUT_NAME tllama-server)
    install(TARGETS ${core_libraries}
        LIBRARY DESTINATION "${TLLAMA_INSTALL_LIBDIR}" COMPONENT core NAMELINK_SKIP)
    install(TARGETS llama-server
        RUNTIME DESTINATION "${TLLAMA_INSTALL_LIBDIR}" COMPONENT core)
    list(APPEND runtime_targets llama-server)

    file(RELATIVE_PATH TLLAMA_LAUNCHER_TARGET
        "/${CMAKE_INSTALL_BINDIR}" "/${TLLAMA_INSTALL_LIBDIR}/tllama-server")
    configure_file(cmake/InstallLauncher.cmake.in InstallLauncher.cmake @ONLY)
    install(SCRIPT "${CMAKE_CURRENT_BINARY_DIR}/InstallLauncher.cmake" COMPONENT core)
    install(FILES "${native_source}/LICENSE"
        DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/tllama-server"
        RENAME LICENSE.llama.cpp COMPONENT core)
endif()

file(RELATIVE_PATH backend_to_core
    "/${TLLAMA_BACKEND_INSTALL_DIR}" "/${TLLAMA_INSTALL_LIBDIR}")
set(backend_rpath "$ORIGIN")
if(NOT backend_to_core STREQUAL "")
    list(APPEND backend_rpath "$ORIGIN/${backend_to_core}")
endif()
list(APPEND backend_rpath ${TLLAMA_BACKEND_RPATH})
set(backend_apis)
foreach(backend IN LISTS GGML_AVAILABLE_BACKENDS)
    if(NOT TARGET "${backend}")
        message(FATAL_ERROR "Configured backend target is missing: ${backend}")
    endif()
    string(REGEX REPLACE "^ggml-([^-]+).*" "\\1" api "${backend}")
    list(APPEND backend_apis "${api}")
    list(APPEND backends_${api} "${backend}")
    set_target_properties("${backend}" PROPERTIES
        INSTALL_RPATH "${backend_rpath}")
    install(TARGETS "${backend}"
        LIBRARY DESTINATION "${TLLAMA_BACKEND_INSTALL_DIR}" COMPONENT "backend-${api}")
    list(APPEND runtime_targets "${backend}")
endforeach()
list(REMOVE_DUPLICATES backend_apis)
foreach(api IN LISTS backend_apis)
    add_custom_target("tllama-backend-${api}" DEPENDS ${backends_${api}})
endforeach()
if(NOT runtime_targets)
    message(FATAL_ERROR "No server or backend targets were selected")
endif()
add_custom_target(tllama-runtime ALL DEPENDS ${runtime_targets})

message(STATUS "TLlama native revision: ${TLLAMA_LLAMA_REVISION}")
message(STATUS "TLlama backend components: ${backend_apis}")
message(STATUS "TLlama private runtime directory: ${TLLAMA_INSTALL_LIBDIR}")
