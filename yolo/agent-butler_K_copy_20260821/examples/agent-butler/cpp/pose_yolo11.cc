// Copyright (c) 2024 by Rockchip Electronics Co., Ltd. All Rights Reserved.
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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "pose_yolo11.h"
#include "common.h"
#include "file_utils.h"
#include "image_utils.h"

#include <sys/time.h>

static inline int64_t getCurrentTimeUs()
{
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return tv.tv_sec * 1000000 + tv.tv_usec;
}

static void dump_tensor_attr(torq_tensor_attr *attr)
{
    printf("  index=%d, name=%s, n_dims=%d, dims=[%d, %d, %d, %d], n_elems=%d, size=%d, fmt=%s, type=%s, qnt_type=%s, "
           "zp=%d, scale=%f\n",
           attr->index, attr->name, attr->n_dims, attr->dims[0], attr->dims[1], attr->dims[2], attr->dims[3],
           attr->n_elems, attr->size, get_format_string(attr->fmt), get_type_string(attr->type),
           get_qnt_type_string(attr->qnt_type), attr->zp, attr->scale);
}

int init_pose_yolo11_model(const char *model_path, pose_torq_app_context_t *app_ctx)
{
    int ret;
    torq_context ctx = 0;

    ret = torq_init(&ctx, (char *)model_path, 0, 0, NULL);
    if (ret < 0)
    {
        printf("torq_init fail! ret=%d\n", ret);
        return -1;
    }

    // Get Model Input Output Number
    torq_input_output_num io_num;
    ret = torq_query(ctx, TORQ_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
    if (ret != TORQ_SUCC)
    {
        printf("torq_query fail! ret=%d\n", ret);
        return -1;
    }
    printf("model input num: %d, output num: %d\n", io_num.n_input, io_num.n_output);

    // Get Model Input Info
    printf("input tensors:\n");
    torq_tensor_attr input_attrs[io_num.n_input];
    memset(input_attrs, 0, sizeof(input_attrs));
    for (int i = 0; i < io_num.n_input; i++)
    {
        input_attrs[i].index = i;
        ret = torq_query(ctx, TORQ_QUERY_INPUT_ATTR, &(input_attrs[i]), sizeof(torq_tensor_attr));
        if (ret != TORQ_SUCC)
        {
            printf("torq_query fail! ret=%d\n", ret);
            return -1;
        }
        dump_tensor_attr(&(input_attrs[i]));
    }

    // Get Model Output Info
    printf("output tensors:\n");
    torq_tensor_attr output_attrs[io_num.n_output];
    memset(output_attrs, 0, sizeof(output_attrs));
    for (int i = 0; i < io_num.n_output; i++)
    {
        output_attrs[i].index = i;
        ret = torq_query(ctx, TORQ_QUERY_OUTPUT_ATTR, &(output_attrs[i]), sizeof(torq_tensor_attr));
        if (ret != TORQ_SUCC)
        {
            printf("torq_query fail! ret=%d\n", ret);
            return -1;
        }
        dump_tensor_attr(&(output_attrs[i]));
    }

    // Set to context
    app_ctx->torq_ctx = ctx;

    // TODO
    if (output_attrs[0].qnt_type == TORQ_TENSOR_QNT_AFFINE_ASYMMETRIC && output_attrs[0].type != TORQ_TENSOR_FLOAT16 && output_attrs[0].type != TORQ_TENSOR_BFLOAT16)
    {
        app_ctx->is_quant = true;
    }
    else
    {
        app_ctx->is_quant = false;
    }

    app_ctx->io_num = io_num;
    app_ctx->input_attrs = (torq_tensor_attr *)malloc(io_num.n_input * sizeof(torq_tensor_attr));
    memcpy(app_ctx->input_attrs, input_attrs, io_num.n_input * sizeof(torq_tensor_attr));
    app_ctx->output_attrs = (torq_tensor_attr *)malloc(io_num.n_output * sizeof(torq_tensor_attr));
    memcpy(app_ctx->output_attrs, output_attrs, io_num.n_output * sizeof(torq_tensor_attr));

    if (input_attrs[0].fmt == TORQ_TENSOR_NCHW)
    {
        printf("model is NCHW input fmt\n");
        app_ctx->model_channel = input_attrs[0].dims[1];
        app_ctx->model_height = input_attrs[0].dims[2];
        app_ctx->model_width = input_attrs[0].dims[3];
    }
    else
    {
        printf("model is NHWC input fmt\n");
        app_ctx->model_height = input_attrs[0].dims[1];
        app_ctx->model_width = input_attrs[0].dims[2];
        app_ctx->model_channel = input_attrs[0].dims[3];
    }
    printf("model input height=%d, width=%d, channel=%d\n",
           app_ctx->model_height, app_ctx->model_width, app_ctx->model_channel);

    return 0;
}

int release_pose_yolo11_model(pose_torq_app_context_t *app_ctx)
{
    if (app_ctx->input_attrs != NULL)
    {
        free(app_ctx->input_attrs);
        app_ctx->input_attrs = NULL;
    }
    if (app_ctx->output_attrs != NULL)
    {
        free(app_ctx->output_attrs);
        app_ctx->output_attrs = NULL;
    }
    if (app_ctx->torq_ctx != 0)
    {
        torq_destroy(app_ctx->torq_ctx);
        app_ctx->torq_ctx = 0;
    }
    return 0;
}


int inference_pose_yolo11_model(pose_torq_app_context_t *app_ctx, image_buffer_t *img, pose_object_detect_result_list *od_results)
{
    if ((!app_ctx) || !(img) || (!od_results))
    {
        return -1;
    }

    int ret = -1;
    image_buffer_t dst_img;
    letterbox_t letter_box;
    torq_input inputs[app_ctx->io_num.n_input];
    torq_output outputs[app_ctx->io_num.n_output];
    const float nms_threshold = NMS_THRESH;      // Default NMS threshold
    const float box_conf_threshold = BOX_THRESH; // Default box threshold
    int bg_color = 114;
    unsigned char *input_buf = NULL;

    memset(od_results, 0x00, sizeof(*od_results));
    memset(&letter_box, 0, sizeof(letterbox_t));
    memset(&dst_img, 0, sizeof(image_buffer_t));
    memset(inputs, 0, sizeof(inputs));
    memset(outputs, 0, sizeof(outputs));

    // Pre Process
    dst_img.width = app_ctx->model_width;
    dst_img.height = app_ctx->model_height;
    dst_img.format = IMAGE_FORMAT_RGB888;
    dst_img.size = get_image_size(&dst_img);
    dst_img.virt_addr = (unsigned char *)alloc_aligned_4k(dst_img.size);
    if (dst_img.virt_addr == NULL)
    {
        printf("alloc buffer size:%d fail!\n", dst_img.size);
        goto out;
    }

    // letterbox
    ret = convert_image_with_letterbox(img, &dst_img, &letter_box, bg_color);
    if (ret < 0)
    {
        printf("convert_image_with_letterbox fail! ret=%d\n", ret);
        goto out;
    }
    // Set Input Data
    inputs[0].index = 0;
    inputs[0].fmt = TORQ_TENSOR_NHWC;
    inputs[0].pass_through = 1;  // Data is already in the model's expected format
    inputs[0].type = app_ctx->input_attrs[0].type;
    inputs[0].size = app_ctx->input_attrs[0].size;  // Use model's expected buffer size

    // For FP16/FP32 models, convert uint8 image to float; for INT8/UINT8, use as-is
    if (app_ctx->input_attrs[0].type == TORQ_TENSOR_FLOAT16) {
        input_buf = (unsigned char *)alloc_aligned_4k(inputs[0].size);
        if (input_buf == NULL) {
            goto out;
        }
        // Convert uint8 [0,255] to float16 [0.0, 1.0] normalized
        uint16_t *fp16_buf = (uint16_t *)input_buf;
        for (int i = 0; i < dst_img.size; i++) {
            float val = dst_img.virt_addr[i] / 255.0f;
            // IEEE 754 float to float16 conversion
            uint32_t f; memcpy(&f, &val, sizeof(f));
            uint32_t sign = (f >> 16) & 0x8000;
            int exp = ((f >> 23) & 0xFF) - 127 + 15;
            uint32_t frac = (f >> 13) & 0x3FF;
            if (exp <= 0) { fp16_buf[i] = sign; }
            else if (exp >= 31) { fp16_buf[i] = sign | 0x7C00; }
            else { fp16_buf[i] = sign | (exp << 10) | frac; }
        }
    } else if (app_ctx->input_attrs[0].type == TORQ_TENSOR_BFLOAT16) {
        input_buf = (unsigned char *)alloc_aligned_4k(inputs[0].size);
        if (input_buf == NULL) {
            goto out;
        }
        uint16_t *bf16_buf = (uint16_t *)input_buf;
        for (int i = 0; i < dst_img.size; i++) {
            float val = dst_img.virt_addr[i] / 255.0f;
            uint32_t f; memcpy(&f, &val, sizeof(f));
            bf16_buf[i] = (uint16_t)(f >> 16);
        }
    } else if (app_ctx->input_attrs[0].type == TORQ_TENSOR_FLOAT32) {
        input_buf = (unsigned char *)alloc_aligned_4k(inputs[0].size);
        if (input_buf == NULL) {
            goto out;
        }
        float *fp32_buf = (float *)input_buf;
        for (int i = 0; i < dst_img.size; i++) {
            fp32_buf[i] = dst_img.virt_addr[i] / 255.0f;
        }
    } else if (app_ctx->input_attrs[0].type == TORQ_TENSOR_INT8 ||
               app_ctx->input_attrs[0].type == TORQ_TENSOR_UINT8) {
        input_buf = (unsigned char *)alloc_aligned_4k(inputs[0].size);
        if (input_buf == NULL) {
            goto out;
        }
        memcpy(input_buf, dst_img.virt_addr, inputs[0].size);
    } else {
        printf("unsupported input tensor type=%d\n", app_ctx->input_attrs[0].type);
        goto out;
    }
    inputs[0].buf = input_buf;

    ret = torq_inputs_set(app_ctx->torq_ctx, app_ctx->io_num.n_input, inputs);
    if (ret < 0)
    {
        printf("torq_input_set fail! ret=%d\n", ret);
        goto out;
    }

    // Run
    printf("torq_run\n");
    int start_us,end_us;
    start_us = getCurrentTimeUs();
    ret = torq_run(app_ctx->torq_ctx, nullptr);
    end_us = getCurrentTimeUs() - start_us;
    printf("torq_run time=%.2fms, FPS = %.2f\n",end_us / 1000.f, 
            1000.f * 1000.f / end_us);

    if (ret < 0)
    {
        printf("torq_run fail! ret=%d\n", ret);
        goto out;
    }

    // Get Output
    for (int i = 0; i < app_ctx->io_num.n_output; i++)
    {
        outputs[i].index = i;
        outputs[i].want_float = (!app_ctx->is_quant);
        outputs[i].is_prealloc = 1;
        outputs[i].size = outputs[i].want_float ? app_ctx->output_attrs[i].n_elems * sizeof(float)
                                                : app_ctx->output_attrs[i].size;
        outputs[i].buf = alloc_aligned_4k(outputs[i].size);
        if (outputs[i].buf == NULL)
        {
            goto out;
        }
    }
    ret = torq_outputs_get(app_ctx->torq_ctx, app_ctx->io_num.n_output, outputs, NULL);
    if (ret < 0)
    {
        printf("torq_outputs_get fail! ret=%d\n", ret);
        goto out;
    }
    // Post Process
    start_us = getCurrentTimeUs();
    pose_post_process(app_ctx, outputs, &letter_box, box_conf_threshold, nms_threshold, od_results);
    end_us = getCurrentTimeUs() - start_us;
    printf("pose_post_process time=%.2fms, FPS = %.2f\n",end_us / 1000.f, 
            1000.f * 1000.f / end_us);
    // Remeber to release torq output
    torq_outputs_release(app_ctx->torq_ctx, app_ctx->io_num.n_output, outputs);

out:
    for (int i = 0; i < app_ctx->io_num.n_output; i++)
    {
        if (outputs[i].buf != NULL)
        {
            free(outputs[i].buf);
        }
    }
    if (input_buf != NULL)
    {
        free(input_buf);
    }
    if (dst_img.virt_addr != NULL)
    {
        free(dst_img.virt_addr);
    }

    return ret;
}
