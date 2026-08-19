cmake_minimum_required(VERSION 3.20)
project(NativeMenu LANGUAGES CXX)

add_executable(NativeMenu WIN32 src/main.cpp)
target_compile_features(NativeMenu PRIVATE cxx_std_20)
target_compile_definitions(NativeMenu PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(NativeMenu PRIVATE comctl32)

set_target_properties(NativeMenu PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/bin")
