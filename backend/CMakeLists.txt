cmake_minimum_required(VERSION 3.15...3.30)
project(newswitchSources LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Build the reusable C++ core, but not the standalone terminal app: for the
# Python wheel we only need the library to link into the extension module.
set(UC2DEVICES_BUILD_APP OFF CACHE BOOL "" FORCE)

# disable subdirectory building for now -> use later when everything is working, but maybe its also not required
#add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/newswitch/uc2_devices)

# Not building pybind extensions for now -> Build standalone first and than cleanly add the pybind extensions to the build system

#[[
# pybind11 is provided by the build environment (see pyproject.toml build deps).
set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 CONFIG REQUIRED)
find_package(Threads REQUIRED)

pybind11_add_module(_hikcam newswitch/uc2_devices/bindings/hikcam_py.cpp)
target_link_libraries(_hikcam PRIVATE uc2devices_core)

# Frame ring buffer: a standalone, SDK-independent module (only needs threads),
# so it builds and is importable even without the MVS camera SDK present.
pybind11_add_module(_ringbuffer
    newswitch/uc2_devices/bindings/ringbuffer_py.cpp
    newswitch/uc2_devices/core/src/Ringbuffer.cpp)
target_include_directories(_ringbuffer PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/newswitch/uc2_devices/core/include")
target_link_libraries(_ringbuffer PRIVATE Threads::Threads)
install(TARGETS _ringbuffer DESTINATION newswitchSources/uc2_devices)

# Bake the MVS runtime library directory into the module's rpath so importing
# the extension works without exporting LD_LIBRARY_PATH.

set_target_properties(_hikcam PROPERTIES
    BUILD_RPATH   "${UC2DEVICES_MVS_LIB_DIR}"
    INSTALL_RPATH "${UC2DEVICES_MVS_LIB_DIR}")
# Install the extension next to the pure-Python package (see wheel.packages).
install(TARGETS _hikcam DESTINATION newswitchSources/uc2_devices)

]]