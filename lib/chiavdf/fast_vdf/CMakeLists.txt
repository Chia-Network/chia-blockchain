CMAKE_MINIMUM_REQUIRED(VERSION 3.1.0 FATAL_ERROR)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

IF(NOT CMAKE_BUILD_TYPE)
  SET(CMAKE_BUILD_TYPE "RELEASE")
ENDIF()

project(chiavdf)

set(CMAKE_MODULE_PATH
    ${CMAKE_CURRENT_LIST_DIR}/cmake
    ${CMAKE_MODULE_PATH}
)

find_package(GMP REQUIRED)
find_package(GMPXX REQUIRED)

include_directories(
  ${INCLUDE_DIRECTORIES}
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${GMP_INCLUDE_DIR}
  ${GMPXX_INCLUDE_DIR}
)

set (CMAKE_CXX_FLAGS "-std=c++1z")

add_subdirectory(lib/pybind11)
pybind11_add_module(chiavdf ${CMAKE_CURRENT_SOURCE_DIR}/python_bindings/chiavdf.cpp)

add_executable(verifier_test
    verifier_test.cpp
)

target_link_libraries(chiavdf PRIVATE ${GMP_LIBRARIES} ${GMPXX_LIBRARIES} -pthread)
target_link_libraries(verifier_test ${GMP_LIBRARIES} ${GMPXX_LIBRARIES} -pthread)
