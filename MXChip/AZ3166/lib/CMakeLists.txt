#  Copyright (c) Microsoft
#  Copyright (c) 2024 Eclipse Foundation
# 
#  This program and the accompanying materials are made available 
#  under the terms of the MIT license which is available at
#  https://opensource.org/license/mit.
# 
#  SPDX-License-Identifier: MIT
# 
#  Contributors: 
#     Microsoft         - Initial version
#     Frédéric Desbiens - 2024 version.

# Define ThreadX user configuration
set(TX_USER_FILE "${CMAKE_CURRENT_LIST_DIR}/threadx/tx_user.h" CACHE STRING "Enable TX user configuration")

# Define NetXDuo user configuration
set(NX_USER_FILE "${CMAKE_CURRENT_LIST_DIR}/netxduo/nx_user.h" CACHE STRING "Enable NX user configuration")
set(NXD_ENABLE_FILE_SERVERS OFF CACHE BOOL "Disable fileX dependency by netxduo")

# Core libraries
add_subdirectory(${SHARED_LIB_DIR}/threadx threadx)
add_subdirectory(${SHARED_LIB_DIR}/netxduo netxduo)
add_subdirectory(${SHARED_LIB_DIR}/jsmn jsmn)
add_subdirectory(${SHARED_LIB_DIR}/nanoprintf nanoprintf)

add_subdirectory(stm32cubef4)
add_subdirectory(mxchip_bsp)
# WICED SDK (Wi-Fi driver, prebuilt binary) is not kept in this repository: it is downloaded once from Eclipse ThreadX
# getting-started at a pinned commit, each file checked against its SHA-256. Upstream: MXChip/AZ3166/lib/wiced_sdk
set(WICED_COMMIT 37ff82f757070f3fa5364acb1ac06fcc7a5b9d38)
set(WICED_FILES
    CMakeLists.txt                 9247755ebf14f6a0c9371a6551722f6dfdb1803a4a26132a522990da20df2985
    binary_build/CMakeLists.txt    7accb6aa413ebcc9f6b0d9ba5abe6044573bea9e464d4815dc67173d4d984a29
    binary_build/inc/resources.h   6ee2df6fdc93010a246868a5a6fd6160074cca160e6e1863a12d9e37bb483a2c
    binary_build/src/43362A2_bin.c 68cebdc6b0d2a7a21658ccfd65ec1c8456a4146e98d3814168e6a6b7905d72b6
    inc/wiced_sdk.h                bf0ff429d0b300ed80b497773914bf22c363cabbb87e1fa4050898cf608a5ccc
    lib/libwiced_sdk_bin.a         7da9d6fce17252767c5c7616726fc199faa37b1b295c78098c4df7e658773e43)
while(WICED_FILES)
    list(POP_FRONT WICED_FILES _file _sha)
    set(_dst ${CMAKE_CURRENT_LIST_DIR}/wiced_sdk/${_file})
    set(_have "")
    if(EXISTS ${_dst})
        file(SHA256 ${_dst} _have)
    endif()
    if(NOT _have STREQUAL _sha)
        message(STATUS "Downloading WICED SDK: ${_file}")
        file(DOWNLOAD
            https://raw.githubusercontent.com/eclipse-threadx/getting-started/${WICED_COMMIT}/MXChip/AZ3166/lib/wiced_sdk/${_file}
            ${_dst} EXPECTED_HASH SHA256=${_sha} TLS_VERIFY ON)
    endif()
endwhile()
add_subdirectory(wiced_sdk)
