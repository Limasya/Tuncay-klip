cmake_minimum_required(VERSION 3.20)
project(signal_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(SE_BUILD_SHARED  "Build shared library"  ON)
option(SE_BUILD_STATIC  "Build static library"  OFF)
option(SE_BUILD_TESTS   "Build tests"           ON)

# ── Compiler warnings ─────────────────────────────────────────────────────────
if(MSVC)
    add_compile_options(/W4 /permissive- /Zc:preprocessor)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# ── nlohmann/json (local header-only) ─────────────────────────────────────────
add_library(nlohmann_json INTERFACE)
target_include_directories(nlohmann_json INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party
)

# ── Sources ───────────────────────────────────────────────────────────────────
set(SE_SOURCES
    src/api.cpp
    src/audio_analyzer.cpp
    src/video_analyzer.cpp
)

set(SE_HEADERS
    include/signal_engine/api.h
    include/signal_engine/audio_analyzer.h
    include/signal_engine/video_analyzer.h
    include/signal_engine/ring_buffer.h
    include/signal_engine/types.h
)

# ── Shared library ────────────────────────────────────────────────────────────
add_library(signal_engine SHARED ${SE_SOURCES} ${SE_HEADERS})
target_include_directories(signal_engine
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(signal_engine PRIVATE nlohmann_json)

if(WIN32)
    target_compile_definitions(signal_engine PRIVATE "SE_EXPORT=__declspec(dllexport)")
else()
    target_compile_definitions(signal_engine PRIVATE "SE_EXPORT=__attribute__((visibility(\"default\")))")
endif()

set_target_properties(signal_engine PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
    POSITION_INDEPENDENT_CODE ON
    VERSION ${PROJECT_VERSION}
    SOVERSION 1
    OUTPUT_NAME "signal_engine"
    PREFIX ""
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)

# ── Static library (for tests + embedding) ─────────────────────────────────────
add_library(signal_engine_static STATIC ${SE_SOURCES} ${SE_HEADERS})
target_include_directories(signal_engine_static
    PUBLIC  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_compile_definitions(signal_engine_static PUBLIC "SE_EXPORT=")
target_link_libraries(signal_engine_static PRIVATE nlohmann_json)
set_target_properties(signal_engine_static PROPERTIES
    OUTPUT_NAME signal_engine
    POSITION_INDEPENDENT_CODE ON
)

# ── CLI ───────────────────────────────────────────────────────────────────────
add_executable(se_cli src/main.cpp)
target_link_libraries(se_cli PRIVATE signal_engine)
set_target_properties(se_cli PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# ── Tests ─────────────────────────────────────────────────────────────────────
if(SE_BUILD_TESTS)
    enable_testing()
    add_executable(se_tests tests/test_all.cpp)
    target_link_libraries(se_tests PRIVATE signal_engine_static)
    set_target_properties(se_tests PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    )
    add_test(NAME signal_engine_tests COMMAND se_tests)
endif()

# ── Install ───────────────────────────────────────────────────────────────────
install(TARGETS signal_engine se_cli
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)
install(DIRECTORY include/signal_engine DESTINATION include)
