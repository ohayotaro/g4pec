cmake_minimum_required(VERSION 3.16)
project(g4pec_g4sipm_evaluation LANGUAGES CXX)

# This is a separate opt-in evaluation; the g4pec application never links it.
set(G4SIPM_SOURCE "" CACHE PATH "Checkout of the pinned upstream G4SiPM source")
find_package(Git REQUIRED)
execute_process(COMMAND ${GIT_EXECUTABLE} -C "${G4SIPM_SOURCE}" rev-parse HEAD
  RESULT_VARIABLE revision_status OUTPUT_VARIABLE revision OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT revision_status EQUAL 0 OR NOT revision STREQUAL "40b0017f266c0708c39c595ebb4d09385acc2717")
  message(FATAL_ERROR "Evaluation requires G4SiPM commit 40b0017f266c0708c39c595ebb4d09385acc2717")
endif()

find_package(Geant4 11.3 REQUIRED)
include(${Geant4_USE_FILE})
set(Boost_USE_MULTITHREADED OFF)
set(Boost_USE_STATIC_LIBS ON)
find_package(Boost 1.50 REQUIRED COMPONENTS date_time regex)

# The upstream physics-list helper calls G4OpticalPhysics::Configure, removed
# from modern Geant4. It is unnecessary for response-only characterization.
file(GLOB_RECURSE upstream_sources CONFIGURE_DEPENDS "${G4SIPM_SOURCE}/g4sipm/src/*.cc")
list(FILTER upstream_sources EXCLUDE REGEX "/OpticalPhysicsList\\.cc$")
# Package geometry is not used by the response probe. Its old visualization
# helper also references the removed G4VisAttributes::Invisible constant.
list(FILTER upstream_sources EXCLUDE REGEX "/housing/")
add_library(g4sipm_evaluation_response STATIC ${upstream_sources})
target_include_directories(g4sipm_evaluation_response PUBLIC
  "${G4SIPM_SOURCE}/g4sipm/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(g4sipm_evaluation_response PUBLIC
  ${Geant4_LIBRARIES} ${Boost_LIBRARIES})
target_compile_features(g4sipm_evaluation_response PUBLIC cxx_std_17)
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  # Restore the removed base-class typedefs used by the upstream comparator.
  # This libc++ compatibility switch does not change its ordering behaviour.
  target_compile_definitions(g4sipm_evaluation_response PUBLIC
    _LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION)
endif()

add_executable(g4sipm_response_probe response_probe.cc)
target_link_libraries(g4sipm_response_probe PRIVATE g4sipm_evaluation_response)
enable_testing()
add_test(NAME upstream_response_characterization
  COMMAND g4sipm_response_probe "${CMAKE_CURRENT_BINARY_DIR}/response-report.json")
set_tests_properties(upstream_response_characterization PROPERTIES TIMEOUT 30)
