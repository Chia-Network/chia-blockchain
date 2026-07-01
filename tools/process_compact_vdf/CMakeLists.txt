cmake_minimum_required(VERSION 3.18)
project(process_compact_vdf CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED CHIAVDF_SRC)
  set(CHIAVDF_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../chiavdf/src")
endif()

if(NOT EXISTS "${CHIAVDF_SRC}/verifier.h")
  message(FATAL_ERROR "chiavdf sources not found at ${CHIAVDF_SRC}. Pass -DCHIAVDF_SRC=/path/to/chiavdf/src")
endif()

find_package(SQLite3 REQUIRED)
find_package(CURL REQUIRED)
find_package(Threads REQUIRED)

if(APPLE)
  find_library(GMP_LIBRARY gmp REQUIRED)
  find_library(GMPXX_LIBRARY gmpxx REQUIRED)
  find_library(ZSTD_LIBRARY zstd REQUIRED)
  set(GMP_LIBRARIES ${GMP_LIBRARY} ${GMPXX_LIBRARY})
  find_path(GMP_INCLUDE_DIR gmp.h)
  find_path(GMPXX_INCLUDE_DIR gmpxx.h)
  find_path(ZSTD_INCLUDE_DIR zstd.h)
  include_directories(${GMP_INCLUDE_DIR} ${GMPXX_INCLUDE_DIR} ${ZSTD_INCLUDE_DIR})
else()
  find_package(PkgConfig REQUIRED)
  pkg_check_modules(GMP REQUIRED gmp)
  pkg_check_modules(GMPXX REQUIRED gmpxx)
  pkg_check_modules(ZSTD REQUIRED libzstd)
  set(GMP_LIBRARIES ${GMP_LIBRARIES} ${GMPXX_LIBRARIES})
  include_directories(${GMP_INCLUDE_DIRS} ${GMPXX_INCLUDE_DIRS} ${ZSTD_INCLUDE_DIRS})
endif()

add_executable(process_compact_vdf
  src/main.cpp
  src/chia_protocol.cpp
  src/clvm_length.cpp
  src/vdf_validate.cpp
  src/db_v2.cpp
  src/zstd_util.cpp
  src/mini_json.cpp
  src/process_compact_vdf.cpp
  src/export_compact_vdf.cpp
  src/http_fetch.cpp
  "${CHIAVDF_SRC}/refcode/lzcnt.c"
)

target_include_directories(process_compact_vdf PRIVATE
  src
  "${CHIAVDF_SRC}"
)

target_compile_definitions(process_compact_vdf PRIVATE
  VDF_MODE=0
  FAST_MACHINE=1
)

target_link_libraries(process_compact_vdf PRIVATE
  SQLite::SQLite3
  CURL::libcurl
  Threads::Threads
  ${GMP_LIBRARIES}
)

if(APPLE)
  target_link_libraries(process_compact_vdf PRIVATE ${ZSTD_LIBRARY})
  target_compile_definitions(process_compact_vdf PRIVATE CHIAOSX)
else()
  target_link_libraries(process_compact_vdf PRIVATE ${ZSTD_LIBRARIES})
endif()

if(UNIX AND NOT APPLE)
  target_link_libraries(process_compact_vdf PRIVATE -pthread)
endif()
