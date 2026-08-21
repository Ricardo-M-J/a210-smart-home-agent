cmake_minimum_required(VERSION 3.10)

project(torq_agent_butler_demo)

if (ENABLE_ASAN)
    message(STATUS "BUILD WITH ADDRESS SANITIZER")
    set(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
    set(CMAKE_LINKER_FLAGS_DEBUG "${CMAKE_LINKER_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
endif ()

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_INSTALL_RPATH "$ORIGIN/lib")

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/ 3rdparty.out)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../utils/ utils.out)

add_executable(${PROJECT_NAME}
    main.cc
    det_yolo11.cc
    det_postprocess.cc
    pose_yolo11.cc
    pose_postprocess.cc
)

target_link_libraries(${PROJECT_NAME}
    imageutils
    fileutils
    imagedrawing
    ${LIBTORQRT}
    dl
)

if (CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(THREADS_PREFER_PTHREAD_FLAG ON)
    find_package(Threads REQUIRED)
    target_link_libraries(${PROJECT_NAME} Threads::Threads)
endif()

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LIBTORQRT_INCLUDES}
)

set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,-unresolved-symbols=ignore-in-shared-libs")

install(TARGETS ${PROJECT_NAME} DESTINATION .)
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/../model/bus.jpg DESTINATION ./model)
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/../model/coco_80_labels_list.txt DESTINATION ./model)
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/../model/yolo11_pose_labels_list.txt DESTINATION ./model)
install(PROGRAMS ${CMAKE_CURRENT_SOURCE_DIR}/../scripts/action_hook.sh DESTINATION ./scripts)

set(det_model_path ${CMAKE_CURRENT_SOURCE_DIR}/../model/yolo11.torq)
if (EXISTS ${det_model_path})
    install(FILES ${det_model_path} DESTINATION model)
endif()

set(pose_model_path ${CMAKE_CURRENT_SOURCE_DIR}/../model/yolo11_pose.torq)
if (EXISTS ${pose_model_path})
    install(FILES ${pose_model_path} DESTINATION model)
endif()
