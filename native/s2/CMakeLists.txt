cmake_minimum_required(VERSION 3.20)
project(local_ee_s2_adapter LANGUAGES CXX)

find_package(s2 CONFIG REQUIRED)

add_library(local_ee_s2_adapter SHARED
  s2_adapter.cpp
  s2_bounds.cpp
  s2_degeneracies.cpp
  s2_input.cpp
  s2_operation.cpp
  s2_output.cpp
  s2_wire.cpp)
target_compile_features(local_ee_s2_adapter PRIVATE cxx_std_17)
target_compile_options(local_ee_s2_adapter PRIVATE -fvisibility=hidden)
target_include_directories(local_ee_s2_adapter PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>")
target_link_libraries(local_ee_s2_adapter PRIVATE s2::s2)
set_target_properties(local_ee_s2_adapter PROPERTIES
  OUTPUT_NAME local_ee_s2
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES)

# S2 is statically linked, so its compiled objects retain default visibility.
# Limit the shared library's public surface to the adapter's one C entry point.
if(APPLE)
  set(_local_ee_s2_exports "${CMAKE_CURRENT_BINARY_DIR}/local_ee_s2.exports")
  file(WRITE "${_local_ee_s2_exports}" "_local_ee_s2_run\n")
  target_link_options(local_ee_s2_adapter PRIVATE
    "LINKER:-exported_symbols_list,${_local_ee_s2_exports}")
elseif(UNIX)
  set(_local_ee_s2_exports "${CMAKE_CURRENT_BINARY_DIR}/local_ee_s2.exports")
  file(WRITE "${_local_ee_s2_exports}"
    "{ global: local_ee_s2_run; local: *; };\n")
  target_link_options(local_ee_s2_adapter PRIVATE
    "LINKER:--version-script=${_local_ee_s2_exports}")
endif()
