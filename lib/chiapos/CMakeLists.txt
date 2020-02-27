CMAKE_MINIMUM_REQUIRED(VERSION 3.1.0 FATAL_ERROR)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

IF(NOT CMAKE_BUILD_TYPE)
  SET(CMAKE_BUILD_TYPE "RELEASE")
ENDIF()

project(chiapos)

set(FSE_LIB ${CMAKE_CURRENT_SOURCE_DIR}/lib/FiniteStateEntropy/lib)
set(FSE_FILES
    ${FSE_LIB}/fse_compress.c
    ${FSE_LIB}/fse_decompress.c
    ${FSE_LIB}/entropy_common.c
    ${FSE_LIB}/hist.c
)

include_directories(
  ${INCLUDE_DIRECTORIES}
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/include
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/FiniteStateEntropy/lib
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${CMAKE_CURRENT_SOURCE_DIR}/test
  ${CMAKE_CURRENT_SOURCE_DIR}/hellman_example
  )

add_library(fse ${FSE_FILES})

add_subdirectory(lib/pybind11)

pybind11_add_module(chiapos ${CMAKE_CURRENT_SOURCE_DIR}/python-bindings/chiapos.cpp)

set (CMAKE_CXX_FLAGS "-g -O3 -Wall -msse2 -msse -march=native -std=c++1z -maes")
try_run(CMAKE_AESNI_TEST_RUN_RESULT
    CMAKE_AESNI_TEST_COMPILE_RESULT
    ${CMAKE_CURRENT_BINARY_DIR}/cmake_aesni_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/cmake_aesni_test.cpp)

# Did compilation succeed and process return 0 (success)?
IF("${CMAKE_AESNI_TEST_COMPILE_RESULT}" AND ("${CMAKE_AESNI_TEST_RUN_RESULT}" EQUAL 0))
    message(STATUS "AESNI Enabled")
    set (CMAKE_CXX_FLAGS "-g -O3 -Wall -msse2 -msse -march=native -std=c++17 -maes")
ELSE()
    message(STATUS "AESNI Disabled")
    add_compile_definitions (DISABLE_AESNI)
    set (CMAKE_CXX_FLAGS "-g -O3 -Wall -march=native -std=c++17")
ENDIF()

add_executable(ProofOfSpace
    src/cli.cpp
)

add_executable(HellmanAttacks
    src/cli.cpp
)

add_executable(RunTests
    tests/test-main.cpp
    tests/test.cpp
)

if (${CMAKE_SYSTEM_NAME} MATCHES "Darwin")
  target_link_libraries(chiapos PRIVATE fse)
  target_link_libraries(ProofOfSpace fse)
  target_link_libraries(HellmanAttacks fse)
  target_link_libraries(RunTests fse)
else()
  target_link_libraries(chiapos PRIVATE fse stdc++fs)
  target_link_libraries(ProofOfSpace fse stdc++fs)
  target_link_libraries(HellmanAttacks fse stdc++fs)
  target_link_libraries(RunTests fse stdc++fs)
endif()
