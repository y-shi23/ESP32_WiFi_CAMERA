cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# Reuse already-downloaded managed components from repo root if present (optional)
if(EXISTS "${CMAKE_SOURCE_DIR}/../managed_components")
    set(EXTRA_COMPONENT_DIRS "${CMAKE_SOURCE_DIR}/../managed_components")
endif()
project(atk_s3_audio_stream)
