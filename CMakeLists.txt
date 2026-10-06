cmake_minimum_required(VERSION 3.16)
project(g4pec VERSION 0.1.0 LANGUAGES CXX)
find_package(Geant4 11.3 REQUIRED gdml)
if(NOT Geant4_gdml_FOUND)
  message(FATAL_ERROR "Geant4 must be built with GEANT4_USE_GDML=ON (requires Xerces-C). Select a GDML-enabled installation with Geant4_DIR.")
endif()
include(${Geant4_USE_FILE})
add_executable(g4pec src/main.cc)
target_compile_features(g4pec PRIVATE cxx_std_17)
target_link_libraries(g4pec PRIVATE ${Geant4_LIBRARIES})
target_compile_options(g4pec PRIVATE -Wall -Wextra -Wpedantic)
include(CTest)
if(BUILD_TESTING)
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  add_test(NAME optical_pipeline COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_pipeline.py
    $<TARGET_FILE:g4pec> ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME optical_benchmarks COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_optical_benchmarks.py
    $<TARGET_FILE:g4pec> ${CMAKE_CURRENT_SOURCE_DIR})
  set_tests_properties(optical_benchmarks PROPERTIES TIMEOUT 180)
  add_test(NAME cell_response COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_cell_response.py)
  set_tests_properties(cell_response PROPERTIES TIMEOUT 60)
  add_test(NAME truth_benchmarks COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_truth_benchmarks.py
    $<TARGET_FILE:g4pec> ${CMAKE_CURRENT_SOURCE_DIR})
  set_tests_properties(truth_benchmarks PROPERTIES TIMEOUT 180)
  add_test(NAME acquisition COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_acquisition.py)
  set_tests_properties(acquisition PROPERTIES TIMEOUT 60)
  add_test(NAME noise_response COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_noise.py)
  set_tests_properties(noise_response PROPERTIES TIMEOUT 60)
  add_test(NAME waveform_readout COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_readout.py)
  set_tests_properties(waveform_readout PROPERTIES TIMEOUT 60)
  add_test(NAME readout_benchmarks COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_readout_benchmarks.py)
  set_tests_properties(readout_benchmarks PROPERTIES TIMEOUT 60)
  add_test(NAME bgo_evaluation COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_bgo_evaluation.py)
  set_tests_properties(bgo_evaluation PROPERTIES TIMEOUT 60)
  add_test(NAME fixed_gate COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_fixed_gate.py)
  set_tests_properties(fixed_gate PROPERTIES TIMEOUT 60)
  add_test(NAME user_settings COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_settings.py)
  set_tests_properties(user_settings PROPERTIES TIMEOUT 60)
  add_test(NAME cause_separation COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_cause_separation.py)
  set_tests_properties(cause_separation PROPERTIES TIMEOUT 60)
  add_test(NAME coincidences COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_coincidences.py)
  set_tests_properties(coincidences PROPERTIES TIMEOUT 60)
  add_test(NAME sipm_dataset COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_sipm_dataset.py)
  set_tests_properties(sipm_dataset PROPERTIES TIMEOUT 60)
  add_test(NAME multi_channel_response COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_channels.py $<TARGET_FILE:g4pec>)
  set_tests_properties(multi_channel_response PROPERTIES TIMEOUT 180)
  add_test(NAME head_features COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_head_features.py)
  set_tests_properties(head_features PROPERTIES TIMEOUT 60)
  add_test(NAME dual_sipm_pipeline COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_dual_sipm.py $<TARGET_FILE:g4pec>)
  set_tests_properties(dual_sipm_pipeline PROPERTIES TIMEOUT 180)
  add_test(NAME opposed_heads_pipeline COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_opposed_heads.py $<TARGET_FILE:g4pec>)
  set_tests_properties(opposed_heads_pipeline PROPERTIES TIMEOUT 180)
  add_test(NAME geometry_contract COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_geometry_contract.py $<TARGET_FILE:g4pec>)
  set_tests_properties(geometry_contract PROPERTIES TIMEOUT 180)
  add_test(NAME configured_pipeline COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/check_configured_pipeline.py $<TARGET_FILE:g4pec>)
  set_tests_properties(configured_pipeline PROPERTIES TIMEOUT 180)
endif()
