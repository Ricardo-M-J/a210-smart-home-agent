// Copyright (c) 2023 by Rockchip Electronics Co., Ltd. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.


#ifndef _TORQ_DEMO_YOLO11_H_
#define _TORQ_DEMO_YOLO11_H_

#include "torq_api.h"
#include "common.h"


typedef struct {
    torq_context torq_ctx;
    torq_input_output_num io_num;
    torq_tensor_attr* input_attrs;
    torq_tensor_attr* output_attrs;
    int model_channel;
    int model_width;
    int model_height;
    bool is_quant;
} det_torq_app_context_t;

#include "det_postprocess.h"


int init_det_yolo11_model(const char* model_path, det_torq_app_context_t* app_ctx);

int release_det_yolo11_model(det_torq_app_context_t* app_ctx);

int inference_det_yolo11_model(det_torq_app_context_t* app_ctx, image_buffer_t* img, det_object_detect_result_list* od_results);

#endif //_TORQ_DEMO_YOLO11_H_